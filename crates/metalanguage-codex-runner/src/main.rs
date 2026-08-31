use std::collections::HashMap;
use std::io::IsTerminal;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use anyhow::anyhow;
use anyhow::bail;
use codex_config::TomlValue;
use codex_core::config::ConfigBuilder;
use codex_core::config::ConfigOverrides;
use codex_core_api::AbsolutePathBuf;
use codex_core_api::Arg0DispatchPaths;
use codex_core_api::AskForApproval;
use codex_core_api::AuthManager;
use codex_core_api::CodexAppsToolsCache;
use codex_core_api::CodexHomeUserInstructionsProvider;
use codex_core_api::EnvironmentManager;
use codex_core_api::EventMsg;
use codex_core_api::ExecServerRuntimePaths;
use codex_core_api::Feature;
use codex_core_api::NewThread;
use codex_core_api::Op;
use codex_core_api::SessionSource;
use codex_core_api::StartIfIdleSubmission;
use codex_core_api::StartThreadOptions;
use codex_core_api::ThreadManager;
use codex_core_api::TurnInputRequest;
use codex_core_api::UserInput;
use codex_core_api::arg0_dispatch_or_else;
use codex_core_api::build_models_manager;
use codex_core_api::empty_extension_registry;
use codex_core_api::init_state_db;
use codex_core_api::item_event_to_server_notification;
use codex_core_api::local_agent_graph_store_from_state_db;
use codex_core_api::resolve_installation_id;
use codex_core_api::set_default_originator;
use codex_core_api::thread_store_from_config;
use codex_protocol::config_types::SandboxMode;
use codex_protocol::dynamic_tools::DynamicToolCallOutputContentItem;
use codex_protocol::dynamic_tools::DynamicToolCallRequest;
use codex_protocol::dynamic_tools::DynamicToolFunctionSpec;
use codex_protocol::dynamic_tools::DynamicToolResponse;
use codex_protocol::dynamic_tools::DynamicToolSpec;
use codex_protocol::items::AgentMessageContent;
use codex_protocol::items::TurnItem;
use codex_protocol::mcp::ClientMcpExtensions;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_protocol::protocol::ExecOutputStream;
use codex_protocol::protocol::PatchApplyStatus;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
struct RunnerRequest {
    model: Option<String>,
    base_instructions: Option<String>,
    cwd: PathBuf,
    codex_home: Option<PathBuf>,
    initial_user_text: Option<String>,
    timeout_seconds: Option<u64>,
    sandbox_mode: Option<String>,
    workspace_roots: Option<Vec<PathBuf>>,
    additional_writable_roots: Option<Vec<PathBuf>>,
    spawn_child_handler_command: Option<Vec<String>>,
    mcp_servers: Option<HashMap<String, Value>>,
    sensitive_mcp_tools: Option<Vec<McpToolSelector>>,
    persist_session: Option<bool>,
    resume_rollout_path: Option<PathBuf>,
    expected_thread_id: Option<String>,
    expected_session_id: Option<String>,
    resolution_phase: Option<bool>,
}

#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq)]
#[serde(deny_unknown_fields)]
struct McpToolSelector {
    server: String,
    tool: String,
}

fn main() -> anyhow::Result<()> {
    arg0_dispatch_or_else(run_main)
}

async fn run_main(arg0_paths: Arg0DispatchPaths) -> anyhow::Result<()> {
    let _ = set_default_originator("metalanguage_codex_runner".to_string());
    let request = read_request()?;
    let timeout_seconds = request.timeout_seconds.unwrap_or(3600).max(1);

    let run = run_request(request, arg0_paths);
    match tokio::time::timeout(Duration::from_secs(timeout_seconds), run).await {
        Ok(result) => result,
        Err(_) => {
            emit(json!({
                "event": "error",
                "error_code": "timeout",
                "error_message": format!("Codex runner exceeded {timeout_seconds} seconds")
            }))?;
            bail!("Codex runner exceeded {timeout_seconds} seconds");
        }
    }
}

