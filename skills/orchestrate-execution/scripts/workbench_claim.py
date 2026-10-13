#!/usr/bin/env python3
"""Reserve one existing ChatGPT conversation for a local Codex task."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from uuid import UUID


DATABASE_NAME = "claims.sqlite3"
SCHEMA_VERSION = 1
SQLITE_TIMEOUT_SECONDS = 5.0
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
RESERVATION_COLUMNS = (
    ("chat_id", "TEXT", 1, 1),
    ("project_id", "TEXT", 1, 0),
    ("owner_id", "TEXT", 1, 0),
    ("request_id", "TEXT", 1, 0),
    ("claim_id", "TEXT", 1, 0),
    ("created_at", "TEXT", 1, 0),
)


class ClaimError(Exception):
    def __init__(self, reason, status="rejected", exit_code=2):
        self.reason = reason
        self.status = status
        self.exit_code = exit_code
        super().__init__(reason)


class StorageError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _uuid(value):
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise ClaimError("invalid_uuid")
    try:
        return str(UUID(value))
    except ValueError:
        raise ClaimError("invalid_uuid") from None


def _project_id(value):
    if (not isinstance(value, str) or not value or len(value) > 128 or
            not value.strip() or any(ord(char) < 32 or 127 <= ord(char) <= 159 or
                                      char in "\u2028\u2029" for char in value)):
        raise ClaimError("invalid_project_id")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ClaimError("invalid_project_id") from None
    return value


def _request_id(value):
    if not isinstance(value, str) or not REQUEST_ID_RE.fullmatch(value):
        raise ClaimError("invalid_request_id")
    return value


def _state_dir(value=None):
    if value is None:
        codex_home = os.environ.get("CODEX_HOME")
        base = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
        directory = base / "state" / "chatgpt-workbench"
    else:
        directory = Path(value).expanduser()
    if not directory.is_absolute():
        directory = Path.cwd() / directory
    return directory


def _database_path(state_dir):
    return _state_dir(state_dir) / DATABASE_NAME


def _storage_error(error):
    code = getattr(error, "sqlite_errorcode", None)
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return StorageError("storage_busy")
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        return StorageError("storage_corrupt")
    message = str(error).lower()
    if "database is locked" in message or "database table is locked" in message or "database is busy" in message:
        return StorageError("storage_busy")
    if any(fragment in message for fragment in ("not a database", "malformed", "no such table", "no such column")):
        return StorageError("storage_corrupt")
    return StorageError("storage_unavailable")


def _uri(path, mode):
    try:
        return path.resolve().as_uri() + "?mode=" + mode
    except (OSError, RuntimeError):
        raise StorageError("storage_unavailable") from None


def _connect(path, mode):
    if mode == "create":
        return sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS, isolation_level=None)
    return sqlite3.connect(_uri(path, mode), uri=True, timeout=SQLITE_TIMEOUT_SECONDS,
                           isolation_level=None)


def _table_columns(connection):
    return tuple((row[1], row[2].upper(), row[3], row[5])
                 for row in connection.execute("PRAGMA table_info(reservations)"))


def _verify_schema(connection):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION or _table_columns(connection) != RESERVATION_COLUMNS:
        raise StorageError("storage_corrupt")


def _initialize_schema(connection):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if tables:
            raise StorageError("storage_corrupt")
        connection.execute(
            "CREATE TABLE reservations ("
            "chat_id TEXT PRIMARY KEY NOT NULL, "
            "project_id TEXT NOT NULL, "
            "owner_id TEXT NOT NULL, "
            "request_id TEXT NOT NULL, "
            "claim_id TEXT NOT NULL, "
            "created_at TEXT NOT NULL)"
        )
        connection.execute("PRAGMA user_version = 1")
    _verify_schema(connection)


def _reservation(row):
    return {
        "chat_id": row[0],
        "project_id": row[1],
        "owner_id": row[2],
        "request_id": row[3],
        "claim_id": row[4],
        "created_at": row[5],
    }


def _fetch_reservation(connection, chat_id):
    return connection.execute(
        "SELECT chat_id, project_id, owner_id, request_id, claim_id, created_at "
        "FROM reservations WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def acquire(chat_id, project_id, owner_id, request_id, claim_id, state_dir=None):
    chat_id = _uuid(chat_id)
    project_id = _project_id(project_id)
    owner_id = _uuid(owner_id)
    request_id = _request_id(request_id)
    claim_id = _uuid(claim_id)
    path = _database_path(state_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = _connect(path, "create")
        try:
            connection.execute("BEGIN IMMEDIATE")
            _initialize_schema(connection)
            created_at = _now()
            cursor = connection.execute(
                "INSERT INTO reservations (chat_id, project_id, owner_id, request_id, claim_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(chat_id) DO NOTHING",
                (chat_id, project_id, owner_id, request_id, claim_id, created_at),
            )
            if cursor.rowcount == 0:
                row = _fetch_reservation(connection, chat_id)
                connection.commit()
                return {"status": "busy", "reservation": _reservation(row)}
            connection.commit()
            return {"status": "reserved", **{
                "chat_id": chat_id,
                "project_id": project_id,
                "owner_id": owner_id,
                "request_id": request_id,
                "claim_id": claim_id,
                "created_at": created_at,
            }}
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as error:
        raise _storage_error(error) from None


def status(chat_id, state_dir=None):
    chat_id = _uuid(chat_id)
    path = _database_path(state_dir)
    try:
        path.lstat()
    except FileNotFoundError:
        return {"status": "free", "chat_id": chat_id}
    except OSError as error:
        raise StorageError("storage_unavailable") from None
    try:
        connection = _connect(path, "ro")
        try:
            _verify_schema(connection)
            row = _fetch_reservation(connection, chat_id)
            return ({"status": "free", "chat_id": chat_id} if row is None else
                    {"status": "busy", "reservation": _reservation(row)})
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as error:
        raise _storage_error(error) from None


def release(chat_id, owner_id, request_id, claim_id, state_dir=None):
    chat_id = _uuid(chat_id)
    owner_id = _uuid(owner_id)
    request_id = _request_id(request_id)
    claim_id = _uuid(claim_id)
    path = _database_path(state_dir)
    try:
        path.lstat()
    except FileNotFoundError:
        raise ClaimError("reservation_mismatch", status="mismatch", exit_code=3) from None
    except OSError:
        raise StorageError("storage_unavailable") from None
    try:
        connection = _connect(path, "rw")
        try:
            connection.execute("BEGIN IMMEDIATE")
            _verify_schema(connection)
            row = _fetch_reservation(connection, chat_id)
            if (row is None or row[2] != owner_id or row[3] != request_id or row[4] != claim_id):
                connection.commit()
                raise ClaimError("reservation_mismatch", status="mismatch", exit_code=3)
            connection.execute(
                "DELETE FROM reservations WHERE chat_id = ? AND owner_id = ? AND request_id = ? AND claim_id = ?",
                (chat_id, owner_id, request_id, claim_id),
            )
            connection.commit()
            return {"status": "released", "chat_id": chat_id, "owner_id": owner_id,
                    "request_id": request_id, "claim_id": claim_id}
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
    except ClaimError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise _storage_error(error) from None


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    acquire_parser = commands.add_parser("acquire", help="reserve a conversation")
    acquire_parser.add_argument("--chat-id", required=True)
    acquire_parser.add_argument("--project-id", required=True)
    acquire_parser.add_argument("--owner-id", required=True)
    acquire_parser.add_argument("--request-id", required=True)
    acquire_parser.add_argument("--claim-id", required=True)
    acquire_parser.add_argument("--state-dir")

    status_parser = commands.add_parser("status", help="check the local reservation")
    status_parser.add_argument("--chat-id", required=True)
    status_parser.add_argument("--state-dir")

    release_parser = commands.add_parser("release", help="release the exact reservation")
    release_parser.add_argument("--chat-id", required=True)
    release_parser.add_argument("--owner-id", required=True)
    release_parser.add_argument("--request-id", required=True)
    release_parser.add_argument("--claim-id", required=True)
    release_parser.add_argument("--state-dir")

    return parser


def main(argv=None):
    args = vars(_parser().parse_args(argv))
    command = args.pop("command")
    try:
        if command == "acquire":
            result = acquire(**args)
            exit_code = 2 if result["status"] == "busy" else 0
        elif command == "status":
            result = status(**args)
            exit_code = 0
        else:
            result = release(**args)
            exit_code = 0
    except ClaimError as error:
        result = {"status": error.status, "reason": error.reason}
        exit_code = error.exit_code
    except StorageError as error:
        result = {"status": "error", "reason": error.reason}
        exit_code = 4
    except (OSError, RuntimeError, UnicodeError, sqlite3.Error):
        result = {"status": "error", "reason": "storage_unavailable"}
        exit_code = 4
    print(json.dumps(result, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
