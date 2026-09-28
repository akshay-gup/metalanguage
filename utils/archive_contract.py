"""Shared archive identity used by rollout setup and child progress records."""

from pathlib import Path


METALANGUAGE_VERSION = "3.9"
SHARED_ARCHIVES_MODE = "shared-concurrent"
SHARED_ARCHIVES_ROOT_NAME = "archives"
SHARED_ARCHIVES_WORKSPACE_PATH = "archives"
SHARED_ARCHIVES_CLEANUP_POLICY = "direct-child-git-head-v1"


def shared_archives_metadata(shared_archives_root: Path) -> dict[str, str]:
    return {
        "metalanguage_version": METALANGUAGE_VERSION,
        "archive_mode": SHARED_ARCHIVES_MODE,
        "shared_archives_root": str(shared_archives_root),
        "shared_archives_root_name": SHARED_ARCHIVES_ROOT_NAME,
        "shared_archives_workspace_path": SHARED_ARCHIVES_WORKSPACE_PATH,
        "archive_cleanup_policy": SHARED_ARCHIVES_CLEANUP_POLICY,
    }