async fn run_request(request: RunnerRequest, arg0_paths: Arg0DispatchPaths) -> anyhow::Result<()> {
    let resolution_phase = request.resolution_phase.unwrap_or(false);
    let persist_session = request.persist_session.unwrap_or(false);
    if resolution_phase && request.resume_rollout_path.is_none() {
        bail!("conflict resolution requires resume_rollout_path");
    }
    if resolution_phase
        && (request.expected_thread_id.as_deref().is_none_or(str::is_empty)
            || request.expected_session_id.as_deref().is_none_or(str::is_empty))
    {
        bail!("conflict resolution requires exact thread and session ids");
    }
    if request.resume_rollout_path.is_some() && !resolution_phase {
        bail!("Codex resume is restricted to conflict resolution");
    }
    if resolution_phase && persist_session {
        bail!("conflict resolution cannot request research-session persistence");
    }
    if resolution_phase && request.spawn_child_handler_command.is_some() {
        bail!("spawn_child handler is forbidden during conflict resolution");
    }
    if resolution_phase && request.mcp_servers.as_ref().is_some_and(|value| !value.is_empty()) {
        bail!("MCP servers are forbidden during conflict resolution");
    }
    let cwd = normalize_existing_path(&request.cwd).context("resolve cwd")?;
    let codex_home = match request.codex_home {
        Some(path) => normalize_existing_path(&path).context("resolve codex_home")?,
        None => codex_core_api::find_codex_home()
            .context("find Codex home")?
            .to_path_buf(),
    };
    let workspace_roots =
        normalize_paths(request.workspace_roots.unwrap_or_else(|| vec![cwd.clone()]))?;
    let workspace_root_overrides = absolute_paths(&workspace_roots)?;
    let additional_writable_roots =
        normalize_paths(request.additional_writable_roots.unwrap_or_default())?;
    let additional_writable_root_overrides = absolute_paths(&additional_writable_roots)?;
    let sandbox_mode = parse_sandbox_mode(request.sandbox_mode.as_deref())?;
    let (sandbox_mode_override, permission_profile_override) = match sandbox_mode {
        SandboxMode::WorkspaceWrite => (
            None,
            Some(PermissionProfile::workspace_write_with(
                &additional_writable_root_overrides,
                NetworkSandboxPolicy::Enabled,
                /*exclude_tmpdir_env_var*/ false,
                /*exclude_slash_tmp*/ false,
            )),
        ),
        SandboxMode::ReadOnly | SandboxMode::DangerFullAccess => (Some(sandbox_mode), None),
    };
    let base_instructions = request
        .base_instructions
        .filter(|value| !value.trim().is_empty());

    let mut overrides = ConfigOverrides {
        model: request.model.filter(|value| !value.trim().is_empty()),
        base_instructions,
        cwd: Some(cwd.clone()),
        approval_policy: Some(AskForApproval::Never),
        sandbox_mode: sandbox_mode_override,
        permission_profile: permission_profile_override,
        tools_web_search_request: Some(!resolution_phase),
        ephemeral: Some(!(persist_session || request.resume_rollout_path.is_some())),
        workspace_roots: Some(workspace_root_overrides),
        additional_writable_roots,
        codex_self_exe: arg0_paths.codex_self_exe.clone(),
        codex_linux_sandbox_exe: arg0_paths.codex_linux_sandbox_exe.clone(),
        main_execve_wrapper_exe: arg0_paths.main_execve_wrapper_exe.clone(),
        ..Default::default()
    };
    if matches!(sandbox_mode, SandboxMode::DangerFullAccess) {
        overrides.workspace_roots = None;
    }

    let mcp_cli_overrides = request
        .mcp_servers
        .as_ref()
        .map(|servers| {
            servers
                .iter()
                .map(|(name, value)| {
                    serde_json::from_value::<TomlValue>(value.clone())
                        .map(|value| (format!("mcp_servers.{name}"), value))
                        .context("convert per-rollout MCP server configuration")
                })
                .collect::<anyhow::Result<Vec<_>>>()
        })
        .transpose()?
        .unwrap_or_default();
    let mut config_builder = ConfigBuilder::default()
        .codex_home(codex_home.clone())
        .harness_overrides(overrides);
    if !mcp_cli_overrides.is_empty() {
        config_builder = config_builder.cli_overrides(mcp_cli_overrides);
    }
    let mut config = config_builder.build().await.context("load Codex config")?;
    let mcp_servers = request
        .mcp_servers
        .clone()
        .unwrap_or_default()
        .into_iter()
        .map(|(name, value)| {
            serde_json::from_value(value)
                .map(|server| (name, server))
                .context("parse per-rollout MCP server configuration")
        })
        .collect::<anyhow::Result<HashMap<_, _>>>()?;
    let sensitive_tools = validate_mcp_tool_selectors(
        request.sensitive_mcp_tools.clone().unwrap_or_default(),
        &mcp_servers,
        "sensitive_mcp_tools",
    )?;
    config
        .mcp_servers
        .set(mcp_servers)
        .context("apply per-rollout MCP server configuration")?;
    config
        .features
        .disable(Feature::SpawnCsv)
        .context("disable Codex spawn CSV feature")?;
    config
        .features
        .disable(Feature::Collab)
        .context("disable Codex collab feature")?;
    config
        .features
        .disable(Feature::MultiAgentV2)
        .context("disable Codex multi-agent feature")?;

    let state_db = init_state_db(&config).await;
    let auth_manager =
        AuthManager::shared_from_config(&config, /*enable_codex_api_key_env*/ true)
            .await
            .context("initialize Codex authentication manager")?;
    let local_runtime_paths = ExecServerRuntimePaths::from_optional_paths(
        config.codex_self_exe.clone(),
        config.codex_linux_sandbox_exe.clone(),
    )
    .context("configure Codex runtime helper paths")?;
    let thread_store = thread_store_from_config(&config, state_db.clone());
    let environment_manager = Arc::new(
        EnvironmentManager::from_codex_home(
            config.codex_home.clone(),
            Some(local_runtime_paths),
            config.http_client_factory(),
        )
        .await
        .context("load Codex environment manager")?,
    );
    let installation_id = resolve_installation_id(&config.codex_home)
        .await
        .context("resolve Codex installation id")?;
    let user_instructions_provider = Arc::new(CodexHomeUserInstructionsProvider::new(
        config.codex_home.clone(),
    ));
    let agent_graph_store = local_agent_graph_store_from_state_db(state_db.as_ref());

    let thread_manager = ThreadManager::new(
        &config,
        Arc::clone(&auth_manager),
        build_models_manager(&config, Arc::clone(&auth_manager)),
        CodexAppsToolsCache::default(),
        SessionSource::Exec,
        environment_manager,
        empty_extension_registry(),
        user_instructions_provider,
        /*analytics_events_client*/ None,
        Arc::clone(&thread_store),
        agent_graph_store,
        installation_id,
        /*attestation_provider*/ None,
        /*external_time_provider*/ None,
    );

    let resumed = request.resume_rollout_path.is_some();
    let NewThread {
        thread_id,
        thread,
        session_configured,
    } = if let Some(rollout_path) = request.resume_rollout_path.as_ref() {
        let rollout_path = normalize_existing_path(rollout_path)
            .context("resolve resume_rollout_path")?;
        thread_manager
            .resume_thread_from_rollout(
                config,
                rollout_path,
                Arc::clone(&auth_manager),
                None,
                ClientMcpExtensions::default(),
            )
            .await
            .context("resume Codex thread from rollout")?
    } else {
        let mut start_options = StartThreadOptions::new(config);
        start_options.dynamic_tools = metalanguage_dynamic_tools();
        thread_manager
            .start_thread(start_options)
            .await
            .context("start Codex thread")?
    };

    if let Some(expected) = request.expected_thread_id.as_deref()
        && thread_id.to_string() != expected
    {
        bail!("resumed Codex thread id does not match expected thread id");
    }
    if let Some(expected) = request.expected_session_id.as_deref()
        && session_configured.session_id.to_string() != expected
    {
        bail!("resumed Codex session id does not match expected session id");
    }

    emit(json!({
        "event": "thread_started",
        "runner_phase": if resolution_phase { "conflict_resolution" } else { "research" },
        "resumed": resumed,
        "thread_id": thread_id.to_string(),
        "session_id": session_configured.session_id.to_string(),
        "model": session_configured.model,
        "model_provider": session_configured.model_provider_id,
        "cwd": session_configured.cwd.to_string_lossy(),
        "workspace_roots": workspace_roots
            .iter()
            .map(|path| path.to_string_lossy().to_string())
            .collect::<Vec<_>>(),
    }))?;

    let spawn_child_handler_command = request.spawn_child_handler_command.clone();
    let prompt = request
        .initial_user_text
        .unwrap_or_else(|| "Read README.md.".to_string());
    let turn_result = run_turn(
        &thread,
        &thread_id.to_string(),
        prompt,
        spawn_child_handler_command,
        sensitive_tools,
        resolution_phase,
    )
    .await;
    let persistence_result = if turn_result.is_ok() && persist_session {
        thread.ensure_rollout_materialized().await;
        match thread.flush_rollout().await {
            Ok(()) => match thread.rollout_path() {
                Some(rollout_path) => emit(json!({
                    "event": "rollout_persisted",
                    "thread_id": thread_id.to_string(),
                    "session_id": session_configured.session_id.to_string(),
                    "rollout_path": rollout_path.to_string_lossy(),
                })),
                None => Err(anyhow!("Codex rollout path was not materialized")),
            },
            Err(error) => Err(error).context("flush Codex rollout"),
        }
    } else {
        Ok(())
    };
    let shutdown_result = thread.shutdown_and_wait().await;
    let _ = thread_manager.remove_thread(&thread_id).await;

    turn_result?;
    persistence_result?;
    shutdown_result.context("shut down Codex thread")?;
    Ok(())
}

