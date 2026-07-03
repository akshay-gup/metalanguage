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
use codex_core::config::ConfigBuilder;
use codex_core::config::ConfigOverrides;
use codex_core_api::AbsolutePathBuf;
use codex_core_api::Arg0DispatchPaths;
use codex_core_api::AskForApproval;
use codex_core_api::AuthManager;
use codex_core_api::EnvironmentManager;
use codex_core_api::EventMsg;
use codex_core_api::ExecServerRuntimePaths;
use codex_core_api::Feature;
use codex_core_api::NewThread;
use codex_core_api::Op;
use codex_core_api::SessionSource;
use codex_core_api::ThreadManager;
use codex_core_api::UserInput;
use codex_core_api::arg0_dispatch_or_else;
use codex_core_api::empty_extension_registry;
use codex_core_api::init_state_db;
use codex_core_api::item_event_to_server_notification;
use codex_core_api::resolve_installation_id;
use codex_core_api::set_default_originator;
use codex_core_api::thread_store_from_config;
use codex_protocol::config_types::SandboxMode;
use codex_protocol::dynamic_tools::DynamicToolCallOutputContentItem;
use codex_protocol::dynamic_tools::DynamicToolCallRequest;
use codex_protocol::dynamic_tools::DynamicToolResponse;
use codex_protocol::dynamic_tools::DynamicToolSpec;
use codex_protocol::items::AgentMessageContent;
use codex_protocol::items::TurnItem;
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
    rollout_token_budget_tokens: Option<i64>,
    instance_uuid: Option<String>,
    spawn_child_handler_command: Option<Vec<String>>,
}

#[derive(Debug)]
struct BudgetState {
    rollout_token_budget_tokens: Option<i64>,
    tokens_spent: i64,
    reserved_child_tokens: i64,
    transferred_in_tokens: i64,
    transferred_out_tokens: i64,
}

impl BudgetState {
    fn effective_rollout_token_budget_tokens(&self) -> Option<i64> {
        self.rollout_token_budget_tokens
            .map(|budget| budget + self.transferred_in_tokens)
    }

    fn tokens_remaining(&self) -> Option<i64> {
        self.effective_rollout_token_budget_tokens().map(|budget| {
            (budget - self.tokens_spent - self.reserved_child_tokens - self.transferred_out_tokens)
                .max(0)
        })
    }

    fn exhausted(&self) -> bool {
        self.effective_rollout_token_budget_tokens()
            .is_some_and(|budget| {
                self.tokens_spent + self.reserved_child_tokens + self.transferred_out_tokens
                    >= budget
            })
    }

    fn snapshot(&self) -> Value {
        json!({
            "budget_configured": self.rollout_token_budget_tokens.is_some(),
            "rollout_token_budget_tokens": self.rollout_token_budget_tokens,
            "effective_rollout_token_budget_tokens": self.effective_rollout_token_budget_tokens(),
            "tokens_spent": self.tokens_spent,
            "tokens_reserved_for_children": self.reserved_child_tokens,
            "tokens_transferred_in": self.transferred_in_tokens,
            "tokens_transferred_out": self.transferred_out_tokens,
            "tokens_remaining": self.tokens_remaining(),
        })
    }

