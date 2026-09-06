import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from mediaflow.infrastructure.persistence import (
    DEFAULT_MIGRATIONS,
    Migration,
    MigrationError,
    MigrationRunner,
)


def test_fresh_database_applies_ordered_migrations_idempotently(tmp_path: Path) -> None:
    database_path = tmp_path / "mediaflow.db"
    runner = MigrationRunner(database_path)

    runner.migrate()
    runner.migrate()

    with closing(sqlite3.connect(database_path)) as connection, connection:
        applied = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert applied == [(migration.version, migration.name) for migration in DEFAULT_MIGRATIONS]
    assert {"download_tasks", "download_attempts", "task_outputs"} <= tables


def test_database_can_advance_from_each_released_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "mediaflow.db"

    MigrationRunner(database_path, migrations=DEFAULT_MIGRATIONS[:1]).migrate()
    MigrationRunner(database_path).migrate()

    with closing(sqlite3.connect(database_path)) as connection, connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        outputs_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'task_outputs'"
        ).fetchone()
    assert versions == [(1,), (2,)]
    assert outputs_table == ("task_outputs",)


def test_failed_migration_rolls_back_schema_and_version_record(tmp_path: Path) -> None:
    database_path = tmp_path / "mediaflow.db"
    failing = Migration(
        version=1,
        name="fails_atomically",
        statements=(
            "CREATE TABLE must_rollback (value TEXT) STRICT",
            "INSERT INTO table_that_does_not_exist(value) VALUES ('failure')",
        ),
    )

    with pytest.raises(sqlite3.OperationalError):
        MigrationRunner(database_path, migrations=(failing,)).migrate()

    with closing(sqlite3.connect(database_path)) as connection, connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'must_rollback'"
        ).fetchone()
        applied = connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert table is None
    assert applied == []


def test_applied_version_with_changed_identity_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "mediaflow.db"
    MigrationRunner(database_path, migrations=DEFAULT_MIGRATIONS[:1]).migrate()
    changed = Migration(version=1, name="renamed", statements=("SELECT 1",))

    with pytest.raises(MigrationError):
        MigrationRunner(database_path, migrations=(changed,)).migrate()


def test_applied_migration_with_changed_statements_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "mediaflow.db"
    MigrationRunner(database_path, migrations=DEFAULT_MIGRATIONS[:1]).migrate()
    changed = Migration(
        version=1,
        name=DEFAULT_MIGRATIONS[0].name,
        statements=("SELECT 1",),
    )

    with pytest.raises(MigrationError):
        MigrationRunner(database_path, migrations=(changed,)).migrate()


def test_database_with_unknown_newer_version_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "mediaflow.db"
    MigrationRunner(database_path).migrate()
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO schema_migrations(version, name, checksum, applied_at_utc)
            VALUES (3, 'future_schema', 'unknown', '2026-09-06T00:00:00Z')
            """
        )

    with pytest.raises(MigrationError):
        MigrationRunner(database_path).migrate()


def test_database_with_migration_gap_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "mediaflow.db"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at_utc TEXT NOT NULL
            ) STRICT
            """
        )
        connection.execute(
            """
            INSERT INTO schema_migrations(version, name, checksum, applied_at_utc)
            VALUES (2, 'create_task_outputs', 'unknown', '2026-09-06T00:00:00Z')
            """
        )

    with pytest.raises(MigrationError):
        MigrationRunner(database_path).migrate()


@pytest.mark.parametrize(
    "migrations",
    [
        (
            Migration(version=2, name="second", statements=("SELECT 1",)),
            Migration(version=1, name="first", statements=("SELECT 1",)),
        ),
        (
            Migration(version=1, name="first", statements=("SELECT 1",)),
            Migration(version=1, name="duplicate", statements=("SELECT 1",)),
        ),
        (Migration(version=2, name="gap", statements=("SELECT 1",)),),
    ],
)
def test_runner_rejects_unordered_or_duplicate_versions(
    migrations: tuple[Migration, ...],
) -> None:
    with pytest.raises(ValueError):
        MigrationRunner(database_path=Path(__file__), migrations=migrations)