fn read_request() -> anyhow::Result<RunnerRequest> {
    if std::io::stdin().is_terminal() {
        bail!("expected request JSON on stdin");
    }

    let mut raw = String::new();
    std::io::stdin()
        .read_to_string(&mut raw)
        .context("read request JSON from stdin")?;
    serde_json::from_str(&raw).context("parse request JSON")
}

async fn run_turn(
    thread: &codex_core_api::CodexThread,
    thread_id: &str,
    prompt: String,
    spawn_child_handler_command: Option<Vec<String>>,
    sensitive_tools: Vec<McpToolSelector>,
    resolution_phase: bool,
) -> anyhow::Result<()> {
    let submission = thread
        .start_turn_if_idle(TurnInputRequest::user_input(vec![UserInput::Text {
            text: prompt,
            text_elements: Vec::new(),
        }]))
        .await
        .context("submit user input")?;
    if let StartIfIdleSubmission::NotSubmitted { reason } = submission {
        let message = format!("turn input was not submitted: {reason:?}");
        emit(json!({
            "event": "error",
            "error_code": "turn_input_not_submitted",
            "error_message": message,
        }))?;
        bail!(message);
    }

    let mut current_turn_id: Option<String> = None;
    let mut final_text = String::new();
    loop {
        let event = thread.next_event().await.context("read Codex event")?;
        match &event.msg {
            EventMsg::TurnStarted(event) => {
                current_turn_id = Some(event.turn_id.clone());
                emit(json!({
                    "event": "turn_started",
                    "turn_id": event.turn_id,
                    "model_context_window": event.model_context_window,
                }))?;
            }
            EventMsg::AgentMessageContentDelta(event) => {
                emit(json!({
                    "event": "agent_message_delta",
                    "turn_id": event.turn_id,
                    "item_id": event.item_id,
                    "text": event.delta,
                }))?;
            }
            EventMsg::AgentMessage(event) => {
                final_text = event.message.clone();
                emit(json!({
                    "event": "agent_message",
                    "text": event.message,
                    "phase": event.phase.as_ref().map(|phase| format!("{phase:?}")),
                }))?;
            }
            EventMsg::Warning(event) | EventMsg::GuardianWarning(event) => {
                emit(json!({
                    "event": "warning",
                    "message": event.message,
                }))?;
            }
            EventMsg::ExecCommandBegin(event) => {
                let mut payload = json!({
                    "event": "tool_begin",
                    "tool": "exec_command",
                    "call_id": event.call_id,
                    "turn_id": event.turn_id,
                    "cwd": event.cwd.to_string(),
                });
                if !resolution_phase {
                    payload["command"] = json!(event.command);
                }
                emit(payload)?;
            }
            EventMsg::ExecCommandOutputDelta(event) => {
                if !resolution_phase {
                    let text = String::from_utf8_lossy(&event.chunk).to_string();
                    emit(json!({
                        "event": "tool_output_delta",
                        "tool": "exec_command",
                        "call_id": event.call_id,
                        "stream": exec_output_stream_name(&event.stream),
                        "text": text,
                    }))?;
                }
            }
            EventMsg::TerminalInteraction(event) => {
                let mut payload = json!({
                    "event": "terminal_interaction",
                    "tool": "exec_command",
                    "call_id": event.call_id,
                    "process_id": event.process_id,
                });
                if !resolution_phase {
                    payload["stdin"] = json!(event.stdin);
                }
                emit(payload)?;
            }
            EventMsg::ExecCommandEnd(event) => {
                let mut payload = json!({
                    "event": "tool_end",
                    "tool": "exec_command",
                    "call_id": event.call_id,
                    "turn_id": event.turn_id,
                    "cwd": event.cwd.to_string(),
                    "exit_code": event.exit_code,
                    "status": format!("{:?}", event.status),
                    "duration_ms": event.duration.as_millis(),
                });
                if !resolution_phase {
                    payload["command"] = json!(event.command);
                }
                emit(payload)?;
            }
            EventMsg::PatchApplyBegin(event) => {
                emit(json!({
                    "event": "tool_begin",
                    "tool": "apply_patch",
                    "call_id": event.call_id,
                    "turn_id": event.turn_id,
                    "auto_approved": event.auto_approved,
                    "changed_paths": event.changes.keys().map(path_to_string).collect::<Vec<_>>(),
                }))?;
            }
            EventMsg::PatchApplyUpdated(event) => {
                emit(json!({
                    "event": "tool_update",
                    "tool": "apply_patch",
                    "call_id": event.call_id,
                    "changed_paths": event.changes.keys().map(path_to_string).collect::<Vec<_>>(),
                }))?;
            }
            EventMsg::PatchApplyEnd(event) => {
                emit(json!({
                    "event": "tool_end",
                    "tool": "apply_patch",
                    "call_id": event.call_id,
                    "turn_id": event.turn_id,
                    "success": event.success,
                    "status": patch_status(&event.status),
                    "changed_paths": event.changes.keys().map(path_to_string).collect::<Vec<_>>(),
                }))?;
            }
            EventMsg::McpToolCallBegin(event) => {
                if resolution_phase {
                    emit(json!({
                        "event": "tool_begin",
                        "tool": event.invocation.tool,
                        "namespace": format!("mcp__{}", event.invocation.server),
                        "call_id": event.call_id,
                        "arguments": {"redacted": true},
                    }))?;
                } else {
                    emit(logged_mcp_tool_begin_event(event, &sensitive_tools))?;
                }
            }
            EventMsg::McpToolCallEnd(event) => {
                emit(logged_mcp_tool_end_event(event))?;
            }
            EventMsg::ItemCompleted(event) => {
                if let TurnItem::AgentMessage(message) = &event.item {
                    let text = agent_message_text(&message.content);
                    final_text = text.clone();
                    emit(json!({
                        "event": "agent_message",
                        "turn_id": event.turn_id,
                        "item_id": message.id,
                        "text": text,
                    }))?;
                } else if !resolution_phase && let Some(notification) = mapped_item_notification(
                    &EventMsg::ItemCompleted(event.clone()),
                    thread_id,
                    current_turn_id.as_deref(),
                    &sensitive_tools,
                )? {
                    emit(json!({
                        "event": "codex_item",
                        "notification": notification,
                    }))?;
                }
            }
            EventMsg::TurnComplete(event) => {
                if let Some(error) = &event.error {
                    let error_code = codex_error_code(error.codex_error_info.as_ref());
                    emit(json!({
                        "event": "error",
                        "error_code": error_code,
                        "error_message": error.message,
                        "codex_error_info": error.codex_error_info.as_ref(),
                        "turn_id": event.turn_id,
                    }))?;
                    bail!("Codex turn failed ({error_code}): {}", error.message);
                }
                let text = event
                    .last_agent_message
                    .clone()
                    .unwrap_or_else(|| final_text.clone());
                emit(json!({
                    "event": "turn_complete",
                    "turn_id": event.turn_id,
                    "final_text": text,
                    "duration_ms": event.duration_ms,
                }))?;
                return Ok(());
            }
            EventMsg::Error(event) => {
                let error_code = codex_error_code(event.codex_error_info.as_ref());
                emit(json!({
                    "event": "error",
                    "error_code": error_code,
                    "error_message": event.message,
                    "codex_error_info": event.codex_error_info.as_ref(),
                }))?;
                bail!("Codex error ({error_code}): {}", event.message);
            }
            EventMsg::TurnAborted(event) => {
                emit(json!({
                    "event": "error",
                    "error_code": "turn_aborted",
                    "turn_id": event.turn_id,
                    "error_message": format!("{:?}", event.reason),
                }))?;
                bail!("turn aborted: {:?}", event.reason);
            }
            EventMsg::CollabAgentSpawnBegin(_)
            | EventMsg::CollabAgentSpawnEnd(_)
            | EventMsg::CollabAgentInteractionBegin(_)
            | EventMsg::CollabAgentInteractionEnd(_)
            | EventMsg::CollabWaitingBegin(_)
            | EventMsg::CollabWaitingEnd(_)
            | EventMsg::CollabCloseBegin(_)
            | EventMsg::CollabCloseEnd(_)
            | EventMsg::CollabResumeBegin(_)
            | EventMsg::CollabResumeEnd(_) => bail_with_event("collab_event_blocked")?,
            EventMsg::ExecApprovalRequest(_) => bail_with_event("exec_approval_requested")?,
            EventMsg::ApplyPatchApprovalRequest(_) => bail_with_event("patch_approval_requested")?,
            EventMsg::RequestPermissions(_) => bail_with_event("permissions_requested")?,
            EventMsg::RequestUserInput(_) => bail_with_event("user_input_requested")?,
            EventMsg::DynamicToolCallRequest(request) => {
                let mut payload = json!({
                    "event": "tool_begin",
                    "tool": request.tool,
                    "namespace": request.namespace,
                    "call_id": request.call_id,
                    "turn_id": request.turn_id,
                });
                if !resolution_phase {
                    payload["arguments"] = request.arguments.clone();
                }
                emit(payload)?;
                let response = handle_dynamic_tool_for_phase(
                    request,
                    spawn_child_handler_command.as_deref(),
                    resolution_phase,
                );
                emit(json!({
                    "event": "tool_end",
                    "tool": request.tool,
                    "namespace": request.namespace,
                    "call_id": request.call_id,
                    "turn_id": request.turn_id,
                    "success": response.success,
                }))?;
                thread
                    .submit(Op::DynamicToolResponse {
                        id: request.call_id.clone(),
                        response,
                    })
                    .await
                    .context("submit dynamic tool response")?;
            }
            _ => {}
        }
    }
}

