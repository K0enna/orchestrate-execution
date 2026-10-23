#!/usr/bin/env python3
"""Validate terminal receipts and claim local handling once; no transport or executor."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID

MAX_RECEIPT_BYTES = 128 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ReceiptError(Exception):
    def __init__(self, reason, recovery=False):
        self.reason = reason
        self.recovery = recovery
        super().__init__(reason)


def _uuid(value):
    if not isinstance(value, str):
        raise ReceiptError("invalid_uuid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ReceiptError("invalid_uuid") from None
    if str(parsed) != value.lower():
        raise ReceiptError("invalid_uuid")
    return str(parsed)


def _absolute(value):
    if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
        raise ReceiptError("absolute_path_required")
    return Path(value).resolve()


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ReceiptError("invalid_fields")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptError("duplicate_json_key")
        result[key] = value
    return result


def _read_json(path, limit):
    if not path.is_file():
        raise ReceiptError("missing_or_nonfile_json")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ReceiptError("json_too_large")
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ReceiptError("invalid_json")))
    except (UnicodeError, ValueError, RecursionError):
        raise ReceiptError("invalid_json") from None
    return parsed, hashlib.sha256(raw).hexdigest()


def hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_fields(data, run_id, parent_thread, root):
    _keys(data, "version run_id parent_thread_id outcome summary artifacts checks")
    if type(data["version"]) is not int or data["version"] != 1:
        raise ReceiptError("unsupported_version")
    if _uuid(data["run_id"]) != run_id or _uuid(data["parent_thread_id"]) != parent_thread:
        raise ReceiptError("wrong_run_or_parent")
    if data["outcome"] not in ("completed", "blocked", "failed"):
        raise ReceiptError("unsupported_outcome")
    if not isinstance(data["summary"], str) or not data["summary"].strip() or len(data["summary"]) > 2000:
        raise ReceiptError("invalid_summary")
    if not isinstance(data["artifacts"], list) or not isinstance(data["checks"], list):
        raise ReceiptError("invalid_proof_lists")
    seen = set()
    for artifact in data["artifacts"]:
        _keys(artifact, "path sha256")
        path = _absolute(artifact["path"])
        if not path.is_relative_to(root):
            raise ReceiptError("artifact_outside_root")
        if path in seen:
            raise ReceiptError("duplicate_artifact")
        seen.add(path)
        if not path.is_file():
            raise ReceiptError("missing_or_nonfile_artifact")
        if not isinstance(artifact["sha256"], str) or not SHA256.fullmatch(artifact["sha256"]):
            raise ReceiptError("invalid_artifact_hash")
        if hash_file(path) != artifact["sha256"]:
            raise ReceiptError("stale_artifact")
    for check in data["checks"]:
        _keys(check, "name result")
        if not isinstance(check["name"], str) or not check["name"].strip() or len(check["name"]) > 2000:
            raise ReceiptError("invalid_check_name")
        if check["result"] not in ("pass", "fail", "not_run"):
            raise ReceiptError("invalid_check_result")
    if data["outcome"] == "completed" and (not data["artifacts"] or not data["checks"] or
                                            any(c["result"] != "pass" for c in data["checks"])):
        raise ReceiptError("completion_proof_required")


def validate_receipt(receipt, run_id, parent_thread, artifact_root):
    run_id, parent_thread = _uuid(run_id), _uuid(parent_thread)
    root = _absolute(artifact_root)
    if not root.is_dir():
        raise ReceiptError("artifact_root_missing")
    data, digest = _read_json(_absolute(receipt), MAX_RECEIPT_BYTES)
    _validate_fields(data, run_id, parent_thread, root)
    return data, digest


def _new_receipt_path(receipt, root):
    if not isinstance(receipt, (str, Path)) or not Path(receipt).is_absolute():
        raise ReceiptError("absolute_path_required")
    candidate = Path(receipt)
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError:
        raise ReceiptError("receipt_parent_missing") from None
    if not parent.is_dir():
        raise ReceiptError("receipt_parent_missing")
    resolved = parent / candidate.name
    if not resolved.is_relative_to(root):
        raise ReceiptError("receipt_outside_root")
    if candidate.exists() or candidate.is_symlink() or resolved.exists() or resolved.is_symlink():
        raise ReceiptError("receipt_exists")
    return resolved


def write_receipt(receipt, run_id, parent_thread, artifact_root, outcome, summary,
                  artifacts=None, checks=None):
    run_id, parent_thread = _uuid(run_id), _uuid(parent_thread)
    root = _absolute(artifact_root)
    if not root.is_dir():
        raise ReceiptError("artifact_root_missing")
    receipt_path = _new_receipt_path(receipt, root)
    artifact_paths = [] if artifacts is None else artifacts
    check_values = [] if checks is None else checks
    if not isinstance(artifact_paths, list) or not isinstance(check_values, list):
        raise ReceiptError("invalid_proof_lists")
    entries = []
    for value in artifact_paths:
        path = _absolute(value)
        if not path.is_relative_to(root):
            raise ReceiptError("artifact_outside_root")
        if not path.is_file():
            raise ReceiptError("missing_or_nonfile_artifact")
        entries.append({"path": str(path), "sha256": hash_file(path)})
    data = {
        "version": 1,
        "run_id": run_id,
        "parent_thread_id": parent_thread,
        "outcome": outcome,
        "summary": summary,
        "artifacts": entries,
        "checks": check_values,
    }
    _validate_fields(data, run_id, parent_thread, root)
    raw = (json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ReceiptError("json_too_large")
    try:
        fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ReceiptError("receipt_exists") from None
    except OSError:
        raise ReceiptError("receipt_write_failed") from None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise ReceiptError("receipt_write_failed", recovery=True) from None
    return {
        "status": "written",
        "path": str(receipt_path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "outcome": outcome,
        "artifact_count": len(entries),
        "check_counts": {
            result: sum(1 for check in check_values if check["result"] == result)
            for result in ("pass", "fail", "not_run")
        },
    }


def _marker(state_dir, run_id):
    directory = _absolute(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (run_id + ".json")


def _existing(path, run_id, parent_thread):
    try:
        data, _ = _read_json(path, 4096)
        _keys(data, "version run_id parent_thread_id status receipt_sha256")
        if type(data["version"]) is not int or data["version"] != 1:
            raise ReceiptError("invalid_marker")
        if data["run_id"] != run_id or data["parent_thread_id"] != parent_thread:
            raise ReceiptError("invalid_marker")
        if data["status"] == "claimed":
            if not isinstance(data["receipt_sha256"], str) or not SHA256.fullmatch(data["receipt_sha256"]):
                raise ReceiptError("invalid_marker")
        elif data["status"] != "canceled" or data["receipt_sha256"] is not None:
            raise ReceiptError("invalid_marker")
        return data
    except (ReceiptError, OSError):
        raise ReceiptError("marker_recovery_needed", recovery=True) from None


def _create(path, data):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    # Preserve an incomplete marker on any write failure: never retry acceptance silently.
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise ReceiptError("marker_recovery_needed", recovery=True) from None
    return True


def claim(receipt, state_dir, run_id, parent_thread, artifact_root):
    run_id, parent_thread = _uuid(run_id), _uuid(parent_thread)
    data, digest = validate_receipt(receipt, run_id, parent_thread, artifact_root)
    marker = _marker(state_dir, run_id)
    value = {"version": 1, "run_id": run_id, "parent_thread_id": parent_thread,
             "status": "claimed", "receipt_sha256": digest}
    if _create(marker, value):
        status = "claimed"
    else:
        existing = _existing(marker, run_id, parent_thread)
        if existing["status"] == "canceled":
            raise ReceiptError("run_canceled")
        if existing["receipt_sha256"] != digest:
            raise ReceiptError("conflicting_receipt")
        status = "duplicate"
    return {"status": status, "run_id": run_id, "outcome": data["outcome"], "receipt_sha256": digest}


def cancel(state_dir, run_id, parent_thread):
    run_id, parent_thread = _uuid(run_id), _uuid(parent_thread)
    marker = _marker(state_dir, run_id)
    value = {"version": 1, "run_id": run_id, "parent_thread_id": parent_thread,
             "status": "canceled", "receipt_sha256": None}
    if _create(marker, value):
        status = "canceled"
    else:
        existing = _existing(marker, run_id, parent_thread)
        status = "already_canceled" if existing["status"] == "canceled" else "already_claimed"
    return {"status": status, "run_id": run_id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    write_command = commands.add_parser("write")
    for flag in ("receipt", "run-id", "parent-thread", "artifact-root", "outcome", "summary"):
        write_command.add_argument("--" + flag, required=True)
    write_command.add_argument("--artifact", action="append", default=[])
    for flag in ("check-pass", "check-fail", "check-not-run"):
        write_command.add_argument("--" + flag, action="append", default=[])
    for name in ("claim", "cancel"):
        command = commands.add_parser(name)
        for flag in ("state-dir", "run-id", "parent-thread"):
            command.add_argument("--" + flag, required=True)
        if name == "claim":
            command.add_argument("--receipt", required=True)
            command.add_argument("--artifact-root", required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "write":
            checks = []
            for flag, result_value in (
                ("check-pass", "pass"),
                ("check-fail", "fail"),
                ("check-not-run", "not_run"),
            ):
                checks.extend(
                    {"name": name, "result": result_value}
                    for name in args.pop(flag.replace("-", "_"))
                )
            result = write_receipt(
                receipt=args.pop("receipt"),
                run_id=args.pop("run_id"),
                parent_thread=args.pop("parent_thread"),
                artifact_root=args.pop("artifact_root"),
                outcome=args.pop("outcome"),
                summary=args.pop("summary"),
                artifacts=args.pop("artifact"),
                checks=checks,
            )
        else:
            result = (claim if command == "claim" else cancel)(**args)
    except ReceiptError as error:
        print(json.dumps({"status": "recovery_needed" if error.recovery else "rejected", "reason": error.reason}))
        return 3 if error.recovery else 2
    except (OSError, ValueError):
        print(json.dumps({"status": "rejected", "reason": "filesystem_error"}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