    fn apply_snapshot(&mut self, snapshot: &Value) {
        if let Some(value) = snapshot
            .get("rollout_token_budget_tokens")
            .and_then(Value::as_i64)
        {
            self.rollout_token_budget_tokens = Some(value);
        }
        if let Some(value) = snapshot.get("tokens_spent").and_then(Value::as_i64) {
            self.tokens_spent = self.tokens_spent.max(value);
        }
        if let Some(value) = snapshot
            .get("tokens_reserved_for_children")
            .and_then(Value::as_i64)
        {
            self.reserved_child_tokens = value;
        }
        if let Some(value) = snapshot
            .get("tokens_transferred_in")
            .and_then(Value::as_i64)
        {
            self.transferred_in_tokens = value;
        }
        if let Some(value) = snapshot
            .get("tokens_transferred_out")
            .and_then(Value::as_i64)
        {
            self.transferred_out_tokens = value;
        }
    }
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
    let sandbox_mode = parse_sandbox_mode(request.sandbox_mode.as_deref())?;
    let (sandbox_mode_override, permission_profile_override) = match sandbox_mode {
        SandboxMode::WorkspaceWrite => (
            None,
            Some(PermissionProfile::workspace_write_with(
                &[],
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
        tools_web_search_request: Some(true),
        ephemeral: Some(true),
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

    let mut config = ConfigBuilder::default()
        .codex_home(codex_home.clone())
        .harness_overrides(overrides)
        .build()
        .await
        .context("load Codex config")?;
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
        AuthManager::shared_from_config(&config, /*enable_codex_api_key_env*/ true).await;
    let local_runtime_paths = ExecServerRuntimePaths::from_optional_paths(
        config.codex_self_exe.clone(),
        config.codex_linux_sandbox_exe.clone(),
    )
    .context("configure Codex runtime helper paths")?;
    let thread_store = thread_store_from_config(&config, state_db.clone());
    let environment_manager = Arc::new(
        EnvironmentManager::from_codex_home(config.codex_home.clone(), Some(local_runtime_paths))
            .await
            .context("load Codex environment manager")?,
    );
    let installation_id = resolve_installation_id(&config.codex_home)
        .await
        .context("resolve Codex installation id")?;

    let thread_manager = ThreadManager::new(
        &config,
        auth_manager,
        SessionSource::Exec,
        environment_manager,
        empty_extension_registry(),
        None,
        Arc::clone(&thread_store),
        state_db,
        installation_id,
        None,
    );

    let NewThread {
        thread_id,
        thread,
        session_configured,
    } = thread_manager
        .start_thread_with_tools(config, metalanguage_dynamic_tools())
        .await
        .context("start Codex thread")?;

    emit(json!({
        "event": "thread_started",
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

    let rollout_token_budget_tokens = request.rollout_token_budget_tokens;
    let instance_uuid = request.instance_uuid.clone();
    let spawn_child_handler_command = request.spawn_child_handler_command.clone();
    let prompt = request
        .initial_user_text
        .unwrap_or_else(|| "Read README.md.".to_string());
    let turn_result = run_turn(
        &thread,
        &thread_id.to_string(),
        prompt,
        rollout_token_budget_tokens,
        instance_uuid,
        spawn_child_handler_command,
    )
    .await;
    let shutdown_result = thread.shutdown_and_wait().await;
    let _ = thread_manager.remove_thread(&thread_id).await;

    turn_result?;
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
    rollout_token_budget_tokens: Option<i64>,
    instance_uuid: Option<String>,
    spawn_child_handler_command: Option<Vec<String>>,
) -> anyhow::Result<()> {
    thread
        .submit(Op::UserInput {
            items: vec![UserInput::Text {
                text: prompt,
                text_elements: Vec::new(),
            }],
            environments: None,
            final_output_json_schema: None,
            responsesapi_client_metadata: None,
            additional_context: Default::default(),
            thread_settings: Default::default(),
        })
        .await
        .context("submit user input")?;

    let mut current_turn_id: Option<String> = None;
    let mut final_text = String::new();
    let mut budget_state = BudgetState {
        rollout_token_budget_tokens,
        tokens_spent: 0,
        reserved_child_tokens: 0,
        transferred_in_tokens: 0,
        transferred_out_tokens: 0,
    };
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
            EventMsg::TokenCount(event) => {
                let info = event.info.as_ref();
                if let Some(info) = info {
                    let total_tokens = info.total_token_usage.total_tokens.max(0);
                    if total_tokens > 0 {
                        budget_state.tokens_spent = budget_state.tokens_spent.max(total_tokens);
                    } else {
                        budget_state.tokens_spent += info.last_token_usage.total_tokens.max(0);
                    }
                }
                let _ = refresh_budget_status_from_handler(
                    &mut budget_state,
                    spawn_child_handler_command.as_deref(),
                );
                let tokens_remaining = budget_state.tokens_remaining();
                let budget_exhausted = budget_state.exhausted();
                emit(json!({
                    "event": "token_usage",
                    "turn_id": current_turn_id.as_deref(),
                    "last": info.map(|info| &info.last_token_usage),
                    "total": info.map(|info| &info.total_token_usage),
                    "model_context_window": info.and_then(|info| info.model_context_window),
                    "tokens_spent": budget_state.tokens_spent,
                    "tokens_reserved_for_children": budget_state.reserved_child_tokens,
                    "tokens_transferred_in": budget_state.transferred_in_tokens,
                    "tokens_transferred_out": budget_state.transferred_out_tokens,
                    "tokens_remaining": tokens_remaining,
                    "rollout_token_budget_tokens": budget_state.rollout_token_budget_tokens,
                    "effective_rollout_token_budget_tokens": budget_state.effective_rollout_token_budget_tokens(),
                    "budget_exhausted": budget_exhausted,
                }))?;
                if budget_exhausted {
                    let budget = budget_state
                        .effective_rollout_token_budget_tokens()
                        .unwrap_or_default();
                    emit(json!({
                        "event": "error",
                        "error_code": "token_budget_exhausted",
                        "error_message": format!(
                            "Token budget exhausted: {}/{}.",
                            budget_state.tokens_spent
                                + budget_state.reserved_child_tokens
                                + budget_state.transferred_out_tokens,
                            budget
                        ),
                        "tokens_spent": budget_state.tokens_spent,
                        "tokens_reserved_for_children": budget_state.reserved_child_tokens,
                        "tokens_transferred_in": budget_state.transferred_in_tokens,
                        "tokens_transferred_out": budget_state.transferred_out_tokens,
                        "rollout_token_budget_tokens": budget_state.rollout_token_budget_tokens,
                        "effective_rollout_token_budget_tokens": budget,
                    }))?;
                    let _ = thread.submit(Op::Interrupt).await;
                    bail!(
                        "token budget exhausted: {}/{}",
                        budget_state.tokens_spent
                            + budget_state.reserved_child_tokens
                            + budget_state.transferred_out_tokens,
                        budget
                    );
                }
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
                emit(json!({
                    "event": "tool_begin",
                    "tool": "exec_command",
                    "call_id": event.call_id,
                    "turn_id": event.turn_id,
                    "command": event.command,
                    "cwd": event.cwd.to_string_lossy(),
                }))?;
            }
            EventMsg::ExecCommandOutputDelta(event) => {
                let text = String::from_utf8_lossy(&event.chunk).to_string();
                emit(json!({
                    "event": "tool_output_delta",
                    "tool": "exec_command",
                    "call_id": event.call_id,
                    "stream": exec_output_stream_name(&event.stream),
                    "text": text,
                }))?;
            }
            EventMsg::TerminalInteraction(event) => {
                emit(json!({
                    "event": "terminal_interaction",
                    "tool": "exec_command",
                    "call_id": event.call_id,
                    "process_id": event.process_id,
                    "stdin": event.stdin,
                }))?;
            }
            EventMsg::ExecCommandEnd(event) => {
                emit(json!({
                    "event": "tool_end",
                    "tool": "exec_command",
                    "call_id": event.call_id,
                    "turn_id": event.turn_id,
                    "command": event.command,
                    "cwd": event.cwd.to_string_lossy(),
                    "exit_code": event.exit_code,
                    "status": format!("{:?}", event.status),
                    "duration_ms": event.duration.as_millis(),
                }))?;
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
                } else if let Some(notification) = mapped_item_notification(
                    &EventMsg::ItemCompleted(event.clone()),
                    thread_id,
                    current_turn_id.as_deref(),
                )? {
                    emit(json!({
                        "event": "codex_item",
                        "notification": notification,
                    }))?;
                }
            }
            EventMsg::TurnComplete(event) => {
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
                emit(json!({
                    "event": "error",
                    "error_message": event.message,
                }))?;
                bail!("{}", event.message);
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
                emit(json!({
                    "event": "tool_begin",
                    "tool": request.tool,
                    "namespace": request.namespace,
                    "call_id": request.call_id,
                    "turn_id": request.turn_id,
                    "arguments": request.arguments,
                }))?;
                let response = handle_metalanguage_dynamic_tool(
                    request,
                    &mut budget_state,
                    instance_uuid.as_deref(),
                    spawn_child_handler_command.as_deref(),
                );
                emit(json!({
                    "event": "tool_end",
                    "tool": request.tool,
                    "namespace": request.namespace,
                    "call_id": request.call_id,
                    "turn_id": request.turn_id,
                    "success": response.success,
                    "tokens_reserved_for_children": budget_state.reserved_child_tokens,
                    "tokens_transferred_in": budget_state.transferred_in_tokens,
                    "tokens_transferred_out": budget_state.transferred_out_tokens,
                    "effective_rollout_token_budget_tokens": budget_state.effective_rollout_token_budget_tokens(),
                    "tokens_remaining": budget_state.tokens_remaining(),
                }))?;
                thread
                    .submit(Op::DynamicToolResponse {
                        id: request.call_id.clone(),
                        response,
                    })
                    .await
                    .context("submit dynamic tool response")?;
                if budget_state.exhausted() {
                    let budget = budget_state
                        .effective_rollout_token_budget_tokens()
                        .unwrap_or_default();
                    emit(json!({
                        "event": "error",
                        "error_code": "token_budget_exhausted",
                        "error_message": format!(
                            "Token budget exhausted: {}/{}.",
                            budget_state.tokens_spent
                                + budget_state.reserved_child_tokens
                                + budget_state.transferred_out_tokens,
                            budget
                        ),
                        "tokens_spent": budget_state.tokens_spent,
                        "tokens_reserved_for_children": budget_state.reserved_child_tokens,
                        "tokens_transferred_in": budget_state.transferred_in_tokens,
                        "tokens_transferred_out": budget_state.transferred_out_tokens,
                        "rollout_token_budget_tokens": budget_state.rollout_token_budget_tokens,
                        "effective_rollout_token_budget_tokens": budget,
                    }))?;
                    let _ = thread.submit(Op::Interrupt).await;
                    bail!(
                        "token budget exhausted: {}/{}",
                        budget_state.tokens_spent
                            + budget_state.reserved_child_tokens
                            + budget_state.transferred_out_tokens,
                        budget
                    );
                }
            }
            _ => {}
        }
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
        DynamicToolSpec {
            namespace: None,
            name: "budget_status".to_string(),
            description: concat!(
                "Return this rollout's token budget, spent tokens, reserved child ",
                "budget, and remaining budget."
            )
            .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": false,
            }),
            defer_loading: false,
        },
        DynamicToolSpec {
            namespace: None,
            name: "submit_solution".to_string(),
            description: concat!(
                "Submit a problem uuid from the shared workspace problem pool and its ",
                "answer for immediate scoring. The response returns correct/incorrect, ",
                "reward, credited tokens, and updated budget status."
            )
            .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "Problem uuid copied from shared_workspace/problem_pool.json or shared_workspace/problem_pool.md."
                    },
                    "answer": {
                        "type": "string",
                        "description": "Answer to score against the selected problem uuid."
                    }
                },
                "required": ["uuid", "answer"],
                "additionalProperties": false,
            }),
            defer_loading: false,
        },
        DynamicToolSpec {
            namespace: None,
            name: "spawn_child".to_string(),
            description: concat!(
                "Claim a next-iteration rollout slot by passing the child's inherited ",
                "prompt, optionally copying a workspace-local directory into the child ",
                "workspace, and reserving exactly initial_budget_tokens from this rollout."
            )
            .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Required non-empty initial prompt for the child rollout. Include the durable core instructions needed to solve, submit_solution, use archive/shared_workspace, and spawn again."
                    },
                    "workspace_dir": {
                        "type": "string",
                        "description": "Optional workspace-local directory whose contents should be copied into the child rollout root. Leave blank or omit for no inherited workspace files."
                    },
                    "initial_budget_tokens": {
                        "type": "integer",
                        "description": "Positive token budget to reserve from this rollout and assign exactly to the claimed slot."
                    }
                },
                "required": ["prompt", "initial_budget_tokens"],
                "additionalProperties": false,
            }),
            defer_loading: false,
        },
        DynamicToolSpec {
            namespace: None,
            name: "transfer_tokens".to_string(),
            description: concat!(
                "Transfer part of this rollout's remaining token budget to a live ",
                "peer rollout in the same task. The target receives exactly amount_tokens."
            )
            .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "target_instance_uuid": {
                        "type": "string",
                        "description": "Instance UUID of a live peer rollout listed in runtime.md."
                    },
                    "amount_tokens": {
                        "type": "integer",
                        "description": "Positive token budget amount to transfer."
                    }
                },
                "required": ["target_instance_uuid", "amount_tokens"],
                "additionalProperties": false,
            }),
            defer_loading: false,
        },
    ]
}