fn codex_error_code(error_info: Option<&codex_protocol::protocol::CodexErrorInfo>) -> String {
    let Some(error_info) = error_info else {
        return "turn_failed".to_string();
    };
    match serde_json::to_value(error_info) {
        Ok(Value::String(code)) => code,
        Ok(Value::Object(details)) => details
            .into_iter()
            .next()
            .map(|(code, _)| code)
            .unwrap_or_else(|| "turn_failed".to_string()),
        Ok(value) => value.to_string(),
        Err(_) => "turn_failed".to_string(),
    }
}

fn bail_with_event(code: &str) -> anyhow::Result<()> {
    emit(json!({
        "event": "error",
        "error_code": code,
        "error_message": code,
    }))?;
    Err(anyhow!(code.to_string()))
}

fn metalanguage_dynamic_tools() -> Vec<DynamicToolSpec> {
    vec![
        DynamicToolSpec::Function(DynamicToolFunctionSpec {
            name: "spawn_child".to_string(),
            description: concat!(
                "Spawn this rollout's one possible next-iteration child. The child receives ",
                "the supplied initial prompt and a copied workspace-local directory whose ",
                "root contains a regular, non-symlinked, readable, non-blank UTF-8 README.md. ",
                "Invalid or failed attempts can be corrected and retried. After one successful ",
                "spawn, later calls from this rollout fail. Every call returns feedback and the ",
                "parent rollout continues normally."
            )
            .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Required non-empty initial user message stored for the child rollout."
                    },
                    "workspace_dir": {
                        "type": "string",
                        "description": "Required workspace-local directory copied for the child. Its root must contain a regular, non-symlinked, readable, non-blank UTF-8 README.md. Additional files are optional. The source is consumed after the parent rollout finishes only when spawning succeeds."
                    }
                },
                "required": ["prompt", "workspace_dir"],
                "additionalProperties": false,
            }),
            defer_loading: false,
        }),
    ]
}

