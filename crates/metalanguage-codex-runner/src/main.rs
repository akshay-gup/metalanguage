use std::io::IsTerminal;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use anyhow::anyhow;
use anyhow::bail;
use codex_core::config::ConfigBuilder;
use codex_core::config::ConfigOverrides;
use codex_core_api::Arg0DispatchPaths;
use codex_core_api::AskForApproval;
use codex_core_api::AuthManager;
use codex_core_api::EnvironmentManager;
use codex_core_api::EventMsg;
use codex_core_api::ExecServerRuntimePaths;
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
use codex_protocol::items::AgentMessageContent;
use codex_protocol::items::TurnItem;
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
    let additional_writable_roots =
        normalize_paths(request.additional_writable_roots.unwrap_or_default())?;
    let sandbox_mode = parse_sandbox_mode(request.sandbox_mode.as_deref())?;
    let base_instructions = request
        .base_instructions
        .filter(|value| !value.trim().is_empty());

    let mut overrides = ConfigOverrides {
        model: request.model.filter(|value| !value.trim().is_empty()),
        base_instructions,
        cwd: Some(cwd.clone()),
        approval_policy: Some(AskForApproval::Never),
        sandbox_mode: Some(sandbox_mode),
        ephemeral: Some(true),
        workspace_roots: Some(workspace_roots.clone()),
        additional_writable_roots,
        codex_self_exe: arg0_paths.codex_self_exe.clone(),
        codex_linux_sandbox_exe: arg0_paths.codex_linux_sandbox_exe.clone(),
        main_execve_wrapper_exe: arg0_paths.main_execve_wrapper_exe.clone(),
        ..Default::default()
    };
    if matches!(sandbox_mode, SandboxMode::DangerFullAccess) {
        overrides.workspace_roots = None;
    }

    let config = ConfigBuilder::default()
        .codex_home(codex_home.clone())
        .harness_overrides(overrides)
        .build()
        .await
        .context("load Codex config")?;

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
        .start_thread(config)
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

    let prompt = request
        .initial_user_text
        .unwrap_or_else(|| "Read README.md.".to_string());
    let turn_result = run_turn(&thread, &thread_id.to_string(), prompt).await;
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
                emit(json!({
                    "event": "token_usage",
                    "turn_id": current_turn_id.as_deref(),
                    "last": info.map(|info| &info.last_token_usage),
                    "total": info.map(|info| &info.total_token_usage),
                    "model_context_window": info.and_then(|info| info.model_context_window),
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
            EventMsg::ExecApprovalRequest(_) => bail_with_event("exec_approval_requested")?,
            EventMsg::ApplyPatchApprovalRequest(_) => bail_with_event("patch_approval_requested")?,
            EventMsg::RequestPermissions(_) => bail_with_event("permissions_requested")?,
            EventMsg::RequestUserInput(_) => bail_with_event("user_input_requested")?,
            EventMsg::DynamicToolCallRequest(_) => bail_with_event("dynamic_tool_requested")?,
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
