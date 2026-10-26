"""L7 版本存储：SQLite 元数据 + 内容寻址工件文件。

正文只存内容寻址文件（``<artifact_root>/<content_hash>.md``，0600），SQLite
只存哈希与引用——与 boss-watch-agent 的 `resume_versions` 纪律一致：正文不进
SQLite 行。

幂等：同内容哈希的重复落盘返回已有版本（``reused=True``），不插新行。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from ..domain.contracts import ResumeVersion, TailorLineage

__all__ = ["ResumeVersionStore", "SaveResult"]


@dataclass(frozen=True)
class SaveResult:
    """落盘结果。"""

    version: ResumeVersion
    reused: bool


class ResumeVersionStore:
    """简历版本目录：内容寻址工件 + SQLite 元数据 + 血缘。"""

    def __init__(self, db_path: str, artifact_root: str) -> None:
        self._artifact_root = Path(artifact_root)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        # ThreadingHTTPServer 每个请求在新线程，而连接在主线程创建：必须
        # check_same_thread=False，并用锁串行化对共享连接的访问。
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()  # 可重入：save_version 内部会调 get_by_content_hash
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            PRAGMA busy_timeout = 5000;
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            CREATE TABLE IF NOT EXISTS resume_versions (
                resume_version_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                local_artifact_ref TEXT NOT NULL UNIQUE,
                content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash) = 64),
                media_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL CHECK (byte_size > 0),
                created_at TEXT NOT NULL,
                supersedes_resume_version_id TEXT
            );
            CREATE TABLE IF NOT EXISTS resume_tailor_lineage (
                lineage_id TEXT PRIMARY KEY,
                new_resume_version_id TEXT NOT NULL,
                base_resume_version_id TEXT,
                tailor_id TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                jd_content_hash TEXT NOT NULL,
                mode TEXT NOT NULL,
                model_ref TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def save_version(self, version: ResumeVersion, content_bytes: bytes) -> SaveResult:
        """幂等落盘一个版本。

        Args:
            version: 版本元数据。
            content_bytes: 渲染后的正文字节（内容寻址工件）。

        Returns:
            SaveResult；同内容已存在时 ``reused=True``。
        """
        existing = self.get_by_content_hash(version.content_hash)
        if existing is not None:
            return SaveResult(existing, True)

        with self._lock:
            self._write_artifact(version.content_hash, content_bytes)
            self._conn.execute(
                """
                INSERT INTO resume_versions (
                    resume_version_id, display_name, local_artifact_ref, content_hash,
                    media_type, byte_size, created_at, supersedes_resume_version_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version.resume_version_id,
                    version.display_name,
                    version.local_artifact_ref,
                    version.content_hash,
                    version.media_type,
                    version.byte_size,
                    version.created_at,
                    version.supersedes_resume_version_id,
                ),
            )
            self._conn.commit()
        return SaveResult(version, False)

    def _write_artifact(self, content_hash: str, content_bytes: bytes) -> None:
        """内容寻址写入工件文件（排他 + 0600），同内容幂等。"""
        path = self._artifact_root / f"{content_hash}.md"
        if path.exists():
            if path.read_bytes() == content_bytes:
                return
            raise FileExistsError("resume_artifact_hash_conflict")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, content_bytes)
        finally:
            os.close(fd)

    def get(self, resume_version_id: str) -> ResumeVersion | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM resume_versions WHERE resume_version_id = ?",
                (resume_version_id,),
            ).fetchone()
        return self._row_to_version(row)

    def get_by_content_hash(self, content_hash: str) -> ResumeVersion | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM resume_versions WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
        return self._row_to_version(row)

    def list_versions(self, limit: int = 50) -> list[ResumeVersion]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM resume_versions ORDER BY created_at DESC, resume_version_id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_version(row) for row in rows]

    def save_lineage(self, lineage: TailorLineage) -> None:
        """写血缘（同 lineage_id 幂等）。"""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO resume_tailor_lineage (
                    lineage_id, new_resume_version_id, base_resume_version_id, tailor_id,
                    plan_id, jd_content_hash, mode, model_ref, strategy_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lineage.lineage_id,
                    lineage.new_resume_version_id,
                    lineage.base_resume_version_id,
                    lineage.tailor_id,
                    lineage.plan_id,
                    lineage.jd_content_hash,
                    lineage.mode,
                    lineage.model_ref,
                    lineage.strategy_version,
                    lineage.created_at,
                ),
            )
            self._conn.commit()

    def get_lineage(self, lineage_id: str) -> TailorLineage | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM resume_tailor_lineage WHERE lineage_id = ?",
                (lineage_id,),
            ).fetchone()
        if row is None:
            return None
        return TailorLineage(
            lineage_id=row["lineage_id"],
            new_resume_version_id=row["new_resume_version_id"],
            base_resume_version_id=row["base_resume_version_id"],
            tailor_id=row["tailor_id"],
            plan_id=row["plan_id"],
            jd_content_hash=row["jd_content_hash"],
            mode=row["mode"],
            model_ref=row["model_ref"],
            strategy_version=row["strategy_version"],
            created_at=row["created_at"],
        )

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM resume_versions").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_version(row: sqlite3.Row | None) -> ResumeVersion | None:
        if row is None:
            return None
        return ResumeVersion(
            resume_version_id=row["resume_version_id"],
            display_name=row["display_name"],
            local_artifact_ref=row["local_artifact_ref"],
            content_hash=row["content_hash"],
            media_type=row["media_type"],
            byte_size=row["byte_size"],
            created_at=row["created_at"],
            supersedes_resume_version_id=row["supersedes_resume_version_id"],
        )