#[cfg(test)]
fn dynamic_tool_name(tool: &DynamicToolSpec) -> &str {
    match tool {
        DynamicToolSpec::Function(function) => &function.name,
        DynamicToolSpec::Namespace(namespace) => &namespace.name,
    }
}

fn logged_mcp_tool_arguments(
    selectors: &[McpToolSelector],
    server: &str,
    tool: &str,
    arguments: Option<&Value>,
) -> Value {
    if !mcp_tool_is_sensitive(selectors, server, tool) {
        return arguments.cloned().unwrap_or(Value::Null);
    }
    json!({"redacted": true})
}

fn logged_mcp_tool_begin_event(
    event: &codex_protocol::protocol::McpToolCallBeginEvent,
    selectors: &[McpToolSelector],
) -> Value {
    json!({
        "event": "tool_begin",
        "tool": event.invocation.tool,
        "namespace": format!("mcp__{}", event.invocation.server),
        "call_id": event.call_id,
        "arguments": logged_mcp_tool_arguments(
            selectors,
            &event.invocation.server,
            &event.invocation.tool,
            event.invocation.arguments.as_ref(),
        ),
    })
}

fn logged_mcp_tool_end_event(event: &codex_protocol::protocol::McpToolCallEndEvent) -> Value {
    json!({
        "event": "tool_end",
        "tool": event.invocation.tool,
        "namespace": format!("mcp__{}", event.invocation.server),
        "call_id": event.call_id,
        "success": event.is_success(),
    })
}

fn handle_metalanguage_dynamic_tool(
    request: &DynamicToolCallRequest,
    spawn_child_handler_command: Option<&[String]>,
) -> DynamicToolResponse {
    if request.namespace.is_some() {
        return dynamic_tool_json_response(
            false,
            json!({
                "success": false,
                "child_spawned": false,
                "parent_continues": true,
                "retryable": true,
                "error_code": "unsupported_dynamic_tool_namespace",
                "error": "unsupported dynamic tool namespace",
                "namespace": request.namespace,
            }),
        );
    }

    match request.tool.as_str() {
        "spawn_child" => handle_spawn_child_tool(request, spawn_child_handler_command),
        other => dynamic_tool_json_response(
            false,
            json!({"error": "unsupported dynamic tool", "tool": other}),
        ),
    }
}

fn handle_dynamic_tool_for_phase(
    request: &DynamicToolCallRequest,
    spawn_child_handler_command: Option<&[String]>,
    resolution_phase: bool,
) -> DynamicToolResponse {
    if resolution_phase {
        return dynamic_tool_json_response(
            false,
            spawn_child_failure(
                "dynamic_tools_disabled_during_conflict_resolution",
                "dynamic tools are disabled during conflict resolution",
                false,
            ),
        );
    }
    handle_metalanguage_dynamic_tool(request, spawn_child_handler_command)
}