fn handle_metalanguage_dynamic_tool(
    request: &DynamicToolCallRequest,
    budget_state: &mut BudgetState,
    instance_uuid: Option<&str>,
    spawn_child_handler_command: Option<&[String]>,
) -> DynamicToolResponse {
    if request.namespace.is_some() {
        return dynamic_tool_json_response(
            false,
            json!({"error": "unsupported dynamic tool namespace", "namespace": request.namespace}),
        );
    }

    match request.tool.as_str() {
        "budget_status" => {
            handle_budget_status_tool(request, budget_state, spawn_child_handler_command)
        }
        "submit_solution" => {
            handle_submit_solution_tool(request, budget_state, spawn_child_handler_command)
        }
        "spawn_child" => handle_spawn_child_tool(
            request,
            budget_state,
            instance_uuid,
            spawn_child_handler_command,
        ),
        "transfer_tokens" => handle_transfer_tokens_tool(
            request,
            budget_state,
            instance_uuid,
            spawn_child_handler_command,
        ),
        other => dynamic_tool_json_response(
            false,
            json!({"error": "unsupported dynamic tool", "tool": other}),
        ),
    }
}

fn handle_submit_solution_tool(
    request: &DynamicToolCallRequest,
    budget_state: &mut BudgetState,
    spawn_child_handler_command: Option<&[String]>,
) -> DynamicToolResponse {
    let Some(command) = spawn_child_handler_command else {
        return dynamic_tool_json_response(
            false,
            json!({"error": "submit_solution handler command is not configured"}),
        );
    };
    if command.is_empty() {
        return dynamic_tool_json_response(
            false,
            json!({"error": "submit_solution handler command is empty"}),
        );
    }
    if let Err(message) = parse_submit_solution_args(&request.arguments) {
        return dynamic_tool_json_response(false, json!({"error": message}));
    }

    let handler_payload = json!({
        "tool": request.tool,
        "namespace": request.namespace,
        "call_id": request.call_id,
        "arguments": request.arguments,
    });
    let output = match run_spawn_child_handler(command, &handler_payload) {
        Ok(value) => value,
        Err(message) => return dynamic_tool_json_response(false, json!({"error": message})),
    };
    apply_budget_status_from_tool_output(budget_state, &output);
    let success = output
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    dynamic_tool_json_response(success, output)
}

