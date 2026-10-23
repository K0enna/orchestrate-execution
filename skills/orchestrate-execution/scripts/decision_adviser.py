#!/usr/bin/env python3
"""Request typed, bounded advice from one explicitly selected provider."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any


OPENAI_ENDPOINT = "https://api.openai.com/v1/decisions"
OPENAI_MODEL = "gpt-6-luna"
MAX_REQUEST_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 512 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 120.0
MAX_QUESTIONS = 16
MAX_NAME_LENGTH = 64
MAX_INSTRUCTIONS_BYTES = 2048
MAX_CHOICE_COUNT = 32
MAX_CHOICE_LABEL_LENGTH = 64
MAX_DESCRIPTION_BYTES = 512
MAX_SCORE_LEVELS = 10
MAX_SCORE_LEVEL_BYTES = 512
PROBABILITY_TOLERANCE = 0.001
QUESTION_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z", re.ASCII)


class AdviserError(Exception):
    """A fixed, safe error category with an optional HTTP status."""

    def __init__(self, category: str, http_status: int | None = None):
        self.category = category
        self.http_status = http_status
        super().__init__(category)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _check_finite_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    if isinstance(value, list):
        for item in value:
            _check_finite_json(item)
    elif isinstance(value, dict):
        for item in value.values():
            _check_finite_json(item)


def _decode_json(raw: bytes, category: str) -> Any:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
        _check_finite_json(value)
        return value
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise AdviserError(category) from None


def _read_request(path_value: str | None) -> bytes:
    try:
        if path_value is None or path_value == "-":
            raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        else:
            with Path(path_value).open("rb") as source:
                raw = source.read(MAX_REQUEST_BYTES + 1)
    except (OSError, AttributeError):
        raise AdviserError("input_unavailable") from None
    if len(raw) > MAX_REQUEST_BYTES:
        raise AdviserError("request_too_large")
    return raw


def _text(value: Any, *, max_bytes: int | None = None, max_chars: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdviserError("invalid_request")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise AdviserError("invalid_request") from None
    if max_bytes is not None and len(encoded) > max_bytes:
        raise AdviserError("invalid_request")
    if max_chars is not None and len(value) > max_chars:
        raise AdviserError("invalid_request")
    return value


def _validate_request(value: Any) -> tuple[str, dict[str, dict[str, Any]]]:
    if not isinstance(value, dict) or set(value) != {"state", "questions"}:
        raise AdviserError("invalid_request")
    state = _text(value["state"])
    raw_questions = value["questions"]
    if not isinstance(raw_questions, dict) or not 1 <= len(raw_questions) <= MAX_QUESTIONS:
        raise AdviserError("invalid_request")

    questions: dict[str, dict[str, Any]] = {}
    for name, raw_question in raw_questions.items():
        if (
            not isinstance(name, str)
            or len(name) > MAX_NAME_LENGTH
            or not QUESTION_NAME_RE.fullmatch(name)
            or not isinstance(raw_question, dict)
        ):
            raise AdviserError("invalid_request")
        question_type = raw_question.get("type")
        instructions = _text(
            raw_question.get("instructions"), max_bytes=MAX_INSTRUCTIONS_BYTES
        )
        if question_type == "predicate":
            if set(raw_question) != {"type", "instructions"}:
                raise AdviserError("invalid_request")
            questions[name] = {
                "type": "predicate",
                "instructions": instructions,
            }
        elif question_type == "choice":
            if set(raw_question) != {"type", "instructions", "choices"}:
                raise AdviserError("invalid_request")
            raw_choices = raw_question["choices"]
            if (
                not isinstance(raw_choices, dict)
                or not 2 <= len(raw_choices) <= MAX_CHOICE_COUNT
            ):
                raise AdviserError("invalid_request")
            choices: dict[str, str] = {}
            for label, description in raw_choices.items():
                label = _text(label, max_chars=MAX_CHOICE_LABEL_LENGTH)
                choices[label] = _text(description, max_bytes=MAX_DESCRIPTION_BYTES)
            questions[name] = {
                "type": "choice",
                "instructions": instructions,
                "choices": choices,
            }
        elif question_type == "score":
            if set(raw_question) != {"type", "instructions", "levels"}:
                raise AdviserError("invalid_request")
            raw_levels = raw_question["levels"]
            if (
                not isinstance(raw_levels, list)
                or not 2 <= len(raw_levels) <= MAX_SCORE_LEVELS
            ):
                raise AdviserError("invalid_request")
            levels = [
                _text(level, max_bytes=MAX_SCORE_LEVEL_BYTES)
                for level in raw_levels
            ]
            questions[name] = {
                "type": "score",
                "instructions": instructions,
                "levels": levels,
            }
        else:
            raise AdviserError("invalid_request")
    return state, questions


def _provider_payload(
    provider: str, state: str, questions: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    if provider != "openai":
        raise AdviserError("invalid_provider")

    named_questions: list[dict[str, Any]] = []
    for name, question in questions.items():
        question_type = question["type"]
        entry = {
            "type": question_type,
            "name": name,
            "instructions": question["instructions"],
        }
        if question_type == "choice":
            entry["choices"] = [
                {"value": label, "description": description}
                for label, description in question["choices"].items()
            ]
        elif question_type == "score":
            entry["levels"] = [
                {"label": level} for level in question["levels"]
            ]
        named_questions.append(entry)
    return {"model": OPENAI_MODEL, "input": state, "questions": named_questions}


def _encode_payload(payload: dict[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise AdviserError("invalid_request") from None
    if len(encoded) > MAX_REQUEST_BYTES:
        raise AdviserError("request_too_large")
    return encoded


def _contains_timeout(error: BaseException) -> bool:
    import socket

    current: Any = error
    for _ in range(4):
        if isinstance(current, (TimeoutError, socket.timeout)):
            return True
        current = getattr(current, "reason", None)
        if current is None:
            break
    return False


def _http_status(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return value
    return None


def _post_json(body: bytes, api_key: str, timeout: float) -> tuple[bytes, int]:
    import http.client
    import socket
    import ssl
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    request = urllib.request.Request(
        OPENAI_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = _http_status(response.getcode())
            if status is None or not 200 <= status < 300:
                raise AdviserError("http_error", status)
            content_type = response.headers.get_content_type().lower()
            if content_type != "application/json" and not content_type.endswith(
                "+json"
            ):
                raise AdviserError("invalid_response", status)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise AdviserError("response_too_large", status)
            return raw, status
    except urllib.error.HTTPError as error:
        status = _http_status(error.code)
        error.close()
        raise AdviserError("http_error", status) from None
    except AdviserError:
        raise
    except (TimeoutError, socket.timeout):
        raise AdviserError("timeout") from None
    except urllib.error.URLError as error:
        category = "timeout" if _contains_timeout(error) else "network_error"
        raise AdviserError(category) from None
    except (OSError, http.client.HTTPException, ssl.SSLError, ValueError):
        raise AdviserError("network_error") from None


def _probability(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdviserError("invalid_response")
    if isinstance(value, float) and not math.isfinite(value):
        raise AdviserError("invalid_response")
    if value < 0 or value > 1:
        raise AdviserError("invalid_response")
    return value


def _confidence(answer: dict[str, Any]) -> int | float:
    if "confidence" not in answer:
        raise AdviserError("invalid_response")
    return _probability(answer["confidence"])


def _array_distribution(
    raw: Any, expected: list[str]
) -> dict[str, int | float]:
    if not isinstance(raw, list) or len(raw) != len(expected):
        raise AdviserError("invalid_response")
    distribution: dict[str, int | float] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise AdviserError("invalid_response")
        option = item.get("value")
        if not isinstance(option, str) or option not in expected or option in distribution:
            raise AdviserError("invalid_response")
        if "probability" not in item:
            raise AdviserError("invalid_response")
        distribution[option] = _probability(item["probability"])
    if set(distribution) != set(expected):
        raise AdviserError("invalid_response")
    if abs(math.fsum(distribution.values()) - 1.0) > PROBABILITY_TOLERANCE:
        raise AdviserError("invalid_response")
    return distribution


def _score_value(value: Any, level_count: int) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdviserError("invalid_response")
    if isinstance(value, float) and not math.isfinite(value):
        raise AdviserError("invalid_response")
    if value < 0 or value > level_count - 1:
        raise AdviserError("invalid_response")
    return value


def _check_weighted_score(score: int | float, probabilities: list[int | float]) -> None:
    expected = math.fsum(index * probability for index, probability in enumerate(probabilities))
    if abs(score - expected) > PROBABILITY_TOLERANCE:
        raise AdviserError("invalid_response")


def _unresolved(question: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"type": question["type"], "status": "unresolved", "reason": reason}


def _openai_score_distribution(
    raw: Any, levels: list[str]
) -> list[int | float]:
    if not isinstance(raw, list) or len(raw) != len(levels):
        raise AdviserError("invalid_response")
    probabilities: dict[int, int | float] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise AdviserError("invalid_response")
        index = item.get("value")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < len(levels)
            or index in probabilities
            or item.get("label") != levels[index]
            or "probability" not in item
        ):
            raise AdviserError("invalid_response")
        probabilities[index] = _probability(item["probability"])
    if set(probabilities) != set(range(len(levels))):
        raise AdviserError("invalid_response")
    ordered = [probabilities[index] for index in range(len(levels))]
    if abs(math.fsum(ordered) - 1.0) > PROBABILITY_TOLERANCE:
        raise AdviserError("invalid_response")
    return ordered


def _openai_answer(question: dict[str, Any], answer: Any) -> dict[str, Any]:
    if not isinstance(answer, dict):
        raise AdviserError("invalid_response")
    question_type = question["type"]
    if answer.get("type") != question_type:
        raise AdviserError("invalid_response")
    if question_type == "predicate":
        if "probability" not in answer:
            raise AdviserError("invalid_response")
        return {
            "type": "predicate",
            "status": "answered",
            "probability_yes": _probability(answer["probability"]),
        }
    if question_type == "choice":
        choices = question["choices"]
        choice = answer.get("choice")
        if not isinstance(choice, str) or choice not in choices:
            raise AdviserError("invalid_response")
        distribution = _array_distribution(answer.get("probabilities"), list(choices))
        return {
            "type": "choice",
            "status": "answered",
            "choice": choice,
            "probabilities": [
                {"value": key, "probability": distribution[key]} for key in choices
            ],
            "confidence": _confidence(answer),
            "confidence_semantics": "separate_provider_field",
        }
    levels = question["levels"]
    score = _score_value(answer.get("score"), len(levels))
    probabilities = _openai_score_distribution(answer.get("probabilities"), levels)
    _check_weighted_score(score, probabilities)
    return {
        "type": "score",
        "status": "answered",
        "score": score,
        "levels": [
            {"index": index, "label": label, "probability": probabilities[index]}
            for index, label in enumerate(levels)
        ],
        "confidence": _confidence(answer),
        "confidence_semantics": "separate_provider_field",
    }


def _answers(
    questions: dict[str, dict[str, Any]], raw_answers: Any
) -> dict[str, Any]:
    if not isinstance(raw_answers, list):
        raise AdviserError("invalid_response")
    supplied: dict[str, Any] = {}
    for answer in raw_answers:
        if not isinstance(answer, dict):
            raise AdviserError("invalid_response")
        name = answer.get("name")
        if not isinstance(name, str) or name not in questions or name in supplied:
            raise AdviserError("invalid_response")
        supplied[name] = answer

    normalized: dict[str, Any] = {}
    for name, question in questions.items():
        if name not in supplied:
            normalized[name] = _unresolved(question, "missing_answer")
            continue
        answer = supplied[name]
        if answer.get("type") == "refusal":
            normalized[name] = _unresolved(question, "refusal")
            continue
        normalized[name] = _openai_answer(question, answer)
    return normalized


def _model_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdviserError("invalid_response")
    return value


def _token_count(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _usage(value: Any) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
    if not isinstance(value, dict):
        return normalized
    for key in normalized:
        if key in value:
            normalized[key] = _token_count(value[key])
    for group, names in (
        ("input_tokens_details", ("cached_tokens", "cache_write_tokens")),
        ("output_tokens_details", ("reasoning_tokens",)),
    ):
        details = value.get(group)
        if isinstance(details, dict):
            present = {
                name: _token_count(details[name])
                for name in names
                if name in details
            }
            if present:
                normalized[group] = present
    return normalized


def _normalize_response(
    questions: dict[str, dict[str, Any]], response: Any
) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise AdviserError("invalid_response")
    model = _model_name(response.get("model"))
    if "answers" not in response:
        raise AdviserError("invalid_response")
    answers = _answers(questions, response["answers"])
    status = (
        "partial"
        if any(answer["status"] == "unresolved" for answer in answers.values())
        else "complete"
    )
    return {
        "status": status,
        "model": model,
        "answers": answers,
        "usage": _usage(response.get("usage")),
    }


def _api_key() -> str:
    value = os.environ.get("OPENAI_API_KEY")
    if not isinstance(value, str) or not value.strip():
        raise AdviserError("missing_credentials")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise AdviserError("invalid_credentials") from None
    if any(byte < 33 or byte > 126 for byte in encoded):
        raise AdviserError("invalid_credentials")
    return value


def _elapsed(started: float) -> float:
    return round(max(0.0, time.perf_counter() - started), 6)


def _empty_usage() -> dict[str, Any]:
    return {"input_tokens": None, "output_tokens": None, "total_tokens": None}


def _failure_report(
    provider: str,
    attempted_call: bool,
    elapsed_seconds: float,
    error: AdviserError,
) -> dict[str, Any]:
    return {
        "status": "error",
        "provider": provider,
        "attempted_call": attempted_call,
        "elapsed_seconds": elapsed_seconds,
        "model": None,
        "answers": {},
        "usage": _empty_usage(),
        "error": {
            "category": error.category,
            "http_status": _http_status(error.http_status),
        },
    }


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise AdviserError("invalid_cli")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--provider",
        required=True,
        metavar="{openai}",
        help="explicit decision provider",
    )
    parser.add_argument(
        "--timeout",
        default=str(DEFAULT_TIMEOUT_SECONDS),
        metavar="SECONDS",
        help="finite request timeout from 1 to 120 seconds (default: 30)",
    )
    parser.add_argument(
        "request",
        nargs="?",
        help="JSON request file; omit or use '-' to read stdin",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    started = time.perf_counter()
    provider = "unknown"
    attempted_call = False
    http_status: int | None = None
    try:
        args = _parser().parse_args(argv)
        if args.provider != "openai":
            raise AdviserError("invalid_provider")
        provider = "openai"
        try:
            timeout = float(args.timeout)
        except (TypeError, ValueError):
            raise AdviserError("invalid_timeout") from None
        if not math.isfinite(timeout) or not MIN_TIMEOUT_SECONDS <= timeout <= MAX_TIMEOUT_SECONDS:
            raise AdviserError("invalid_timeout")
        request_value = _decode_json(_read_request(args.request), "invalid_json")
        state, questions = _validate_request(request_value)
        payload = _provider_payload(provider, state, questions)
        body = _encode_payload(payload)
        api_key = _api_key()
        attempted_call = True
        response_bytes, http_status = _post_json(body, api_key, timeout)
        response_value = _decode_json(response_bytes, "invalid_response")
        normalized = _normalize_response(questions, response_value)
        report = {
            "status": normalized["status"],
            "provider": provider,
            "attempted_call": True,
            "elapsed_seconds": _elapsed(started),
            "model": normalized["model"],
            "answers": normalized["answers"],
            "usage": normalized["usage"],
            "error": None,
        }
        exit_code = 0
    except AdviserError as error:
        if error.http_status is None:
            error.http_status = http_status
        report = _failure_report(
            provider, attempted_call, _elapsed(started), error
        )
        exit_code = (
            2
            if error.category
            in {
                "invalid_provider",
                "invalid_cli",
                "invalid_timeout",
                "input_unavailable",
                "request_too_large",
                "invalid_json",
                "invalid_request",
            }
            else 1
        )
    except Exception:
        error = AdviserError("internal_error", http_status)
        report = _failure_report(
            provider, attempted_call, _elapsed(started), error
        )
        exit_code = 1
    sys.stdout.write(
        json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
