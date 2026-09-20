"""Load exact-directory AGENTS.md files as neutral, additive context.

Literal ``cd``/``pushd``/``popd`` parsing is deliberately bounded, and literal
Git ``-C`` operands are treated as directory-scoped work.
Dynamic parser targets, substitutions, functions, subshells, structured control
flow, pipelines, background jobs, and directory-stack indices are ignored
rather than guessed. Comments, quoted prose, and heredoc bodies are not
executable transitions.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_CONTROL_OPERATORS = {";", "&&", "||", "|", "|&", "&", "(", ")", "{", "}"}
_REDIRECT_OPERATORS = {
    "<",
    ">",
    "<<",
    "<<-",
    "<<<",
    ">>",
    "<>",
    ">|",
    "<&",
    ">&",
    "&>",
    "&>>",
}
_UNSUPPORTED_COMMANDS = {
    "case",
    "coproc",
    "do",
    "done",
    "elif",
    "else",
    "esac",
    "fi",
    "for",
    "function",
    "if",
    "select",
    "then",
    "time",
    "until",
    "while",
}
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_TOOL_NAMES = {"bash", "exec_command", "run_bash", "shell"}
_GIT_NO_VALUE_OPTIONS = {
    "-p",
    "-P",
    "--paginate",
    "--no-pager",
    "--no-replace-objects",
    "--bare",
    "--literal-pathspecs",
    "--glob-pathspecs",
    "--noglob-pathspecs",
    "--icase-pathspecs",
    "--no-optional-locks",
    "--no-advice",
    "--version",
    "--help",
}
_GIT_VALUE_OPTIONS = {"-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix"}


@dataclass(frozen=True)
class _ShellWord:
    value: str
    dynamic: bool = False


@dataclass(frozen=True)
class _LiteralShellScopes:
    transitions: tuple[Path, ...]
    git_directories: tuple[Path, ...]


@dataclass(frozen=True)
class ManagedContextActivation:
    additional_context: str
    paths: tuple[Path, ...]
    activation: str

    @property
    def deferred(self) -> bool:
        return bool(self.additional_context)


NEUTRAL_DEFER_RESULT = "Local context activated; tool was not executed."


def _managed_roots(context: dict[str, Any]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for key in ("workdir", "shared_archives_root", "shared_workspace_dir"):
        value = context.get(key)
        if isinstance(value, str) and value:
            try:
                root = Path(value).expanduser().resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if root.is_dir() and root not in roots:
                roots.append(root)
    return tuple(roots)


def _tool_directory(payload: dict[str, Any], root: Path) -> Path:
    tool_input = payload.get("tool_input")
    arguments = tool_input if isinstance(tool_input, dict) else {}
    for key in ("workdir", "working_directory", "cwd", "directory"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            return path.resolve() if path.is_absolute() else (root / path).resolve()
    for key in ("filePath", "file_path", "path"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            path = path.resolve() if path.is_absolute() else (root / path).resolve()
            return path if path.is_dir() else path.parent
    return root


def _lex_shell(command: str) -> list[_ShellWord | str] | None:
    """Tokenize the small, static shell subset used for directory changes."""

    tokens: list[_ShellWord | str] = []
    word: list[str] = []
    word_dynamic = False
    word_started = False
    pending_heredocs: list[tuple[str, bool]] = []
    awaiting_heredoc: bool | None = None
    index = 0

    def finish_word() -> None:
        nonlocal word, word_dynamic, word_started, awaiting_heredoc
        if not word_started:
            return
        token = _ShellWord("".join(word), word_dynamic)
        tokens.append(token)
        if awaiting_heredoc is not None:
            pending_heredocs.append((token.value, awaiting_heredoc))
            awaiting_heredoc = None
        word = []
        word_dynamic = False
        word_started = False

    def finish_line(position: int) -> int | None:
        finish_word()
        if not tokens or tokens[-1] != ";":
            tokens.append(";")
        for delimiter, strip_tabs in pending_heredocs:
            while True:
                line_end = command.find("\n", position)
                if line_end < 0:
                    line_end = len(command)
                line = command[position:line_end]
                compared = line.lstrip("\t") if strip_tabs else line
                position = line_end + (line_end < len(command))
                if compared == delimiter:
                    break
                if line_end == len(command):
                    return None
        pending_heredocs.clear()
        return position

    while index < len(command):
        character = command[index]
        if character in " \t\r":
            finish_word()
            index += 1
            continue
        if character == "\n":
            position = finish_line(index + 1)
            if position is None:
                return None
            index = position
            continue
        if character == "#" and not word_started:
            line_end = command.find("\n", index)
            if line_end < 0:
                index = len(command)
            else:
                position = finish_line(line_end + 1)
                if position is None:
                    return None
                index = position
            continue
        if character == "'":
            word_started = True
            quote_end = command.find("'", index + 1)
            if quote_end < 0:
                return None
            word.append(command[index + 1 : quote_end])
            index = quote_end + 1
            continue
        if character == '"':
            word_started = True
            index += 1
            while index < len(command) and command[index] != '"':
                quoted = command[index]
                if quoted == "\\" and index + 1 < len(command):
                    escaped = command[index + 1]
                    if escaped in {'$', '`', '"', "\\", "\n"}:
                        if escaped != "\n":
                            word.append(escaped)
                        index += 2
                        continue
                if quoted in {"$", "`"}:
                    word_dynamic = True
                word.append(quoted)
                index += 1
            if index >= len(command):
                return None
            index += 1
            continue
        if character == "\\":
            word_started = True
            if index + 1 >= len(command):
                return None
            escaped = command[index + 1]
            if escaped != "\n":
                word.append(escaped)
            index += 2
            continue
        if command.startswith("$(", index) or character == "`":
            return None
        if character in ";&|()<>{}":
            finish_word()
            operator = next(
                (
                    candidate
                    for candidate in (
                        "&>>",
                        "<<-",
                        "<<<",
                        "&&",
                        "||",
                        "|&",
                        ">>",
                        "<<",
                        "<>",
                        ">|",
                        "<&",
                        ">&",
                        "&>",
                    )
                    if command.startswith(candidate, index)
                ),
                character,
            )
            tokens.append(operator)
            if operator in {"<<", "<<-"}:
                awaiting_heredoc = operator == "<<-"
            index += len(operator)
            continue
        if character in {"$", "*", "?", "["}:
            word_dynamic = True
        if character == "~" and not word_started:
            word_dynamic = True
        if character in {"{", "}"}:
            word_dynamic = True
        word_started = True
        word.append(character)
        index += 1

    finish_word()
    if awaiting_heredoc is not None or pending_heredocs:
        return None
    while tokens and tokens[-1] == ";":
        tokens.pop()
    return tokens


def _command_words(tokens: list[_ShellWord | str]) -> list[_ShellWord] | None:
    words: list[_ShellWord] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if isinstance(token, str):
            if token not in _REDIRECT_OPERATORS:
                return None
            if words and words[-1].value.isdigit():
                words.pop()
            index += 1
            if index >= len(tokens) or not isinstance(tokens[index], _ShellWord):
                return None
            index += 1
            continue
        words.append(token)
        index += 1
    while words and _ASSIGNMENT.match(words[0].value):
        words.pop(0)
    return words


def _literal_directory_argument(words: list[_ShellWord], command: str) -> str | None:
    arguments = words[1:]
    if command == "cd":
        while arguments and not arguments[0].dynamic and arguments[0].value.startswith("-"):
            option = arguments.pop(0).value
            if option == "--":
                break
            if option == "-" or any(character not in "LPe" for character in option[1:]):
                return None
    elif arguments and not arguments[0].dynamic:
        if arguments[0].value == "--":
            arguments.pop(0)
        elif arguments[0].value.startswith("-") or re.fullmatch(
            r"[+-]\d+", arguments[0].value
        ):
            return None
    if len(arguments) != 1 or arguments[0].dynamic or not arguments[0].value:
        return None
    return arguments[0].value


def _change_directory(current: Path, target: str) -> tuple[Path, Path] | None:
    target_path = Path(target)
    logical = Path(
        os.path.normpath(target if target_path.is_absolute() else current / target_path)
    )
    try:
        resolved = logical.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_dir() or not os.access(resolved, os.X_OK):
        return None
    return logical, resolved


def _simple_shell_commands(
    command: str,
) -> tuple[list[list[_ShellWord]], list[str]] | None:
    tokens = _lex_shell(command)
    unsupported_operators = _CONTROL_OPERATORS - {";", "&&", "||"}
    if tokens is None or any(token in unsupported_operators for token in tokens):
        return None
    for index, token in enumerate(tokens):
        if token not in {"&&", "||"}:
            continue
        if index == 0 or index == len(tokens) - 1:
            return None
        if tokens[index - 1] in _CONTROL_OPERATORS or tokens[index + 1] in _CONTROL_OPERATORS:
            return None

    simple_commands: list[list[_ShellWord | str]] = []
    separators: list[str] = []
    current_tokens: list[_ShellWord | str] = []
    for token in tokens:
        if token in {";", "&&", "||"}:
            if current_tokens:
                simple_commands.append(current_tokens)
                separators.append(str(token))
                current_tokens = []
            continue
        current_tokens.append(token)
    if current_tokens:
        simple_commands.append(current_tokens)
    if len(separators) >= len(simple_commands):
        separators = separators[: len(simple_commands) - 1]

    normalized: list[list[_ShellWord]] = []
    for simple in simple_commands:
        words = _command_words(simple)
        if words is None:
            return None
        if words and not words[0].dynamic and words[0].value in _UNSUPPORTED_COMMANDS:
            return None
        normalized.append(words)
    return normalized, separators


def _git_directory_operands(
    words: list[_ShellWord],
    start_directory: Path,
) -> tuple[Path, ...] | None:
    """Resolve the leading global ``git -C`` options for one simple command.

    Unknown global options are rejected rather than guessing their arity. A
    malformed or dynamic ``-C`` rejects all scopes for that Git invocation.
    """

    if not words or words[0].dynamic or words[0].value != "git":
        return ()
    current = start_directory
    directories: list[Path] = []
    index = 1
    while index < len(words):
        word = words[index]
        if word.dynamic:
            return None
        value = word.value
        if value == "--":
            break
        if value == "-C":
            index += 1
            if index >= len(words):
                return None
            operand = words[index]
            if operand.dynamic or not operand.value:
                return None
            changed = _change_directory(current, operand.value)
            if changed is None:
                return None
            logical, resolved = changed
            current = logical
            directories.append(resolved)
            index += 1
            continue
        if value in _GIT_NO_VALUE_OPTIONS:
            index += 1
            continue
        if value in _GIT_VALUE_OPTIONS:
            index += 1
            if index >= len(words):
                return None
            index += 1
            continue
        if any(
            value.startswith(prefix)
            for prefix in (
                "--exec-path=",
                "--git-dir=",
                "--work-tree=",
                "--namespace=",
                "--super-prefix=",
                "--config-env=",
            )
        ):
            index += 1
            continue
        if value == "--exec-path":
            index += 1
            continue
        if value.startswith("-"):
            return None
        break
    return tuple(directories)


def _literal_shell_scopes(
    command: str,
    start_directory: Path,
) -> _LiteralShellScopes:
    parsed = _simple_shell_commands(command)
    if parsed is None:
        return _LiteralShellScopes((), ())
    normalized, separators = parsed

    current = start_directory.resolve()
    stack: list[Path] = []
    transitions: list[Path] = []
    directories: list[Path] = []
    previous_status: bool | None = None
    preceding_separator = ";"
    for index, words in enumerate(normalized):
        should_run = preceding_separator == ";"
        if preceding_separator == "&&":
            should_run = previous_status is True
        elif preceding_separator == "||":
            should_run = previous_status is False
        if not should_run:
            preceding_separator = separators[index] if index < len(separators) else ";"
            continue

        status: bool | None = None
        if words and not words[0].dynamic:
            name = words[0].value
            if name in {"true", ":"} and len(words) == 1:
                status = True
            elif name == "false" and len(words) == 1:
                status = False
            elif name in {"cd", "pushd"}:
                target = _literal_directory_argument(words, name)
                changed = _change_directory(current, target) if target is not None else None
                status = changed is not None if target is not None else None
                if changed is not None:
                    logical, resolved = changed
                    if name == "pushd":
                        stack.append(current)
                    current = logical
                    transitions.append(resolved)
            elif name == "popd" and len(words) == 1:
                status = bool(stack)
                if stack:
                    current = stack.pop()
                    transitions.append(current.resolve())
            elif name == "git":
                selected = _git_directory_operands(words, current)
                if selected is not None:
                    directories.extend(selected)
                status = None
        previous_status = status
        preceding_separator = separators[index] if index < len(separators) else ";"
    return _LiteralShellScopes(
        tuple(dict.fromkeys(transitions)),
        tuple(dict.fromkeys(directories)),
    )


def literal_shell_directory_transitions(
    command: str,
    start_directory: Path,
) -> tuple[Path, ...]:
    """Return statically executed literal directory-transition targets.

    This intentionally does not claim to parse Bash completely. Dynamic targets,
    pipelines, background jobs, subshells, functions, and shell control structures
    are outside the supported subset.
    """

    return _literal_shell_scopes(command, start_directory).transitions


def literal_git_directory_scopes(
    command: str,
    start_directory: Path,
) -> tuple[Path, ...]:
    """Return literal directories selected by statically executed ``git -C``.

    Repeated ``-C`` operands resolve in Git order: the first relative to the
    shell directory and each later relative to the preceding Git directory.
    Selection is treated as directory-scoped work even when Git later fails.
    """

    return _literal_shell_scopes(command, start_directory).git_directories


def literal_shell_directory_scopes(
    command: str,
    start_directory: Path,
) -> tuple[Path, ...]:
    """Return all statically executed shell and Git exact-directory scopes."""

    scopes = _literal_shell_scopes(command, start_directory)
    return tuple(dict.fromkeys((*scopes.transitions, *scopes.git_directories)))


def _read_agents(directory: Path) -> tuple[Path, str, str] | None:
    candidate = directory / "AGENTS.md"
    descriptor: int | None = None
    try:
        path_metadata = os.lstat(candidate)
        if not stat.S_ISREG(path_metadata.st_mode):
            return None
        descriptor = os.open(
            candidate,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content_bytes = handle.read()
        content = content_bytes.decode("utf-8")
        if not content.strip():
            return None
        return candidate, hashlib.sha256(content_bytes).hexdigest(), content
    except (OSError, UnicodeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _state_key(record: str) -> tuple[str, str] | None:
    try:
        parsed = json.loads(record)
    except json.JSONDecodeError:
        parts = record.rstrip("\n").split("\t")
        return (parts[0], parts[1]) if len(parts) >= 2 else None
    if not isinstance(parsed, dict):
        return None
    path = parsed.get("path")
    digest = parsed.get("digest")
    if not isinstance(path, str) or not isinstance(digest, str):
        return None
    return path, digest


def _claim_unseen(
    state_path: Path,
    candidates: list[tuple[Path, str, str]],
    activation: str,
) -> list[tuple[Path, str, str]]:
    if not candidates:
        return []
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("a+", encoding="utf-8") as state:
        os.chmod(state_path, 0o600)
        fcntl.flock(state.fileno(), fcntl.LOCK_EX)
        state.seek(0)
        seen = {
            key
            for line in state
            if (key := _state_key(line)) is not None
        }
        unseen = [
            candidate
            for candidate in candidates
            if (str(candidate[0]), candidate[1]) not in seen
        ]
        if not unseen:
            return []
        records = "".join(
            f"{path}\t{digest}\t{activation}\n"
            for path, digest, _content in unseen
        )
        state.seek(0, os.SEEK_END)
        state.write(records)
        state.flush()
        os.fsync(state.fileno())
        return unseen


def managed_context_activation(
    context: dict[str, Any],
    state_path: Path,
    directories: list[Path] | tuple[Path, ...],
    *,
    activation: str,
) -> ManagedContextActivation:
    roots = _managed_roots(context)
    candidates: list[tuple[Path, str, str]] = []
    candidate_keys: set[tuple[str, str]] = set()
    for raw_directory in dict.fromkeys(directories):
        try:
            directory = raw_directory.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not directory.is_dir():
            continue
        if not any(directory == root or root in directory.parents for root in roots):
            continue
        if ".git" in directory.parts:
            continue
        loaded = _read_agents(directory)
        if loaded is None:
            continue
        path, digest, content = loaded
        key = str(path), digest
        if key in candidate_keys:
            continue
        candidate_keys.add(key)
        candidates.append((path, digest, content))
    unseen = _claim_unseen(state_path, candidates, activation)
    return ManagedContextActivation(
        additional_context="\n\n".join(
            f"<CONTEXT>\n{content.rstrip()}\n</CONTEXT>"
            for _path, _digest, content in unseen
        ),
        paths=tuple(path for path, _digest, _content in unseen),
        activation=activation,
    )


def managed_context_for_directories(
    context: dict[str, Any],
    state_path: Path,
    directories: list[Path] | tuple[Path, ...],
    *,
    activation: str = "post_tool_fallback",
) -> str:
    return managed_context_activation(
        context,
        state_path,
        directories,
        activation=activation,
    ).additional_context


def _hook_base_directory(payload: dict[str, Any], root: Path) -> Path:
    value = payload.get("cwd")
    if not isinstance(value, str) or not value.strip():
        return root
    path = Path(value).expanduser()
    if not path.is_absolute():
        return root
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return root
    return resolved if resolved.is_dir() else root


def _tool_directories(
    payload: dict[str, Any],
    root: Path,
    *,
    include_tool_directory: bool,
) -> tuple[Path, ...]:
    base = _hook_base_directory(payload, root)
    try:
        directory = _tool_directory(payload, base)
    except (OSError, RuntimeError):
        directory = base
    directories = [directory] if include_tool_directory else []
    tool_input = payload.get("tool_input")
    arguments = tool_input if isinstance(tool_input, dict) else {}
    command = arguments.get("command")
    tool_name = str(payload.get("tool_name") or "").lower()
    if tool_name in _SHELL_TOOL_NAMES and isinstance(command, str):
        scopes = _literal_shell_scopes(command, directory)
        directories.extend(scopes.transitions)
        directories.extend(scopes.git_directories)
    return tuple(dict.fromkeys(directories))


def pre_tool_context_gate(
    context: dict[str, Any],
    payload: dict[str, Any],
    state_path: Path,
) -> ManagedContextActivation:
    roots = _managed_roots(context)
    if not roots:
        return ManagedContextActivation("", (), "pre_tool_gate")
    return managed_context_activation(
        context,
        state_path,
        _tool_directories(payload, roots[0], include_tool_directory=True),
        activation="pre_tool_gate",
    )


def post_tool_context_activation(
    context: dict[str, Any],
    payload: dict[str, Any],
    state_path: Path,
) -> ManagedContextActivation:
    roots = _managed_roots(context)
    if not roots:
        return ManagedContextActivation("", (), "post_tool_fallback")
    return managed_context_activation(
        context,
        state_path,
        _tool_directories(
            payload,
            roots[0],
            include_tool_directory=(
                payload.get("metalanguage_shell_transitions_only") is not True
            ),
        ),
        activation="post_tool_fallback",
    )


def directory_agents_observation(
    context: dict[str, Any],
    payload: dict[str, Any],
    state_path: Path,
) -> str:
    """Return newly activated exact-directory context for one hook event."""

    roots = _managed_roots(context)
    if not roots:
        return ""
    event_name = payload.get("hook_event_name")
    if event_name == "UserPromptSubmit":
        return managed_context_activation(
            context,
            state_path,
            [roots[0]],
            activation="initial",
        ).additional_context
    elif event_name == "PreToolUse":
        return pre_tool_context_gate(context, payload, state_path).additional_context
    elif event_name == "PostToolUse":
        return post_tool_context_activation(
            context,
            payload,
            state_path,
        ).additional_context
    else:
        return ""


def main() -> None:
    if len(sys.argv) != 2:
        return
    try:
        context_path = Path(sys.argv[1]).expanduser().resolve(strict=True)
        context = json.loads(context_path.read_text(encoding="utf-8"))
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(context, dict) or not isinstance(payload, dict):
            return
        event_name = payload.get("hook_event_name")
        observation = directory_agents_observation(
            context,
            payload,
            context_path.with_name("directory_agents_seen"),
        )
        if not observation:
            return
        hook_output: dict[str, Any] = {
            "hookEventName": event_name,
            "additionalContext": observation,
        }
        if event_name == "PreToolUse":
            hook_output.update(
                {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": NEUTRAL_DEFER_RESULT,
                }
            )
        print(
            json.dumps(
                {"hookSpecificOutput": hook_output},
                ensure_ascii=False,
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return


if __name__ == "__main__":
    main()
