"""Audit logger: writes JSONL events per run + rich console for user output."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO


class AuditLogger:
    """One-file-per-run JSONL audit log under <log_dir>/<repo_name>/."""

    def __init__(
        self,
        log_dir: Path,
        repo_name: str,
        retention_days: int = 30,
    ):
        self.log_dir = Path(log_dir).expanduser()
        self.repo_dir = self.log_dir / repo_name
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        ts = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
        self.file_path = self.repo_dir / f"{ts}.jsonl"
        self._fp: TextIO = self.file_path.open("a", encoding="utf-8")

    def log_event(
        self,
        level: str,
        phase: str,
        action: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": level,
            "phase": phase,
            "action": action,
        }
        if extra:
            record.update(extra)
        self._fp.write(json.dumps(record) + "\n")
        self._fp.flush()

    def close(self) -> None:
        if self._fp and not self._fp.closed:
            self._fp.close()

    def purge_old(self) -> None:
        """Delete files older than retention_days from this repo's log dir."""
        cutoff = time.time() - (self.retention_days * 86400)
        for f in self.repo_dir.glob("*.jsonl"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
