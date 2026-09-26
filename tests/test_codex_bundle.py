from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import codex_bundle


class CodexBundleTests(unittest.TestCase):
    def test_source_content_head_addition_and_deletion_invalidate_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "third_party" / "codex"
            crate = root / "crates" / "runner"
            codex.mkdir(parents=True)
            crate.mkdir(parents=True)
            source = codex / "lib.rs"
            source.write_bytes(b"before")
            runner_source = crate / "main.rs"
            runner_source.write_bytes(b"runner")
            head = b"first-head\n"
            vendor_additions: list[bytes] = []

            def git(directory: Path, *args: str) -> bytes:
                if args[0] == "rev-parse":
                    return head
                if directory == codex:
                    names = vendor_additions if "--others" in args else [b"lib.rs"]
                    return b"\0".join(names) + b"\0"
                if "--others" in args:
                    return b""
                return b"crates/runner/main.rs\0"

            def fingerprint() -> dict[str, str]:
                return codex_bundle.source_fingerprint(root, codex, crate, root / "target")

            with patch.object(codex_bundle, "_git", side_effect=git):
                original = fingerprint()
                times = source.stat()
                source.write_bytes(b"edited")
                os.utime(source, ns=(times.st_atime_ns, times.st_mtime_ns))
                self.assertNotEqual(fingerprint(), original)
                source.write_bytes(b"before")
                self.assertEqual(fingerprint(), original)
                head = b"second-head\n"
                self.assertNotEqual(fingerprint(), original)
                head = b"first-head\n"
                added = codex / "new.rs"
                added.write_bytes(b"new input")
                vendor_additions.append(b"new.rs")
                self.assertNotEqual(fingerprint(), original)
                vendor_additions.pop()
                source.unlink()
                self.assertNotEqual(fingerprint(), original)
                source.write_bytes(b"before")
                runner_source.write_bytes(b"changed runner")
                self.assertNotEqual(fingerprint(), original)
                runner_source.write_bytes(b"runner")
                local_config = codex / ".cargo" / "config.toml"
                local_config.parent.mkdir()
                local_config.write_text('[build]\nrustflags = ["--cfg", "local"]\n')
                self.assertNotEqual(fingerprint(), original)

    def test_configured_build_outputs_are_not_source_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "lib.rs"
            source.write_bytes(b"source")
            target = root / "custom-output"
            target.mkdir()
            artifact = target / "runner"
            artifact.write_bytes(b"old")
            paths = {source, artifact}
            original = codex_bundle._source_digest(root, paths, target)
            artifact.write_bytes(b"new build product")
            self.assertEqual(codex_bundle._source_digest(root, paths, target), original)

    def test_manifest_binds_both_artifacts_sources_and_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner, host = root / "runner", root / "host"
            for binary in (runner, host):
                binary.write_bytes(b"original")
                binary.chmod(0o755)
            sources = {"codex_head": "first", "codex": "contents", "runner": "wrapper"}
            with self.assertRaisesRegex(RuntimeError, "--codex-build-runner"):
                codex_bundle.validate_manifest(runner, host, sources, release=False)
            codex_bundle.write_manifest(runner, host, sources, release=False)
            codex_bundle.validate_manifest(runner, host, sources, release=False)
            with self.assertRaisesRegex(RuntimeError, "--codex-build-runner"):
                codex_bundle.validate_manifest(runner, host, {**sources, "codex": "dirty"}, release=False)
            with self.assertRaisesRegex(RuntimeError, "--codex-build-runner"):
                codex_bundle.validate_manifest(runner, host, sources, release=True)
            for binary in (runner, host):
                with self.subTest(binary=binary.name):
                    codex_bundle.write_manifest(runner, host, sources, release=False)
                    previous = binary.stat()
                    replacement = root / "replacement"
                    replacement.write_bytes(b"replaced")
                    replacement.chmod(0o755)
                    os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
                    os.replace(replacement, binary)
                    with self.assertRaisesRegex(RuntimeError, "--codex-build-runner"):
                        codex_bundle.validate_manifest(runner, host, sources, release=False)
            codex_bundle.write_manifest(runner, host, sources, release=False)
            host.unlink()
            with self.assertRaisesRegex(RuntimeError, "--codex-build-runner"):
                codex_bundle.validate_manifest(runner, host, sources, release=False)

    def test_corrupt_or_obsolete_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner, host = Path(temporary) / "runner", Path(temporary) / "host"
            for binary in (runner, host):
                binary.write_bytes(b"binary")
                binary.chmod(0o755)
            for contents in ("not json", json.dumps({"schema": 0}), "[]"):
                with self.subTest(contents=contents):
                    codex_bundle.manifest_path(runner).write_text(contents, encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, "--codex-build-runner"):
                        codex_bundle.validate_manifest(runner, host, {}, release=False)


if __name__ == "__main__":
    unittest.main()
