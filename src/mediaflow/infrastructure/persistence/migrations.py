"""Ordered, atomic SQLite schema migrations."""

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


class MigrationError(RuntimeError):
    """The database schema cannot safely be migrated by this application."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "statements", tuple(self.statements))
        if self.version < 1:
            raise ValueError("Migration version must be positive")
        if not self.name or not self.name.strip():
            raise ValueError("Migration name must be non-empty")
        if not self.statements:
            raise ValueError("Migration must contain at least one statement")

    @property
    def checksum(self) -> str:
        content = "\0".join(statement.strip() for statement in self.statements)
        return sha256(content.encode("utf-8")).hexdigest()


DEFAULT_MIGRATIONS = (
    Migration(
        version=1,
        name="create_tasks_and_attempts",
        statements=(
            """
            CREATE TABLE download_tasks (
                task_id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                media_title TEXT NOT NULL,
                preset_kind TEXT NOT NULL CHECK (preset_kind IN ('video', 'audio')),
                preset_quality TEXT NOT NULL,
                preset_container TEXT NOT NULL,
                preset_fps INTEGER,
                output_directory TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE download_attempts (
                attempt_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES download_tasks(task_id) ON DELETE CASCADE,
                attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
                state TEXT NOT NULL CHECK (
                    state IN (
                        'queued', 'downloading', 'processing', 'paused',
                        'interrupted', 'completed', 'failed', 'cancelled'
                    )
                ),
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                finished_at_utc TEXT,
                failure_category TEXT,
                failure_code TEXT,
                failure_retryable INTEGER CHECK (failure_retryable IN (0, 1)),
                UNIQUE (task_id, attempt_number)
            ) STRICT
            """,
            "CREATE INDEX idx_download_attempts_task ON download_attempts(task_id, attempt_number)",
        ),
    ),
    Migration(
        version=2,
        name="create_task_outputs",
        statements=(
            """
            CREATE TABLE task_outputs (
                attempt_id TEXT PRIMARY KEY
                    REFERENCES download_attempts(attempt_id) ON DELETE CASCADE,
                output_path TEXT NOT NULL
            ) STRICT
            """,
        ),
    ),
)


class MigrationRunner:
    """Apply each pending migration once in its own SQLite transaction."""

    def __init__(
        self, database_path: Path, *, migrations: Sequence[Migration] = DEFAULT_MIGRATIONS
    ) -> None:
        self._database_path = database_path
        self._migrations = tuple(migrations)
        versions = tuple(migration.version for migration in self._migrations)
        if versions != tuple(range(1, len(versions) + 1)):
            raise ValueError("Migrations must be a contiguous sequence starting at version one")

    def migrate(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(_connect(self._database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at_utc TEXT NOT NULL
                ) STRICT
                """
            )
            applied = connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            known_prefix = tuple(
                (migration.version, migration.name, migration.checksum)
                for migration in self._migrations[: len(applied)]
            )
            if tuple(applied) != known_prefix:
                raise MigrationError(
                    "Database migration history is not a contiguous prefix known to this version"
                )

        for migration in self._migrations:
            self._apply(connection_path=self._database_path, migration=migration)

    @staticmethod
    def _apply(*, connection_path: Path, migration: Migration) -> None:
        connection = _connect(connection_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT name, checksum FROM schema_migrations WHERE version = ?",
                (migration.version,),
            ).fetchone()
            if row is not None:
                if row != (migration.name, migration.checksum):
                    raise MigrationError(
                        f"Migration {migration.version} differs from the applied migration"
                    )
                connection.commit()
                return
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO schema_migrations(version, name, checksum, applied_at_utc)
                VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (migration.version, migration.name, migration.checksum),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection
