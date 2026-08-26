use std::collections::HashMap;
use std::collections::HashSet;
use std::io::IsTerminal;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::anyhow;
use anyhow::bail;
use codex_config::CONFIG_TOML_FILE;
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
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_protocol::protocol::ExecOutputStream;
use codex_protocol::protocol::HookEventName;
use codex_protocol::protocol::HookRunStatus;
use codex_protocol::protocol::HookTrustStatus;
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
    peer_communication_handler_command: Option<Vec<String>>,
    mcp_servers: Option<HashMap<String, Value>>,
    sensitive_mcp_tools: Option<Vec<McpToolSelector>>,
}

#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq)]
#[serde(deny_unknown_fields)]
struct McpToolSelector {
    server: String,
    tool: String,
}

fn main() -> anyhow::Result<()> {
    if std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new("--peer-post-tool-hook"))
    {
        return run_peer_post_tool_hook();
    }
    if std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new("--peer-delivery-probe"))
    {
        if std::env::var_os("METALANGUAGE_TEST_PEER_DELIVERY_PROBE").as_deref()
            != Some(std::ffi::OsStr::new("1"))
        {
            bail!("peer delivery probe is disabled outside explicit local tests");
        }
        return run_peer_delivery_probe();
    }
    arg0_dispatch_or_else(run_main)
}

fn decode_hex_json_command(value: &str) -> anyhow::Result<Vec<String>> {
    if value.is_empty() || !value.len().is_multiple_of(2) {
        bail!("peer hook command encoding is invalid");
    }
    let mut bytes = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let text = std::str::from_utf8(pair).context("decode peer hook command")?;
        bytes.push(u8::from_str_radix(text, 16).context("decode peer hook command")?);
    }
    serde_json::from_slice::<Vec<String>>(&bytes).context("parse peer hook command")
}

fn run_peer_post_tool_hook() -> anyhow::Result<()> {
    let encoded = std::env::args()
        .nth(2)
        .context("peer post-tool hook requires a handler command")?;
    let command = decode_hex_json_command(&encoded)?;
    if command.is_empty() {
        bail!("peer post-tool hook handler command is empty");
    }
    let mut raw = String::new();
    std::io::stdin()
        .read_to_string(&mut raw)
        .context("read Codex post-tool hook input")?;
    let input: Value = serde_json::from_str(&raw).context("parse Codex post-tool hook input")?;
    let boundary_id = input
        .get("tool_use_id")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .context("Codex post-tool hook omitted tool_use_id")?;
    let delivery = claim_peer_delivery(&command, boundary_id)?;
    let output = match delivery {
        Some(delivery) => json!({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": delivery.injection,
            }
        }),
        None => json!({}),
    };
    serde_json::to_writer(std::io::stdout(), &output).context("write Codex hook response")?;
    Ok(())
}

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}

fn peer_post_tool_hook_command(handler_command: &[String]) -> anyhow::Result<String> {
    if handler_command.is_empty() {
        bail!("peer delivery handler command is empty");
    }
    let encoded = serde_json::to_vec(handler_command)
        .context("serialize peer hook handler command")?
        .into_iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let executable = std::env::current_exe().context("resolve Codex runner executable")?;
    Ok(format!(
        "{} --peer-post-tool-hook {encoded}",
        shell_quote(&executable.to_string_lossy())
    ))
}

fn trust_only_peer_post_tool_hook(
    config: &mut codex_core::config::Config,
    expected_command: &str,
) -> anyhow::Result<()> {
    let listed = codex_hooks::list_hooks(codex_hooks::HooksConfig {
        feature_enabled: true,
        config_layer_stack: Some(config.config_layer_stack.clone()),
        ..codex_hooks::HooksConfig::default()
    });
    let mut matching = listed.hooks.iter().filter(|entry| {
        entry.event_name == HookEventName::PostToolUse
            && matches!(
                &entry.handler,
                codex_hooks::HookListEntryHandler::Command { command, r#async: false }
                    if command == expected_command
            )
    });
    let hook = matching
        .next()
        .context("protected peer PostToolUse hook was not discovered")?;
    if matching.next().is_some() {
        bail!("protected peer PostToolUse hook was discovered more than once");
    }
    if listed
        .hooks
        .iter()
        .any(|entry| entry.key != hook.key && entry.enabled)
    {
        bail!("peer delivery refuses to enable alongside another Codex lifecycle hook");
    }

    let mut user_config = config
        .config_layer_stack
        .get_active_user_layer()
        .map(|layer| layer.config.clone())
        .unwrap_or_else(|| TomlValue::Table(Default::default()));
    let user_table = user_config
        .as_table_mut()
        .context("Codex user configuration is not a table")?;
    let hooks_table = user_table
        .entry("hooks")
        .or_insert_with(|| TomlValue::Table(Default::default()))
        .as_table_mut()
        .context("Codex hooks configuration is not a table")?;
    let state_table = hooks_table
        .entry("state")
        .or_insert_with(|| TomlValue::Table(Default::default()))
        .as_table_mut()
        .context("Codex hook state configuration is not a table")?;
    let mut hook_state = TomlValue::Table(Default::default());
    hook_state
        .as_table_mut()
        .expect("new hook state is a table")
        .insert(
            "trusted_hash".to_string(),
            TomlValue::String(hook.current_hash.clone()),
        );
    state_table.insert(hook.key.clone(), hook_state);
    config.config_layer_stack = config
        .config_layer_stack
        .with_user_config(&config.codex_home.join(CONFIG_TOML_FILE), user_config)
        .context("trust protected peer PostToolUse hook")?;
    let verified = codex_hooks::list_hooks(codex_hooks::HooksConfig {
        feature_enabled: true,
        config_layer_stack: Some(config.config_layer_stack.clone()),
        ..codex_hooks::HooksConfig::default()
    });
    let trusted = verified.hooks.iter().filter(|entry| {
        entry.event_name == HookEventName::PostToolUse
            && entry.trust_status == HookTrustStatus::Trusted
            && matches!(
                &entry.handler,
                codex_hooks::HookListEntryHandler::Command { command, r#async: false }
                    if command == expected_command
            )
    });
    if trusted.count() != 1 {
        bail!("protected peer PostToolUse hook did not become trusted");
    }
    Ok(())
}

fn run_peer_delivery_probe() -> anyhow::Result<()> {
    let request = read_request()?;
    let command = request
        .peer_communication_handler_command
        .as_deref()
        .filter(|command| !command.is_empty())
        .context("peer delivery probe requires a handler command")?;
    let delivery = prepare_peer_delivery_with_diagnostics(command, "probe")?;
    if let Some(delivery) = delivery.as_ref() {
        acknowledge_peer_delivery_with_diagnostics(command, &delivery.delivery_id, "probe")?;
    }
    emit(json!({
        "event": "peer_delivery_probe_complete",
        "pending": delivery.is_some(),
        "message_count": delivery.as_ref().map_or(0, |item| item.message_count),
        "through_id": delivery.as_ref().map_or(0, |item| item.through_id),
        "payload": {"redacted": true},
    }))?;
    Ok(())
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
    if matches!(
        request.peer_communication_handler_command.as_deref(),
        Some([])
    ) {
        bail!("peer_communication capability was requested without a handler command");
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
    let peer_post_tool_hook_command = request
        .peer_communication_handler_command
        .as_deref()
        .map(peer_post_tool_hook_command)
        .transpose()?;

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

    let mut cli_overrides = request
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
    if let Some(command) = peer_post_tool_hook_command.as_ref() {
        cli_overrides.push((
            "hooks.PostToolUse".to_string(),
            serde_json::from_value::<TomlValue>(json!([{
                "matcher": ".*",
                "hooks": [{
                    "type": "command",
                    "command": command,
                    "timeout": 10,
                    "async": false,
                    "additionalContextLimit": 0,
                }],
            }]))
            .context("build protected peer PostToolUse hook configuration")?,
        ));
    }
    let mut config_builder = ConfigBuilder::default()
        .codex_home(codex_home.clone())
        .harness_overrides(overrides);
    if !cli_overrides.is_empty() {
        config_builder = config_builder.cli_overrides(cli_overrides);
    }
    let mut config = config_builder.build().await.context("load Codex config")?;
    if let Some(command) = peer_post_tool_hook_command.as_deref() {
        trust_only_peer_post_tool_hook(&mut config, command)?;
        config
            .features
            .enable(Feature::CodexHooks)
            .context("enable protected Codex peer-delivery hook")?;
    }
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
    // Feature flags alone are not authoritative: when agents remain enabled,
    // model metadata can select the native V2 collaboration runtime. Force the
    // pinned core's explicit disabled override before resolving model metadata.
    config.agents_enabled = false;
    config
        .features
        .disable(Feature::Collab)
        .context("disable Codex collab feature")?;
    config
        .features
        .disable(Feature::MultiAgentV2)
        .context("disable Codex multi-agent feature")?;
    if config.agents_enabled
        || config.features.enabled(Feature::Collab)
        || config.features.enabled(Feature::MultiAgentV2)
    {
        bail!("native Codex collaboration could not be disabled");
    }

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
        build_models_manager(&config, auth_manager),
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

    let mut start_options = StartThreadOptions::new(config);
    start_options.dynamic_tools =
        metalanguage_dynamic_tools(request.peer_communication_handler_command.is_some());
    let NewThread {
        thread_id,
        thread,
        session_configured,
    } = thread_manager
        .start_thread(start_options)
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

    let spawn_child_handler_command = request.spawn_child_handler_command.clone();
    let peer_communication_handler_command = request.peer_communication_handler_command.clone();
    let prompt = request
        .initial_user_text
        .unwrap_or_else(|| "Read README.md.".to_string());
    let turn_result = run_turn(
        &thread,
        &thread_id.to_string(),
        prompt,
        spawn_child_handler_command,
        peer_communication_handler_command,
        sensitive_tools,
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

#[derive(Debug)]
struct PreparedPeerDelivery {
    delivery_id: String,
    injection: String,
    message_count: u64,
    through_id: u64,
    has_more: bool,
}

fn peer_supervisor_request(
    command: &[String],
    tool: &str,
    arguments: Value,
) -> anyhow::Result<Value> {
    let payload = json!({
        "tool": tool,
        "namespace": null,
        "arguments": arguments,
    });
    let output = run_dynamic_tool_handler(
        command,
        &payload,
        "peer delivery supervisor",
        Some(Duration::from_secs(10)),
    )
    .map_err(|error| anyhow!("peer delivery supervisor transport failed: {error}"))?;
    let object = output
        .as_object()
        .context("peer delivery supervisor response was not an object")?;
    let success = object
        .get("success")
        .and_then(Value::as_bool)
        .context("peer delivery supervisor response omitted boolean success")?;
    if !success {
        let error_code = object
            .get("error_code")
            .and_then(Value::as_str)
            .filter(|value| safe_diagnostic_code(value))
            .unwrap_or("unspecified_error");
        bail!("peer delivery supervisor rejected the request ({error_code})");
    }
    Ok(output)
}

fn safe_diagnostic_code(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 80
        && value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
}

fn prepare_peer_delivery(command: &[String]) -> anyhow::Result<Option<PreparedPeerDelivery>> {
    let output = peer_supervisor_request(command, "_peer_delivery_prepare", json!({}))?;
    if !output
        .get("pending")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return Ok(None);
    }
    let delivery_id = output
        .get("delivery_id")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .context("peer delivery omitted delivery_id")?
        .to_string();
    let injection = output
        .get("injection")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .context("peer delivery omitted injection")?
        .to_string();
    if injection.len() > 8_192 {
        bail!("peer delivery exceeded the injection limit");
    }
    Ok(Some(PreparedPeerDelivery {
        delivery_id,
        injection,
        message_count: output
            .get("message_count")
            .and_then(Value::as_u64)
            .context("peer delivery omitted message_count")?,
        through_id: output
            .get("through_id")
            .and_then(Value::as_u64)
            .context("peer delivery omitted through_id")?,
        has_more: output
            .get("has_more")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    }))
}

fn acknowledge_peer_delivery(command: &[String], delivery_id: &str) -> anyhow::Result<()> {
    let output = peer_supervisor_request(
        command,
        "_peer_delivery_ack",
        json!({"delivery_id": delivery_id}),
    )?;
    if !output
        .get("committed")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        bail!("peer delivery acknowledgement was not committed");
    }
    Ok(())
}

fn claim_peer_delivery(
    command: &[String],
    boundary_id: &str,
) -> anyhow::Result<Option<PreparedPeerDelivery>> {
    let output = peer_supervisor_request(
        command,
        "_peer_delivery_claim",
        json!({"boundary_id": boundary_id}),
    )?;
    parse_prepared_peer_delivery(output)
}

fn parse_prepared_peer_delivery(output: Value) -> anyhow::Result<Option<PreparedPeerDelivery>> {
    if !output
        .get("pending")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return Ok(None);
    }
    let delivery_id = output
        .get("delivery_id")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .context("peer delivery omitted delivery_id")?
        .to_string();
    let injection = output
        .get("injection")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .context("peer delivery omitted injection")?
        .to_string();
    if injection.len() > 8_192 {
        bail!("peer delivery exceeded the injection limit");
    }
    Ok(Some(PreparedPeerDelivery {
        delivery_id,
        injection,
        message_count: output
            .get("message_count")
            .and_then(Value::as_u64)
            .context("peer delivery omitted message_count")?,
        through_id: output
            .get("through_id")
            .and_then(Value::as_u64)
            .context("peer delivery omitted through_id")?,
        has_more: output
            .get("has_more")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    }))
}

#[derive(Debug)]
struct PeerBoundaryAcknowledgement {
    matched: bool,
    delivery: Option<PreparedPeerDelivery>,
}

fn acknowledge_peer_delivery_boundary(
    command: &[String],
    boundary_id: &str,
) -> anyhow::Result<PeerBoundaryAcknowledgement> {
    let output = peer_supervisor_request(
        command,
        "_peer_delivery_ack_boundary",
        json!({"boundary_id": boundary_id}),
    )?;
    if !output
        .get("matched")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return Ok(PeerBoundaryAcknowledgement {
            matched: false,
            delivery: None,
        });
    }
    if !output
        .get("committed")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        bail!("peer tool-cycle delivery acknowledgement was not committed");
    }
    let delivery = PreparedPeerDelivery {
        delivery_id: String::new(),
        injection: String::new(),
        message_count: output
            .get("message_count")
            .and_then(Value::as_u64)
            .context("peer boundary acknowledgement omitted message_count")?,
        through_id: output
            .get("through_id")
            .and_then(Value::as_u64)
            .context("peer boundary acknowledgement omitted through_id")?,
        has_more: output
            .get("has_more")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    };
    Ok(PeerBoundaryAcknowledgement {
        matched: true,
        delivery: Some(delivery),
    })
}

fn open_next_peer_tool_cycle(command: &[String]) -> anyhow::Result<()> {
    let _ = peer_supervisor_request(command, "_peer_delivery_cycle_started", json!({}))?;
    Ok(())
}

fn peer_delivery_event(delivery: &PreparedPeerDelivery) -> Value {
    json!({
        "event": "peer_delivery_injected",
        "message_count": delivery.message_count,
        "through_id": delivery.through_id,
        "has_more": delivery.has_more,
        "payload": {"redacted": true},
    })
}

fn prepare_peer_delivery_with_diagnostics(
    command: &[String],
    boundary: &str,
) -> anyhow::Result<Option<PreparedPeerDelivery>> {
    match prepare_peer_delivery(command) {
        Ok(delivery) => Ok(delivery),
        Err(error) => {
            emit(json!({
                "event": "error",
                "error_code": "peer_delivery_prepare_failed",
                "error_message": error.to_string(),
                "peer_delivery_boundary": boundary,
            }))?;
            Err(error)
        }
    }
}

fn acknowledge_peer_delivery_with_diagnostics(
    command: &[String],
    delivery_id: &str,
    boundary: &str,
) -> anyhow::Result<()> {
    match acknowledge_peer_delivery(command, delivery_id) {
        Ok(()) => Ok(()),
        Err(error) => {
            emit(json!({
                "event": "error",
                "error_code": "peer_delivery_ack_failed",
                "error_message": error.to_string(),
                "peer_delivery_boundary": boundary,
            }))?;
            Err(error)
        }
    }
}

async fn run_turn(
    thread: &codex_core_api::CodexThread,
    thread_id: &str,
    prompt: String,
    spawn_child_handler_command: Option<Vec<String>>,
    peer_communication_handler_command: Option<Vec<String>>,
    sensitive_tools: Vec<McpToolSelector>,
) -> anyhow::Result<()> {
    if let Some(command) = peer_communication_handler_command.as_deref() {
        // A restarted runner starts a new inference cycle. This clears only a
        // previously committed post-tool gate; an uncommitted lease remains
        // pending and is recovered by the ordinary initial prepare below.
        open_next_peer_tool_cycle(command)?;
    }
    let initial_delivery = match peer_communication_handler_command.as_deref() {
        Some(command) => prepare_peer_delivery_with_diagnostics(command, "initial_turn")?,
        None => None,
    };
    let prompt = match initial_delivery.as_ref() {
        Some(delivery) => format!("{prompt}\n\n{}", delivery.injection),
        None => prompt,
    };
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
    if let Some(delivery) = initial_delivery.as_ref() {
        acknowledge_peer_delivery_with_diagnostics(
            peer_communication_handler_command
                .as_deref()
                .expect("delivery requires a handler"),
            &delivery.delivery_id,
            "initial_turn",
        )?;
        emit(peer_delivery_event(delivery))?;
    }

    let mut current_turn_id: Option<String> = None;
    let mut final_text = String::new();
    let mut completed_peer_hook_boundaries: HashSet<String> = HashSet::new();
    loop {
        let event = thread.next_event().await.context("read Codex event")?;
        if event_starts_model_sampling(&event.msg)
            && !completed_peer_hook_boundaries.is_empty()
            && let Some(command) = peer_communication_handler_command.as_deref()
        {
            let mut committed_delivery = false;
            for boundary_id in completed_peer_hook_boundaries.drain() {
                let acknowledgement = acknowledge_peer_delivery_boundary(command, &boundary_id)
                    .map_err(|error| {
                        anyhow!("peer delivery boundary acknowledgement failed: {error}")
                    })?;
                if acknowledgement.matched {
                    let delivery = acknowledgement
                        .delivery
                        .as_ref()
                        .expect("matched acknowledgement has delivery metadata");
                    emit(peer_delivery_event(delivery))?;
                    committed_delivery = true;
                }
            }
            if committed_delivery {
                // Model-authored activity proves the injected context has been
                // accepted for this inference. The following tool result, if
                // any, belongs to a new sampling cycle.
                open_next_peer_tool_cycle(command)?;
            }
        }
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
                emit(json!({
                    "event": "tool_begin",
                    "tool": "exec_command",
                    "call_id": event.call_id,
                    "turn_id": event.turn_id,
                    "command": event.command,
                    "cwd": event.cwd.to_string(),
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
                    "cwd": event.cwd.to_string(),
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
            EventMsg::McpToolCallBegin(event) => {
                emit(logged_mcp_tool_begin_event(event, &sensitive_tools))?;
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
                } else if let Some(notification) = mapped_item_notification(
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
            EventMsg::HookCompleted(event)
                if event.run.event_name == HookEventName::PostToolUse
                    && event.run.status == HookRunStatus::Completed =>
            {
                let run_prefix = format!(
                    "post-tool-use:{}:{}:",
                    event.run.display_order,
                    event.run.source_path.display()
                );
                let boundary_id = event
                    .run
                    .id
                    .strip_prefix(&run_prefix)
                    .filter(|boundary| !boundary.is_empty())
                    .context("protected peer hook completion omitted tool boundary")?;
                completed_peer_hook_boundaries.insert(boundary_id.to_string());
            }
            EventMsg::HookCompleted(event)
                if event.run.event_name == HookEventName::PostToolUse
                    && event.run.status != HookRunStatus::Completed =>
            {
                emit(json!({
                    "event": "error",
                    "error_code": "peer_delivery_post_tool_hook_failed",
                    "error_message": "protected peer delivery PostToolUse hook failed",
                }))?;
                bail!("protected peer delivery PostToolUse hook failed");
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
                if let Some(command) = peer_communication_handler_command.as_deref()
                    && let Some(delivery) =
                        prepare_peer_delivery_with_diagnostics(command, "post_turn")?
                {
                    let submission = thread
                        .start_turn_if_idle(TurnInputRequest::user_input(vec![UserInput::Text {
                            text: delivery.injection.clone(),
                            text_elements: Vec::new(),
                        }]))
                        .await
                        .context("submit automatic peer delivery")?;
                    if let StartIfIdleSubmission::NotSubmitted { reason } = submission {
                        let message =
                            format!("automatic peer delivery was not submitted: {reason:?}");
                        emit(json!({
                            "event": "error",
                            "error_code": "peer_delivery_not_submitted",
                            "error_message": message,
                        }))?;
                        bail!(message);
                    }
                    acknowledge_peer_delivery_with_diagnostics(
                        command,
                        &delivery.delivery_id,
                        "post_turn",
                    )?;
                    emit(peer_delivery_event(&delivery))?;
                    current_turn_id = None;
                    continue;
                }
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
                let arguments = if is_peer_message_tool(&request.tool) {
                    json!({"redacted": true})
                } else {
                    request.arguments.clone()
                };
                emit(json!({
                    "event": "tool_begin",
                    "tool": request.tool,
                    "namespace": request.namespace,
                    "call_id": request.call_id,
                    "turn_id": request.turn_id,
                    "arguments": arguments,
                }))?;
                let response = handle_metalanguage_dynamic_tool(
                    request,
                    spawn_child_handler_command.as_deref(),
                    peer_communication_handler_command.as_deref(),
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

fn event_starts_model_sampling(event: &EventMsg) -> bool {
    matches!(
        event,
        EventMsg::ItemStarted(_)
            | EventMsg::AgentMessageContentDelta(_)
            | EventMsg::ReasoningContentDelta(_)
            | EventMsg::ReasoningRawContentDelta(_)
            | EventMsg::AgentMessage(_)
            | EventMsg::ExecCommandBegin(_)
            | EventMsg::PatchApplyBegin(_)
            | EventMsg::McpToolCallBegin(_)
            | EventMsg::DynamicToolCallRequest(_)
            | EventMsg::TurnComplete(_)
    )
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

fn metalanguage_dynamic_tools(include_peer_communication: bool) -> Vec<DynamicToolSpec> {
    let mut tools = vec![DynamicToolSpec::Function(DynamicToolFunctionSpec {
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
    })];
    if include_peer_communication {
        tools.push(DynamicToolSpec::Function(DynamicToolFunctionSpec {
            name: "send_message".to_string(),
            description: concat!(
                "Send a bounded non-empty UTF-8 direct message to a named peer in the current batch. ",
                "The receiver must exactly match a peer name in runtime.md. Delivery is automatic ",
                "at a subsequent supported inference boundary."
            )
            .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "minLength": 1,
                        "description": "A bounded non-empty UTF-8 message (maximum 2048 bytes)."
                    },
                    "receiver": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The exact peer name listed in runtime.md."
                    }
                },
                "required": ["message", "receiver"],
                "additionalProperties": false,
            }),
            defer_loading: false,
        }));
    }
    tools
}

#[cfg(test)]
fn dynamic_tool_name(tool: &DynamicToolSpec) -> &str {
    match tool {
        DynamicToolSpec::Function(function) => &function.name,
        DynamicToolSpec::Namespace(namespace) => &namespace.name,
    }
}

fn is_peer_message_tool(tool: &str) -> bool {
    tool == "send_message"
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
    peer_communication_handler_command: Option<&[String]>,
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
        "send_message" => {
            handle_peer_communication_tool(request, peer_communication_handler_command)
        }
        other => dynamic_tool_json_response(
            false,
            json!({"error": "unsupported dynamic tool", "tool": other}),
        ),
    }
}

fn handle_peer_communication_tool(
    request: &DynamicToolCallRequest,
    handler_command: Option<&[String]>,
) -> DynamicToolResponse {
    let Some(command) = handler_command else {
        return dynamic_tool_json_response(
            false,
            peer_communication_failure(
                &request.tool,
                "peer_communication_handler_unavailable",
                "peer communication handler command is not configured",
                true,
            ),
        );
    };
    if command.is_empty() {
        return dynamic_tool_json_response(
            false,
            peer_communication_failure(
                &request.tool,
                "peer_communication_handler_unavailable",
                "peer communication handler command is empty",
                true,
            ),
        );
    }
    let handler_payload = json!({
        "tool": request.tool,
        "namespace": request.namespace,
        "call_id": request.call_id,
        "arguments": request.arguments,
    });
    let output = match run_dynamic_tool_handler(
        command,
        &handler_payload,
        &request.tool,
        Some(Duration::from_secs(10)),
    ) {
        Ok(value) => value,
        Err(_message) => {
            return dynamic_tool_json_response(
                false,
                peer_communication_failure(
                    &request.tool,
                    "peer_communication_handler_failed",
                    "peer communication supervisor handler failed",
                    true,
                ),
            );
        }
    };
    let success = output
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    dynamic_tool_json_response(success, output)
}

fn peer_communication_failure(tool: &str, error_code: &str, error: &str, retryable: bool) -> Value {
    json!({
        "success": false,
        "tool": tool,
        "retryable": retryable,
        "error_code": error_code,
        "error": error,
    })
}

fn handle_spawn_child_tool(
    request: &DynamicToolCallRequest,
    spawn_child_handler_command: Option<&[String]>,
) -> DynamicToolResponse {
    let Some(command) = spawn_child_handler_command else {
        return dynamic_tool_json_response(
            false,
            spawn_child_failure(
                "spawn_child_handler_unavailable",
                "spawn_child handler command is not configured",
                true,
            ),
        );
    };
    if command.is_empty() {
        return dynamic_tool_json_response(
            false,
            spawn_child_failure(
                "spawn_child_handler_unavailable",
                "spawn_child handler command is empty",
                true,
            ),
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
            );
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
    run_dynamic_tool_handler(command, payload, "spawn_child", None)
}

fn run_dynamic_tool_handler(
    command: &[String],
    payload: &Value,
    label: &str,
    timeout: Option<Duration>,
) -> Result<Value, String> {
    let Some(program) = command.first() else {
        return Err(format!("{label} handler command is empty"));
    };
    let mut child = Command::new(program)
        .args(&command[1..])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|err| format!("failed to start {label} handler ({:?})", err.kind()))?;

    {
        let Some(stdin) = child.stdin.as_mut() else {
            return Err(format!("{label} handler stdin is unavailable"));
        };
        serde_json::to_writer(&mut *stdin, payload)
            .map_err(|err| format!("failed to serialize {label} payload: {err}"))?;
        stdin
            .write_all(b"\n")
            .map_err(|err| format!("failed to write {label} payload: {err}"))?;
    }
    drop(child.stdin.take());

    if let Some(timeout) = timeout {
        let deadline = Instant::now() + timeout;
        loop {
            match child.try_wait() {
                Ok(Some(_)) => break,
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(10));
                }
                Ok(None) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!("{label} handler timed out"));
                }
                Err(err) => {
                    return Err(format!("failed to poll {label} handler ({:?})", err.kind()));
                }
            }
        }
    }

    let output = child
        .wait_with_output()
        .map_err(|err| format!("failed to wait for {label} handler ({:?})", err.kind()))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if !output.status.success() {
        return Err(format!(
            "{label} handler exited with status {}",
            output.status
        ));
    }
    if stdout.is_empty() {
        return Err(format!("{label} handler returned empty stdout"));
    }
    serde_json::from_str(&stdout)
        .map_err(|err| format!("failed to parse {label} handler response: {err}"))
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
    ) || matches!(
        item,
        TurnItem::DynamicToolCall(call) if is_peer_message_tool(&call.tool)
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
    use codex_protocol::ThreadId;
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
        let names = metalanguage_dynamic_tools(true)
            .into_iter()
            .map(|tool| dynamic_tool_name(&tool).to_string())
            .collect::<Vec<_>>();
        assert_eq!(names, vec!["spawn_child", "send_message"]);
        assert!(!names.contains(&"peer_communication".to_string()));
        assert!(!names.contains(&"read_messages".to_string()));
        assert!(!names.contains(&"submit_solution".to_string()));
        let without_peer = metalanguage_dynamic_tools(false)
            .into_iter()
            .map(|tool| dynamic_tool_name(&tool).to_string())
            .collect::<Vec<_>>();
        assert_eq!(without_peer, vec!["spawn_child"]);
    }

    #[test]
    fn spawn_child_schema_requires_prompt_and_workspace_dir() {
        let mut tools = metalanguage_dynamic_tools(false);
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
    fn peer_message_schema_is_exact_and_bounded() {
        let mut tools = metalanguage_dynamic_tools(true);
        let DynamicToolSpec::Function(send) = tools.remove(1) else {
            panic!("send_message must be a function tool");
        };
        assert_eq!(tools.len(), 1);
        assert_eq!(send.name, "send_message");
        assert_eq!(
            send.input_schema,
            json!({
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "minLength": 1,
                        "description": "A bounded non-empty UTF-8 message (maximum 2048 bytes)."
                    },
                    "receiver": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The exact peer name listed in runtime.md."
                    }
                },
                "required": ["message", "receiver"],
                "additionalProperties": false
            })
        );
        assert_eq!(
            send.description,
            "Send a bounded non-empty UTF-8 direct message to a named peer in the current batch. The receiver must exactly match a peer name in runtime.md. Delivery is automatic at a subsequent supported inference boundary."
        );
    }

    #[test]
    fn send_message_callback_uses_configured_central_handler() {
        let request = DynamicToolCallRequest {
            call_id: "peer-call".to_string(),
            turn_id: "turn".to_string(),
            started_at_ms: 0,
            namespace: None,
            tool: "send_message".to_string(),
            arguments: json!({"message": "finding", "receiver": "Alice"}),
        };
        let command = vec![
            "python3".to_string(),
            "-c".to_string(),
            "import json,sys; payload=json.load(sys.stdin); print(json.dumps({'success': True, 'tool': payload['tool'], 'arguments': payload['arguments']}))".to_string(),
        ];
        let response = handle_metalanguage_dynamic_tool(&request, None, Some(&command));
        assert!(response.success);
        let DynamicToolCallOutputContentItem::InputText { text } = &response.content_items[0]
        else {
            panic!("peer response must be JSON text");
        };
        let payload: Value = serde_json::from_str(text).expect("parse central handler response");
        assert_eq!(payload["tool"], "send_message");
        assert_eq!(payload["arguments"]["receiver"], "Alice");

        for tool in ["read_messages", "peer_communication"] {
            let legacy = DynamicToolCallRequest {
                call_id: "legacy".to_string(),
                turn_id: "turn".to_string(),
                started_at_ms: 0,
                namespace: None,
                tool: tool.to_string(),
                arguments: json!({}),
            };
            assert!(!handle_metalanguage_dynamic_tool(&legacy, None, None).success);
        }
    }

    #[test]
    fn protected_delivery_prepare_and_ack_use_supervisor_handler() {
        let command = vec![
            "python3".to_string(),
            "-c".to_string(),
            concat!(
                "import json,sys; p=json.load(sys.stdin); ",
                "print(json.dumps({'success':True,'pending':True,'delivery_id':'lease-7',",
                "'injection':'[UNTRUSTED PEER CONTENT] Message #7 from Alice: finding',",
                "'message_count':1,'through_id':7,'has_more':False} if ",
                "p['tool']=='_peer_delivery_prepare' else {'success':True,'committed':True}))"
            )
            .to_string(),
        ];
        let prepared = prepare_peer_delivery(&command)
            .expect("prepare through supervisor")
            .expect("pending delivery");
        assert_eq!(prepared.delivery_id, "lease-7");
        assert!(prepared.injection.contains("UNTRUSTED PEER CONTENT"));
        acknowledge_peer_delivery(&command, &prepared.delivery_id).expect("ack through supervisor");
    }

    #[test]
    fn peer_communication_handler_timeout_is_bounded() {
        let command = vec!["sh".to_string(), "-c".to_string(), "sleep 5".to_string()];
        let started = Instant::now();
        let error = run_dynamic_tool_handler(
            &command,
            &json!({"tool": "send_message"}),
            "send_message",
            Some(Duration::from_millis(30)),
        )
        .expect_err("handler should time out");
        assert!(error.contains("timed out"));
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn peer_delivery_diagnostics_are_specific_and_payload_redacted() {
        let rejected = vec![
            "python3".to_string(),
            "-c".to_string(),
            "import json; print(json.dumps({'success':False,'error_code':'peer_communication_authentication_failed','error':'private-body'}))".to_string(),
        ];
        let error = prepare_peer_delivery(&rejected).expect_err("authentication must fail");
        let rendered = error.to_string();
        assert!(rendered.contains("peer_communication_authentication_failed"));
        assert!(!rendered.contains("private-body"));

        let malformed = vec![
            "python3".to_string(),
            "-c".to_string(),
            "print('private-message-body is not json')".to_string(),
        ];
        let error = prepare_peer_delivery(&malformed).expect_err("malformed response must fail");
        let rendered = error.to_string();
        assert!(rendered.contains("failed to parse"));
        assert!(!rendered.contains("private-message-body"));

        let wrong_schema = vec![
            "python3".to_string(),
            "-c".to_string(),
            "import json; print(json.dumps({'pending':False}))".to_string(),
        ];
        let error = prepare_peer_delivery(&wrong_schema).expect_err("schema failure must fail");
        assert!(error.to_string().contains("omitted boolean success"));

        let exited = vec![
            "sh".to_string(),
            "-c".to_string(),
            "echo private-stderr-body >&2; exit 7".to_string(),
        ];
        let error = prepare_peer_delivery(&exited).expect_err("exit failure must fail");
        let rendered = error.to_string();
        assert!(rendered.contains("exited with status"));
        assert!(!rendered.contains("private-stderr-body"));
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
            let notification =
                mapped_item_notification(item_event, "thread", Some("turn"), &sensitive_tools)
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
        let non_sensitive_notification =
            mapped_item_notification(&non_sensitive, "thread", Some("turn"), &[])
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
        let spawn_child_notification =
            mapped_item_notification(&spawn_child, "thread", Some("turn"), &sensitive_mcp_tools())
                .expect("map spawn_child item")
                .expect("retain spawn_child item");
        let spawn_child_json = spawn_child_notification.to_string();
        for sentinel in [ARGUMENT_SENTINEL, RESULT_SENTINEL] {
            assert!(spawn_child_json.contains(sentinel));
        }

        for tool in ["send_message"] {
            let peer = item_completed(TurnItem::DynamicToolCall(DynamicToolCallItem {
                id: "peer-call".to_string(),
                namespace: None,
                tool: tool.to_string(),
                arguments: json!({"message": ARGUMENT_SENTINEL}),
                status: DynamicToolCallStatus::Completed,
                content_items: Some(vec![DynamicToolCallOutputContentItem::InputText {
                    text: RESULT_SENTINEL.to_string(),
                }]),
                success: Some(true),
                error: None,
                duration: Some(Duration::from_millis(1)),
            }));
            assert!(
                mapped_item_notification(&peer, "thread", Some("turn"), &sensitive_mcp_tools(),)
                    .expect("map peer item")
                    .is_none()
            );
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