fn handle_budget_status_tool(
    request: &DynamicToolCallRequest,
    budget_state: &mut BudgetState,
    spawn_child_handler_command: Option<&[String]>,
) -> DynamicToolResponse {
    let Some(command) = spawn_child_handler_command else {
        return dynamic_tool_json_response(true, budget_state.snapshot());
    };
    if command.is_empty() {
        return dynamic_tool_json_response(
            false,
            json!({"error": "budget_status handler command is empty"}),
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
        Err(message) => return dynamic_tool_json_response(false, json!({"error": message})),
    };
    apply_budget_status_from_tool_output(budget_state, &output);
    let success = output
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    if success {
        dynamic_tool_json_response(true, budget_state.snapshot())
    } else {
        dynamic_tool_json_response(false, output)
    }
}

fn handle_transfer_tokens_tool(
    request: &DynamicToolCallRequest,
    budget_state: &mut BudgetState,
    instance_uuid: Option<&str>,
    spawn_child_handler_command: Option<&[String]>,
) -> DynamicToolResponse {
    let Some(command) = spawn_child_handler_command else {
        return dynamic_tool_json_response(
            false,
            json!({"error": "transfer_tokens handler command is not configured"}),
        );
    };
    if command.is_empty() {
        return dynamic_tool_json_response(
            false,
            json!({"error": "transfer_tokens handler command is empty"}),
        );
    }
    let (target_instance_uuid, amount_tokens) = match parse_transfer_tokens_args(&request.arguments)
    {
        Ok(parsed) => parsed,
        Err(message) => return dynamic_tool_json_response(false, json!({"error": message})),
    };

    let handler_payload = json!({
        "tool": request.tool,
        "namespace": request.namespace,
        "call_id": request.call_id,
        "arguments": request.arguments,
        "source_budget": {
            "instance_uuid": instance_uuid,
            "rollout_token_budget_tokens": budget_state.rollout_token_budget_tokens,
            "effective_rollout_token_budget_tokens": budget_state.effective_rollout_token_budget_tokens(),
            "tokens_spent": budget_state.tokens_spent,
            "tokens_reserved_for_children": budget_state.reserved_child_tokens,
            "tokens_transferred_in": budget_state.transferred_in_tokens,
            "tokens_transferred_out": budget_state.transferred_out_tokens,
            "requested_transfer_tokens": amount_tokens,
            "tokens_remaining_after_transfer": budget_state.tokens_remaining(),
        },
        "target_instance_uuid": target_instance_uuid,
    });

    let output = match run_spawn_child_handler(command, &handler_payload) {
        Ok(value) => value,
        Err(message) => return dynamic_tool_json_response(false, json!({"error": message})),
    };
    apply_budget_status_from_tool_output(budget_state, &output);
    let success = output
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    dynamic_tool_json_response(success, output)
}

fn handle_spawn_child_tool(
    request: &DynamicToolCallRequest,
    budget_state: &mut BudgetState,
    instance_uuid: Option<&str>,
    spawn_child_handler_command: Option<&[String]>,
) -> DynamicToolResponse {
    let Some(command) = spawn_child_handler_command else {
        return dynamic_tool_json_response(
            false,
            json!({"error": "spawn_child handler command is not configured"}),
        );
    };
    if command.is_empty() {
        return dynamic_tool_json_response(
            false,
            json!({"error": "spawn_child handler command is empty"}),
        );
    }
    let (_prompt, child_budget) = match parse_spawn_child_args(&request.arguments) {
        Ok(parsed) => parsed,
        Err(message) => return dynamic_tool_json_response(false, json!({"error": message})),
    };

    let handler_payload = json!({
        "tool": request.tool,
        "namespace": request.namespace,
        "call_id": request.call_id,
        "arguments": request.arguments,
        "parent_budget": {
            "instance_uuid": instance_uuid,
            "rollout_token_budget_tokens": budget_state.rollout_token_budget_tokens,
            "effective_rollout_token_budget_tokens": budget_state.effective_rollout_token_budget_tokens(),
            "tokens_spent": budget_state.tokens_spent,
            "tokens_reserved_for_children": budget_state.reserved_child_tokens,
            "requested_child_budget_tokens": child_budget,
            "tokens_remaining_after_reservation": budget_state.tokens_remaining(),
        },
    });

    let output = match run_spawn_child_handler(command, &handler_payload) {
        Ok(value) => value,
        Err(message) => return dynamic_tool_json_response(false, json!({"error": message})),
    };
    apply_budget_status_from_tool_output(budget_state, &output);
    let success = output
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    dynamic_tool_json_response(success, output)
}

fn apply_budget_status_from_tool_output(budget_state: &mut BudgetState, output: &Value) {
    if let Some(status) = output.get("budget_status_after") {
        budget_state.apply_snapshot(status);
        return;
    }
    if let Some(status) = output.get("budget_status") {
        budget_state.apply_snapshot(status);
        return;
    }
    budget_state.apply_snapshot(output);
}

fn refresh_budget_status_from_handler(
    budget_state: &mut BudgetState,
    spawn_child_handler_command: Option<&[String]>,
) -> Result<(), String> {
    let Some(command) = spawn_child_handler_command else {
        return Ok(());
    };
    if command.is_empty() {
        return Ok(());
    }
    let output = run_spawn_child_handler(
        command,
        &json!({
            "tool": "budget_status",
            "arguments": {},
        }),
    )?;
    apply_budget_status_from_tool_output(budget_state, &output);
    Ok(())
}

fn parse_submit_solution_args(arguments: &Value) -> Result<(), String> {
    let Some(args) = arguments.as_object() else {
        return Err("submit_solution arguments must be an object".to_string());
    };
    let answer = args
        .get("answer")
        .and_then(Value::as_str)
        .ok_or_else(|| "submit_solution requires string answer".to_string())?;
    if answer.trim().is_empty() {
        return Err("answer must be non-empty".to_string());
    }
    let uuid = args
        .get("uuid")
        .and_then(Value::as_str)
        .ok_or_else(|| "submit_solution requires string uuid".to_string())?;
    if uuid.trim().is_empty() {
        return Err("uuid must be non-empty".to_string());
    }
    Ok(())
}

fn parse_spawn_child_args(arguments: &Value) -> Result<(String, i64), String> {
    let Some(args) = arguments.as_object() else {
        return Err("spawn_child arguments must be an object".to_string());
    };
    let prompt = args
        .get("prompt")
        .and_then(Value::as_str)
        .ok_or_else(|| "spawn_child requires string prompt".to_string())?
        .to_string();
    if prompt.trim().is_empty() {
        return Err("prompt must be non-empty".to_string());
    }
    if let Some(workspace_dir) = args
        .get("workspace_dir")
        .or_else(|| args.get("workspaceDir"))
    {
        if !workspace_dir.is_null() && !workspace_dir.is_string() {
            return Err("workspace_dir must be a string when provided".to_string());
        }
    }
    let budget_value = args
        .get("initial_budget_tokens")
        .or_else(|| args.get("initialBudgetTokens"));
    let child_budget = budget_value
        .and_then(Value::as_i64)
        .ok_or_else(|| "spawn_child requires integer initial_budget_tokens".to_string())?;
    if child_budget <= 0 {
        return Err("initial_budget_tokens must be > 0".to_string());
    }
    Ok((prompt, child_budget))
}

fn parse_transfer_tokens_args(arguments: &Value) -> Result<(String, i64), String> {
    let Some(args) = arguments.as_object() else {
        return Err("transfer_tokens arguments must be an object".to_string());
    };
    let target_instance_uuid = args
        .get("target_instance_uuid")
        .or_else(|| args.get("targetInstanceUuid"))
        .and_then(Value::as_str)
        .ok_or_else(|| "transfer_tokens requires string target_instance_uuid".to_string())?
        .to_string();
    if target_instance_uuid.trim().is_empty() {
        return Err("target_instance_uuid must be non-empty".to_string());
    }
    let amount_value = args
        .get("amount_tokens")
        .or_else(|| args.get("amountTokens"));
    let amount_tokens = amount_value
        .and_then(Value::as_i64)
        .ok_or_else(|| "transfer_tokens requires integer amount_tokens".to_string())?;
    if amount_tokens <= 0 {
        return Err("amount_tokens must be > 0".to_string());
    }
    Ok((target_instance_uuid, amount_tokens))
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
) -> anyhow::Result<Option<Value>> {
    let Some(turn_id) = current_turn_id else {
        return Ok(None);
    };
    let notification = item_event_to_server_notification(msg.clone(), thread_id, turn_id);
    serde_json::to_value(notification)
        .map(Some)
        .context("serialize mapped Codex notification")
}

fn agent_message_text(content: &[AgentMessageContent]) -> String {
    content
        .iter()
        .map(|entry| match entry {
            AgentMessageContent::Text { text } => text.as_str(),
        })
        .collect::<String>()
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
