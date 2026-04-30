"""Tests for audit logger."""

import json
import os
import time
from typing import Any

from release_flow.logging_setup import AuditLogger


class TestAuditLogger:
    def test_writes_jsonl_entries(self, tmp_path: Any) -> None:
        logger = AuditLogger(log_dir=tmp_path, repo_name="myrepo")
        logger.log_event(
            level="info", phase="CLEAN", action="detect_phase",
            extra={"version": "1.0.0-SNAPSHOT"},
        )
        logger.log_event(
            level="info", phase="CLEAN", action="git",
            extra={"cmd": "git status", "exit": 0},
        )
        logger.close()
        files = list(tmp_path.glob("myrepo/*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        e0 = json.loads(lines[0])
        assert e0["phase"] == "CLEAN"
        assert e0["version"] == "1.0.0-SNAPSHOT"
        assert "ts" in e0  # timestamp added automatically

    def test_rotation_purges_old_files(self, tmp_path: Any) -> None:
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        old = repo_dir / "2020-01-01-000000.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        # Set very old mtime
        old_time = time.time() - (40 * 86400)
        os.utime(old, (old_time, old_time))
        logger = AuditLogger(log_dir=tmp_path, repo_name="myrepo", retention_days=30)
        logger.purge_old()
        assert not old.exists()