fn handle_spawn_child_tool(
    request: &DynamicToolCallRequest,
    spawn_child_handler_command: Option<&[String]>,
) -> DynamicToolResponse {
    let Some(command) = spawn_child_handler_command else {
        return dynamic_tool_json_response(
            false,
            spawn_child_failure("spawn_child_handler_unavailable", "spawn_child handler command is not configured", true),
        );
    };
    if command.is_empty() {
        return dynamic_tool_json_response(
            false,
            spawn_child_failure("spawn_child_handler_unavailable", "spawn_child handler command is empty", true),
        );
    }
    let handler_payload = json!({
        "tool": request.tool,
        "namespace": request.namespace,
        "call_id": request.call_id,
        "arguments": request.arguments,
    });

    let output = match run_spawn_child_handler(command, &handler_payload) {
        Ok(value) => value,
        Err(message) => {
            return dynamic_tool_json_response(
                false,
                spawn_child_failure("spawn_child_handler_failed", &message, true),
            )
        }
    };
    let success = output
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    dynamic_tool_json_response(success, output)
}

fn spawn_child_failure(error_code: &str, error: &str, retryable: bool) -> Value {
    json!({
        "success": false,
        "child_spawned": false,
        "parent_continues": true,
        "retryable": retryable,
        "error_code": error_code,
        "error": error,
    })
}

fn mcp_tool_is_sensitive(selectors: &[McpToolSelector], server: &str, tool: &str) -> bool {
    selectors
        .iter()
        .any(|item| item.server == server && item.tool == tool)
}

fn validate_mcp_tool_selectors(
    selectors: Vec<McpToolSelector>,
    servers: &HashMap<String, impl Sized>,
    field: &str,
) -> anyhow::Result<Vec<McpToolSelector>> {
    let mut seen = std::collections::HashSet::new();
    for selector in &selectors {
        if selector.server.trim().is_empty() || selector.tool.trim().is_empty() {
            bail!("{field} entries require non-empty server and tool");
        }
        if !servers.contains_key(&selector.server) {
            bail!("{field} references unconfigured MCP server");
        }
        if !seen.insert((selector.server.clone(), selector.tool.clone())) {
            bail!("{field} contains a duplicate server/tool pair");
        }
    }
    Ok(selectors)
}

fn run_spawn_child_handler(command: &[String], payload: &Value) -> Result<Value, String> {
    let mut child = Command::new(&command[0])
        .args(&command[1..])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|err| format!("failed to start spawn_child handler: {err}"))?;

    {
        let Some(stdin) = child.stdin.as_mut() else {
            return Err("spawn_child handler stdin is unavailable".to_string());
        };
        serde_json::to_writer(&mut *stdin, payload)
            .map_err(|err| format!("failed to serialize spawn_child payload: {err}"))?;
        stdin
            .write_all(b"\n")
            .map_err(|err| format!("failed to write spawn_child payload: {err}"))?;
    }

    let output = child
        .wait_with_output()
        .map_err(|err| format!("failed to wait for spawn_child handler: {err}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if !output.status.success() {
        return Err(format!(
            "spawn_child handler exited with status {}: {}",
            output.status, stderr
        ));
    }
    if stdout.is_empty() {
        return Err("spawn_child handler returned empty stdout".to_string());
    }
    serde_json::from_str(&stdout)
        .map_err(|err| format!("failed to parse spawn_child handler response: {err}: {stdout}"))
}

fn dynamic_tool_json_response(success: bool, payload: Value) -> DynamicToolResponse {
    DynamicToolResponse {
        content_items: vec![DynamicToolCallOutputContentItem::InputText {
            text: payload.to_string(),
        }],
        success,
    }
}

fn mapped_item_notification(
    msg: &EventMsg,
    thread_id: &str,
    current_turn_id: Option<&str>,
    sensitive_tools: &[McpToolSelector],
) -> anyhow::Result<Option<Value>> {
    let Some(turn_id) = current_turn_id else {
        return Ok(None);
    };
    if item_event_contains_sensitive_mcp_call(msg, sensitive_tools) {
        return Ok(None);
    }
    let notification = item_event_to_server_notification(msg.clone(), thread_id, turn_id);
    serde_json::to_value(notification)
        .map(Some)
        .context("serialize mapped Codex notification")
}

fn item_event_contains_sensitive_mcp_call(
    msg: &EventMsg,
    sensitive_tools: &[McpToolSelector],
) -> bool {
    let item = match msg {
        EventMsg::ItemStarted(event) => &event.item,
        EventMsg::ItemCompleted(event) => &event.item,
        _ => return false,
    };
    matches!(
        item,
        TurnItem::McpToolCall(call)
            if mcp_tool_is_sensitive(sensitive_tools, &call.server, &call.tool)
    )
}

