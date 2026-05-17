#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/.uv-cache}"

PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
INSTALL_LEGACY_REWARD=0
VERIFY_ONLY=0

usage() {
    cat <<'EOF'
Usage: ./setup.sh [--with-legacy-reward] [--verify-only]

Creates a repo-local .venv with uv, installs the packages needed for the
SuperGPQA rollout loop, and verifies that the runner imports correctly.

Options:
  --with-legacy-reward  Also install optional math/code reward dependencies.
  --verify-only         Do not install anything; only run import checks.

Environment:
  PYTHON_VERSION=3.12   Python version uv should install/use.
EOF
}

for arg in "$@"; do
    case "$arg" in
        --with-legacy-reward)
            INSTALL_LEGACY_REWARD=1
            ;;
        --verify-only)
            VERIFY_ONLY=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        return
    fi

    echo "uv not found; installing uv into the user account..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "Install curl or wget first, then rerun ./setup.sh." >&2
        exit 1
    fi

    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        echo "uv install finished, but uv is not on PATH." >&2
        echo "Add \$HOME/.local/bin or \$HOME/.cargo/bin to PATH, then rerun ./setup.sh." >&2
        exit 1
    fi
}

run_verify() {
    local uv_run_args=()
    if [ "$VERIFY_ONLY" -eq 1 ]; then
        uv_run_args=(--no-sync)
    fi

    uv run "${uv_run_args[@]}" python -B main_loop.py --help >/dev/null
    uv run "${uv_run_args[@]}" python - <<'PY'
from utils.reward import compute_score_supergpqa

row = {
    "answer_letter": "C",
    "answer": "gamma ray",
    "options": ["alpha", "beta", "gamma ray", "delta"],
}
assert compute_score_supergpqa("Answer: C", "C", row) == 1.0
assert compute_score_supergpqa("Answer: gamma ray", "C", row) == 1.0
assert compute_score_supergpqa("Answer: A", "C", row) == 0.0
print("setup verification passed")
PY
}

if [ "$VERIFY_ONLY" -eq 1 ]; then
    if ! command -v uv >/dev/null 2>&1; then
        echo "uv is not on PATH; run ./setup.sh first to install and sync the environment." >&2
        exit 1
    fi
else
    ensure_uv
fi

if [ "$VERIFY_ONLY" -eq 0 ]; then
    uv python install "$PYTHON_VERSION"
    uv sync --python "$PYTHON_VERSION"
    if [ "$INSTALL_LEGACY_REWARD" -eq 1 ]; then
        uv pip install \
            "aiohttp>=3.9" \
            "latex2sympy2-extended>=1.10" \
            "math-verify>=0.7" \
            "openai>=1.0" \
            "pandas>=2.0" \
            "transformers>=4.40"
        cat <<'EOF'

Note: AIME/GPQA legacy scorers also import bench_eval from Evalchemy.
Evalchemy's current Git package metadata contains a relative file dependency
that uv cannot resolve directly from git, so it is not installed automatically.
The SuperGPQA rollout loop does not need Evalchemy.
EOF
    fi
fi

run_verify
