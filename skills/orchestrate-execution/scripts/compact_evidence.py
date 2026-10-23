#!/usr/bin/env python3
"""Explicit, bounded offline projections of native thread reads, command results and worker receipts.

Reads only the named JSON file. This is neither a transport interceptor nor a
secret scanner. Full evidence stays at its source; summaries are not acceptance.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024


class ProjectionError(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProjectionError("duplicate_json_key")
        result[key] = value
    return result


def _parse(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProjectionError("invalid_json")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProjectionError("invalid_json") from error


def project(source, kind):
    source = Path(source).resolve(strict=True)
    with source.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ProjectionError("input_too_large")
    value = _parse(raw)
    result = {"schema_version": 1, "kind": kind, "source": {"path": str(source),
              "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}, "status": "unknown",
              "failures": None, "unknowns": None, "omissions": {}}
    if kind == "receipt":
        if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1
                or value.get("outcome") not in {"completed", "blocked", "failed"}
                or not isinstance(value.get("checks"), list) or not isinstance(value.get("artifacts"), list)
                or not isinstance(value.get("summary"), str)):
            result["category"] = "unsupported_receipt_shape"
        else:
            checks = value["checks"]
            counts = {key: 0 for key in ("pass", "fail", "not_run", "unknown")}
            samples = []
            for check in checks:
                outcome = check.get("result") if isinstance(check, dict) else None
                key = outcome if isinstance(outcome, str) and outcome in counts else "unknown"
                counts[key] += 1
                if key != "pass" and len(samples) < 8:
                    name = check.get("name") if isinstance(check, dict) else None
                    samples.append({"result": key, "name": name[:160] if isinstance(name, str) else None})
            result.update(status=value["outcome"], run_id=_identity(value.get("run_id")),
                          parent_thread_id=_identity(value.get("parent_thread_id")),
                          final_answer=value["summary"][:1200], checks=counts,
                          failures=counts["fail"], unknowns=counts["unknown"] + counts["not_run"],
                          nonpassing_checks=samples, artifact_count=len(value["artifacts"]))
            result["omissions"] = {"summary_characters": max(0, len(value["summary"])-1200),
                "nonpassing_check_details": counts["fail"]+counts["unknown"]+counts["not_run"]-len(samples),
                "nonpassing_check_name_characters": 0,
                "artifact_details": len(value["artifacts"]), "passing_check_details": counts["pass"]}
    elif kind == "exec":
        # functions.exec_command / write_stdin return this object directly.
        # A session is pending, an exit code is terminal, and contradictory or
        # unfamiliar producer shapes cannot claim either state.
        fields = {"chunk_id", "wall_time_seconds", "exit_code", "original_token_count", "output", "session_id"}
        valid = isinstance(value, dict) and not set(value) - fields and isinstance(value.get("output"), str)
        if valid:
            exit_code, session_id = value.get("exit_code"), value.get("session_id")
            valid = ((exit_code is None or type(exit_code) is int)
                     and (session_id is None or type(session_id) is int and session_id > 0)
                     and ((exit_code is not None) != (session_id is not None)))
            if "chunk_id" in value:
                valid = valid and isinstance(value["chunk_id"], str)
            if "original_token_count" in value:
                valid = valid and type(value["original_token_count"]) is int and value["original_token_count"] >= 0
            if "wall_time_seconds" in value:
                elapsed = value["wall_time_seconds"]
                valid = valid and type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0
        if not valid:
            result["category"] = "unsupported_exec_shape"
        else:
            output = value["output"]
            result.update(status="running" if session_id is not None else "completed" if exit_code == 0 else "failed",
                          exit_code=exit_code, session_id=session_id, chunk_id=_identity(value.get("chunk_id")),
                          output=output[:1200], failures=int(exit_code is not None and exit_code != 0), unknowns=0)
            for key in ("wall_time_seconds", "original_token_count"):
                if key in value:
                    result[key] = value[key]
            result["omissions"] = {"output_characters": max(0, len(output)-1200),
                                   "chunk_id_characters": max(0, len(value.get("chunk_id", ""))-160)}
    elif kind == "thread":
        # Native reads can arrive as a structured result or as JSON text in the
        # MCP content wrapper. Follow only these known envelopes, with a small
        # depth bound so malformed nested content cannot recurse indefinitely.
        for _ in range(4):
            if not isinstance(value, dict):
                break
            if value.get("isError") is True:
                result["category"] = "thread_read_error"
                value = None
                break
            if "isError" in value and type(value["isError"]) is not bool:
                value = None
                break
            if "structuredContent" in value:
                value = value["structuredContent"] if isinstance(value["structuredContent"], dict) else None
                continue
            if "content" in value:
                content = value["content"]
                if (isinstance(content, list) and len(content) == 1
                        and isinstance(content[0], dict) and content[0].get("type") == "text"
                        and isinstance(content[0].get("text"), str)):
                    value = _parse(content[0]["text"].encode("utf-8"))
                    continue
                value = None
                break
            break

        versioned = (isinstance(value, dict)
                     and ("schemaVersion" in value or "thread" in value))
        if versioned:
            native_thread = value.get("thread")
            turns = value.get("turns")
            schema_version = value.get("schemaVersion")
            valid_root = (type(schema_version) is int and schema_version in {1, 2}
                          and isinstance(native_thread, dict)
                          and isinstance(native_thread.get("id"), str) and bool(native_thread["id"].strip())
                          and isinstance(turns, list))
            # Native read_thread turns are newest first. Validate the producer
            # ordering with every timestamp before claiming latest identity.
            timestamps = []
            if valid_root:
                for turn in turns:
                    if (not isinstance(turn, dict) or not isinstance(turn.get("id"), str)
                            or not turn["id"].strip() or not isinstance(turn.get("status"), str)
                            or not turn["status"].strip() or not isinstance(turn.get("items"), list)):
                        valid_root = False
                        break
                    timestamp = turn.get("startedAt")
                    if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                            or not math.isfinite(timestamp)):
                        valid_root = False
                        break
                    timestamps.append(timestamp)
                if any(earlier < later for earlier, later in zip(timestamps, timestamps[1:])):
                    valid_root = False
            order = list(range(len(turns)))
            thread_id = native_thread.get("id") if isinstance(native_thread, dict) else None
            legacy_order = False
        elif (isinstance(value, dict) and isinstance(value.get("thread_id"), str)
              and value["thread_id"].strip() and isinstance(value.get("turns"), list)):
            # Preserve the established simplified CLI input. If timestamps are
            # present, they define recency. Timestamp-free records retain the
            # old oldest-first list convention used by existing callers.
            thread_id = value["thread_id"]
            turns = value["turns"]
            valid_root = True
            present_times = [isinstance(turn, dict) and "startedAt" in turn for turn in turns]
            if any(present_times) and not all(present_times):
                valid_root = False
            if all(present_times) and turns:
                timestamps = [turn.get("startedAt") if isinstance(turn, dict) else None for turn in turns]
                if any(isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts)
                       for ts in timestamps):
                    valid_root = False
                legacy_order = False
                order = sorted(range(len(turns)), key=lambda index: timestamps[index], reverse=True)
            else:
                legacy_order = True
                order = list(reversed(range(len(turns))))
        else:
            valid_root = False
            turns = []
            thread_id = None
            legacy_order = False
            order = []

        if not valid_root:
            result.setdefault("category", "unsupported_thread_shape")
        else:
            counts = {key: 0 for key in ("completed", "inProgress", "failed", "interrupted", "unknown")}
            for turn in turns:
                status = turn.get("status") if isinstance(turn, dict) else None
                counts[status if isinstance(status, str) and status in counts else "unknown"] += 1
            selected_indexes = (list(range(max(0, len(turns)-4), len(turns)))
                                if legacy_order else order[:4])
            selected_set = set(selected_indexes)
            selected = []
            omitted_items = omitted_text = unknown_items = 0
            for index, turn in enumerate(turns):
                if not isinstance(turn, dict) or not isinstance(turn.get("items"), list):
                    unknown_items += 1
                    continue
                finals = []
                for item in turn["items"]:
                    if (isinstance(item, dict) and item.get("type") == "agentMessage"
                            and item.get("phase") == "final_answer"):
                        if isinstance(item.get("text"), str):
                            finals.append(item["text"])
                        else:
                            unknown_items += 1
                    elif isinstance(item, dict):
                        omitted_items += 1
                    else:
                        unknown_items += 1
                text = "\n".join(finals)
                if index in selected_set:
                    selected.append({"turn_id": _identity(turn.get("id")), "status": _identity(turn.get("status")),
                                     "final_answer": text[:320]})
                    omitted_text += max(0, len(text)-320)
                else:
                    omitted_text += len(text)
            latest = turns[order[0]] if order and isinstance(turns[order[0]], dict) else {}
            latest_status = latest.get("status")
            result.update(status=latest_status if isinstance(latest_status, str) and latest_status in counts else "unknown",
                          thread_id=_identity(thread_id), turn_id=_identity(latest.get("id")),
                          turns=selected, turn_status_counts=counts, failures=counts["failed"],
                          unknowns=counts["unknown"]+unknown_items)
            result["omissions"] = {"turn_details": max(0, len(turns)-4), "nonfinal_items": omitted_items,
                                   "final_answer_characters": omitted_text, "unknown_turn_shapes": unknown_items,
                                   "timestamp_free_legacy_order": legacy_order}
    else:
        raise ProjectionError("unsupported_kind")
    encoded = _encode_result(result)
    if kind in {"receipt", "exec"} and len(encoded) > MAX_OUTPUT_BYTES:
        encoded = _fit_result_text(result)
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ProjectionError("summary_too_large")
    return encoded


def _encode_result(result):
    return (json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))+"\n").encode("utf-8")


def _fit_result_text(result):
    omissions = result["omissions"]

    def trim_prefix(target, key, omission_key):
        original = target.get(key)
        if not isinstance(original, str) or not original:
            return False
        previously_omitted = omissions[omission_key]
        low, high, best = 0, len(original), None
        while low <= high:
            keep = (low + high) // 2
            target[key] = original[:keep]
            omissions[omission_key] = previously_omitted + len(original) - keep
            if len(_encode_result(result)) <= MAX_OUTPUT_BYTES:
                best = keep
                low = keep + 1
            else:
                high = keep - 1
        if best is None:
            best = 0
        target[key] = original[:best]
        omissions[omission_key] = previously_omitted + len(original) - best
        return len(_encode_result(result)) <= MAX_OUTPUT_BYTES

    # Keep the summary first; trim later sampled check names before earlier ones.
    for sample in reversed(result.get("nonpassing_checks", [])):
        if isinstance(sample, dict) and trim_prefix(
                sample, "name", "nonpassing_check_name_characters"):
            return _encode_result(result)
    if result["kind"] == "exec":
        trim_prefix(result, "output", "output_characters")
    else:
        trim_prefix(result, "final_answer", "summary_characters")
    return _encode_result(result)


def _identity(value):
    return value[:160] if isinstance(value, str) else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("thread", "receipt", "exec"))
    parser.add_argument("source")
    args = parser.parse_args(argv)
    try:
        sys.stdout.buffer.write(project(args.source, args.kind))
        return 0
    except (OSError, ProjectionError, TypeError, RecursionError):
        sys.stderr.write('{"status":"error","category":"projection_failed"}\n')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