fn agent_message_text(content: &[AgentMessageContent]) -> String {
    content
        .iter()
        .map(|entry| match entry {
            AgentMessageContent::Text { text } => text.as_str(),
        })
        .collect::<String>()
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_protocol::items::DynamicToolCallItem;
    use codex_protocol::items::DynamicToolCallStatus;
    use codex_protocol::items::McpToolCallError;
    use codex_protocol::items::McpToolCallItem;
    use codex_protocol::items::McpToolCallStatus;
    use codex_protocol::mcp::CallToolResult;
    use codex_protocol::protocol::ItemCompletedEvent;
    use codex_protocol::protocol::ItemStartedEvent;
    use codex_protocol::protocol::McpInvocation;
    use codex_protocol::protocol::McpToolCallBeginEvent;
    use codex_protocol::protocol::McpToolCallEndEvent;
    use codex_protocol::ThreadId;

    const ARGUMENT_SENTINEL: &str = "sensitive-argument-sentinel";
    const RESULT_SENTINEL: &str = "sensitive-result-sentinel";
    const ERROR_SENTINEL: &str = "sensitive-error-sentinel";

    fn sensitive_mcp_tools() -> Vec<McpToolSelector> {
        vec![McpToolSelector {
            server: "benchmark".to_string(),
            tool: "submit_solution".to_string(),
        }]
    }

    fn sensitive_mcp_item() -> McpToolCallItem {
        McpToolCallItem {
            id: "mcp-call".to_string(),
            server: "benchmark".to_string(),
            tool: "submit_solution".to_string(),
            arguments: json!({"secret": ARGUMENT_SENTINEL}),
            connector_id: None,
            mcp_app_resource_uri: None,
            link_id: None,
            app_name: None,
            action_name: None,
            plugin_id: None,
            read_only_hint: None,
            status: McpToolCallStatus::Completed,
            result: Some(CallToolResult {
                content: vec![json!({"type": "text", "text": RESULT_SENTINEL})],
                structured_content: Some(json!({"secret": RESULT_SENTINEL})),
                is_error: Some(false),
                meta: None,
            }),
            error: Some(McpToolCallError {
                message: ERROR_SENTINEL.to_string(),
            }),
            duration: Some(Duration::from_millis(1)),
        }
    }

    fn item_started(item: TurnItem) -> EventMsg {
        EventMsg::ItemStarted(ItemStartedEvent {
            thread_id: ThreadId::new(),
            turn_id: "turn".to_string(),
            item,
            started_at_ms: 0,
        })
    }

    fn item_completed(item: TurnItem) -> EventMsg {
        EventMsg::ItemCompleted(ItemCompletedEvent {
            thread_id: ThreadId::new(),
            turn_id: "turn".to_string(),
            item,
            started_at_ms: Some(0),
            completed_at_ms: 1,
        })
    }

    #[test]
    fn native_tools_never_include_submit_solution() {
        let names = metalanguage_dynamic_tools()
            .into_iter()
            .map(|tool| dynamic_tool_name(&tool).to_string())
            .collect::<Vec<_>>();
        assert_eq!(names, vec!["spawn_child"]);
        assert!(!names.contains(&"submit_solution".to_string()));
    }

    #[test]
    fn spawn_child_schema_requires_prompt_and_workspace_dir() {
        let mut tools = metalanguage_dynamic_tools();
        let DynamicToolSpec::Function(function) = tools.remove(0) else {
            panic!("spawn_child must be a function tool");
        };
        assert_eq!(
            function.input_schema["required"],
            json!(["prompt", "workspace_dir"])
        );
        assert!(function.description.contains("parent rollout continues"));
    }

    #[test]
    fn conflict_resolution_fails_spawn_child_closed() {
        let request = DynamicToolCallRequest {
            call_id: "spawn-attempt".to_string(),
            turn_id: "resolution-turn".to_string(),
            started_at_ms: 0,
            namespace: None,
            tool: "spawn_child".to_string(),
            arguments: json!({"prompt": "blocked", "workspace_dir": "child"}),
        };
        let unavailable_handler = vec!["/handler/must/not/run".to_string()];
        let response = handle_dynamic_tool_for_phase(
            &request,
            Some(&unavailable_handler),
            /*resolution_phase*/ true,
        );
        assert!(!response.success);
        let DynamicToolCallOutputContentItem::InputText { text } = &response.content_items[0]
        else {
            panic!("conflict-resolution tool failure must be text JSON");
        };
        let payload: Value = serde_json::from_str(text).expect("parse tool failure payload");
        assert_eq!(
            payload["error_code"],
            "dynamic_tools_disabled_during_conflict_resolution"
        );
        assert_eq!(payload["child_spawned"], false);
        assert_eq!(payload["retryable"], false);
    }

    #[test]
    fn sensitive_mcp_arguments_are_redacted_from_runner_events() {
        let logged = logged_mcp_tool_arguments(
            &sensitive_mcp_tools(),
            "benchmark",
            "submit_solution",
            Some(&json!({"uuid": "problem", "answer": "private-answer"})),
        );
        assert_eq!(logged, json!({"redacted": true}));
        assert!(!logged.to_string().contains("private-answer"));
    }

    #[test]
    fn sensitive_mcp_payloads_never_reach_runner_event_jsonl() {
        let sensitive_tools = sensitive_mcp_tools();
        let invocation = McpInvocation {
            server: "benchmark".to_string(),
            tool: "submit_solution".to_string(),
            arguments: Some(json!({"secret": ARGUMENT_SENTINEL})),
        };
        let begin = McpToolCallBeginEvent {
            call_id: "mcp-call".to_string(),
            invocation: invocation.clone(),
            connector_id: None,
            mcp_app_resource_uri: None,
            link_id: None,
            app_name: None,
            action_name: None,
            plugin_id: None,
            read_only_hint: None,
        };
        let completed_with_result = McpToolCallEndEvent {
            call_id: "mcp-call".to_string(),
            invocation: invocation.clone(),
            connector_id: None,
            mcp_app_resource_uri: None,
            link_id: None,
            app_name: None,
            action_name: None,
            plugin_id: None,
            read_only_hint: None,
            duration: Duration::from_millis(1),
            result: Ok(CallToolResult {
                content: vec![json!({"type": "text", "text": RESULT_SENTINEL})],
                structured_content: None,
                is_error: Some(false),
                meta: None,
            }),
        };
        let completed_with_error = McpToolCallEndEvent {
            result: Err(ERROR_SENTINEL.to_string()),
            ..completed_with_result.clone()
        };
        let started = item_started(TurnItem::McpToolCall(sensitive_mcp_item()));
        let completed = item_completed(TurnItem::McpToolCall(sensitive_mcp_item()));

        let mut emitted = vec![
            logged_mcp_tool_begin_event(&begin, &sensitive_tools),
            logged_mcp_tool_end_event(&completed_with_result),
            logged_mcp_tool_end_event(&completed_with_error),
        ];
        for item_event in [&started, &completed] {
            let notification = mapped_item_notification(
                item_event,
                "thread",
                Some("turn"),
                &sensitive_tools,
            )
            .expect("map item event");
            assert!(notification.is_none());
            if let Some(notification) = notification {
                emitted.push(json!({
                    "event": "codex_item",
                    "notification": notification,
                }));
            }
        }

        let persisted_jsonl = emitted
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n");
        for sentinel in [ARGUMENT_SENTINEL, RESULT_SENTINEL, ERROR_SENTINEL] {
            assert!(!persisted_jsonl.contains(sentinel));
        }
    }

    #[test]
    fn non_sensitive_mcp_and_spawn_child_items_remain_mapped() {
        let non_sensitive = item_completed(TurnItem::McpToolCall(sensitive_mcp_item()));
        let non_sensitive_notification = mapped_item_notification(
            &non_sensitive,
            "thread",
            Some("turn"),
            &[],
        )
        .expect("map non-sensitive MCP item")
        .expect("retain non-sensitive MCP item");
        let non_sensitive_json = non_sensitive_notification.to_string();
        for sentinel in [ARGUMENT_SENTINEL, RESULT_SENTINEL, ERROR_SENTINEL] {
            assert!(non_sensitive_json.contains(sentinel));
        }

        let spawn_child = item_completed(TurnItem::DynamicToolCall(DynamicToolCallItem {
            id: "dynamic-call".to_string(),
            namespace: None,
            tool: "spawn_child".to_string(),
            arguments: json!({"prompt": ARGUMENT_SENTINEL}),
            status: DynamicToolCallStatus::Completed,
            content_items: Some(vec![DynamicToolCallOutputContentItem::InputText {
                text: RESULT_SENTINEL.to_string(),
            }]),
            success: Some(false),
            error: Some(ERROR_SENTINEL.to_string()),
            duration: Some(Duration::from_millis(1)),
        }));
        let spawn_child_notification = mapped_item_notification(
            &spawn_child,
            "thread",
            Some("turn"),
            &sensitive_mcp_tools(),
        )
        .expect("map spawn_child item")
        .expect("retain spawn_child item");
        let spawn_child_json = spawn_child_notification.to_string();
        for sentinel in [ARGUMENT_SENTINEL, RESULT_SENTINEL] {
            assert!(spawn_child_json.contains(sentinel));
        }
    }

    #[test]
    fn mcp_tool_selectors_are_strict_and_server_scoped() {
        let servers = HashMap::from([("benchmark".to_string(), json!({}))]);
        let valid = validate_mcp_tool_selectors(
            vec![McpToolSelector {
                server: "benchmark".to_string(),
                tool: "score".to_string(),
            }],
            &servers,
            "selectors",
        )
        .expect("valid selector");
        assert!(mcp_tool_is_sensitive(&valid, "benchmark", "score"));
        assert!(
            validate_mcp_tool_selectors(
                vec![McpToolSelector {
                    server: "missing".to_string(),
                    tool: "score".to_string(),
                }],
                &servers,
                "selectors",
            )
            .is_err()
        );
    }
}

fn parse_sandbox_mode(value: Option<&str>) -> anyhow::Result<SandboxMode> {
    match value.unwrap_or("workspace-write") {
        "read-only" => Ok(SandboxMode::ReadOnly),
        "workspace-write" => Ok(SandboxMode::WorkspaceWrite),
        "danger-full-access" => Ok(SandboxMode::DangerFullAccess),
        other => bail!("unsupported sandbox_mode: {other}"),
    }
}

fn normalize_paths(paths: Vec<PathBuf>) -> anyhow::Result<Vec<PathBuf>> {
    paths
        .into_iter()
        .map(|path| normalize_existing_path(&path))
        .collect()
}

fn absolute_paths(paths: &[PathBuf]) -> anyhow::Result<Vec<AbsolutePathBuf>> {
    paths
        .iter()
        .map(|path| {
            AbsolutePathBuf::from_absolute_path(path)
                .with_context(|| format!("convert {} to absolute path", path.display()))
        })
        .collect()
}

fn normalize_existing_path(path: &Path) -> anyhow::Result<PathBuf> {
    if path.exists() {
        return path
            .canonicalize()
            .with_context(|| format!("canonicalize {}", path.display()));
    }
    if path.is_absolute() {
        Ok(path.to_path_buf())
    } else {
        Ok(std::env::current_dir()
            .context("resolve current directory")?
            .join(path))
    }
}

fn path_to_string(path: &PathBuf) -> String {
    path.to_string_lossy().to_string()
}

fn patch_status(status: &PatchApplyStatus) -> &'static str {
    match status {
        PatchApplyStatus::Completed => "completed",
        PatchApplyStatus::Failed => "failed",
        PatchApplyStatus::Declined => "declined",
    }
}

fn exec_output_stream_name(stream: &ExecOutputStream) -> &'static str {
    match stream {
        ExecOutputStream::Stdout => "stdout",
        ExecOutputStream::Stderr => "stderr",
    }
}

fn emit(value: Value) -> anyhow::Result<()> {
    let mut stdout = std::io::stdout().lock();
    serde_json::to_writer(&mut stdout, &value).context("serialize runner event")?;
    stdout.write_all(b"\n").context("write event newline")?;
    stdout.flush().context("flush event")?;
    Ok(())
}
