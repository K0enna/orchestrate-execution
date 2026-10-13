from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import run


ACTIONS = ["work_directly", "dispatch_workers"]
CASES = [
    {
        "id": "case-a",
        "task": "Work on the small local fix.",
        "expected_action": "work_directly",
        "expected_accept": False,
    },
    {
        "id": "case-b",
        "task": "Dispatch the two independent tasks.",
        "expected_action": "dispatch_workers",
        "expected_accept": True,
    },
]


def decision(case_id: str, action: str, accept: bool, reason: str = "Because the evidence supports this.") -> dict[str, object]:
    return {
        "id": case_id,
        "next_action": action,
        "accept_return": accept,
        "reason": reason,
    }


def completed_events(*, include_terminal: bool = True, extra_events: list[dict[str, object]] | None = None) -> str:
    events: list[dict[str, object]] = [
        {"type": "thread.started", "thread_id": "thread-123"},
        {"type": "turn.started"},
    ]
    if extra_events:
        events.extend(extra_events)
    if include_terminal:
        events.append({
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 80,
                "output_tokens": 10,
            },
        })
    return "\n".join(json.dumps(event) for event in events) + "\n"


class PromptTests(unittest.TestCase):
    def test_prompt_uses_only_case_id_and_task_and_does_not_leak_expected_fields(self) -> None:
        cases = [{
            "id": "probe-1",
            "task": "Decide what to do.",
            "expected_action": "SECRET_EXPECTED_ACTION_2718",
            "expected_accept": True,
            "private_result": "SECRET_PRIVATE_RESULT_3141",
        }]
        skill_text = "A local skill body.\nSecond line.\n"

        prompt = run.build_prompt(cases, ["choose_alpha", "choose_beta"], skill_text)

        self.assertIn("Scenario ID: probe-1", prompt)
        self.assertIn("Task: Decide what to do.", prompt)
        self.assertIn("Allowed next_action values: choose_alpha, choose_beta", prompt)
        self.assertIn("<skill>\n" + skill_text + "</skill>", prompt)
        self.assertNotIn("SECRET_EXPECTED_ACTION_2718", prompt)
        self.assertNotIn("SECRET_PRIVATE_RESULT_3141", prompt)


class GradingTests(unittest.TestCase):
    def test_duplicate_and_missing_case_ids_fail_the_exact_case_set(self) -> None:
        response = {"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-a", "work_directly", False),
        ]}

        graded = run.grade_response(response, CASES, ACTIONS)

        self.assertFalse(graded["all_passed"])
        self.assertIn("duplicate_case_id:case-a", graded["failures"])
        self.assertIn("missing_case_id:case-b", graded["failures"])
        self.assertFalse(graded["grades"][0]["passed"])
        self.assertFalse(graded["grades"][1]["passed"])

    def test_wrong_action_and_acceptance_are_rejected(self) -> None:
        response = {"decisions": [
            decision("case-a", "dispatch_workers", True),
            decision("case-b", "dispatch_workers", True),
        ]}

        graded = run.grade_response(response, CASES, ACTIONS)

        self.assertFalse(graded["all_passed"])
        self.assertEqual(
            graded["grades"][0]["failures"],
            ["next_action_mismatch", "accept_return_mismatch"],
        )
        self.assertTrue(graded["grades"][1]["passed"])

    def test_non_string_next_action_returns_a_failed_grade(self) -> None:
        for malformed_action in ([], {"action": "work_directly"}):
            with self.subTest(action=malformed_action):
                response = {"decisions": [
                    decision("case-a", malformed_action, False),
                    decision("case-b", "dispatch_workers", True),
                ]}

                graded = run.grade_response(response, CASES, ACTIONS)

                self.assertFalse(graded["all_passed"])
                self.assertIn("decision_0_next_action_is_invalid", graded["failures"])

    def test_legitimate_response_passes_every_case(self) -> None:
        response = {"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-b", "dispatch_workers", True),
        ]}

        graded = run.grade_response(response, CASES, ACTIONS)

        self.assertTrue(graded["all_passed"])
        self.assertTrue(all(grade["passed"] for grade in graded["grades"]))

    def test_extra_case_id_is_rejected(self) -> None:
        response = {"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-b", "dispatch_workers", True),
            decision("extra", "work_directly", False),
        ]}

        graded = run.grade_response(response, CASES, ACTIONS)

        self.assertFalse(graded["all_passed"])
        self.assertIn("unexpected_case_id:extra", graded["failures"])


class EventAndExecutionTests(unittest.TestCase):
    def test_nonzero_exit_and_incomplete_stream_are_never_accepted(self) -> None:
        response_text = json.dumps({"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-b", "dispatch_workers", True),
        ]})

        failed_process = run.evaluate_run(CASES, ACTIONS, response_text, completed_events(), 7)
        incomplete_events = run.evaluate_run(
            CASES,
            ACTIONS,
            response_text,
            completed_events(include_terminal=False),
            0,
        )
        malformed_events = run.evaluate_run(CASES, ACTIONS, response_text, "not-json\n", 0)

        self.assertFalse(failed_process["accepted"])
        self.assertIn("process_exit_code:7", failed_process["execution_failures"])
        self.assertFalse(incomplete_events["accepted"])
        self.assertIsNone(incomplete_events["usage"])
        self.assertFalse(malformed_events["accepted"])
        self.assertIsNone(malformed_events["usage"])

    def test_unparseable_response_fails_without_fabricating_zero_usage(self) -> None:
        result = run.evaluate_run(CASES, ACTIONS, "not-json", completed_events(), 0)

        self.assertFalse(result["accepted"])
        self.assertTrue(result["response_error"].startswith("invalid_response_json:"))
        self.assertEqual(result["usage"]["total_tokens"], 110)

    def test_multiple_terminal_events_have_no_usage(self) -> None:
        duplicate_completion = {
            "type": "turn.completed",
            "usage": {"input_tokens": 200, "cached_input_tokens": 0, "output_tokens": 20},
        }

        parsed = run.parse_events(completed_events(extra_events=[duplicate_completion]))

        self.assertIsNone(parsed["usage"])
        self.assertIn("multiple_terminal_events", parsed["failures"])

    def test_error_event_and_tool_event_fail_closed(self) -> None:
        response_text = json.dumps({"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-b", "dispatch_workers", True),
        ]})
        error_result = run.evaluate_run(
            CASES,
            ACTIONS,
            response_text,
            completed_events(extra_events=[{"type": "error", "message": "failed"}]),
            0,
        )
        tool_result = run.evaluate_run(
            CASES,
            ACTIONS,
            response_text,
            completed_events(extra_events=[{"type": "item.started", "item": {"type": "command_execution"}}]),
            0,
        )

        self.assertFalse(error_result["accepted"])
        self.assertIn("error_event", error_result["execution_failures"])
        self.assertFalse(tool_result["accepted"])
        self.assertTrue(tool_result["tool_event_detection"]["unexpected_tool_events"])

    def test_cached_input_is_reported_but_not_added_to_total(self) -> None:
        parsed = run.parse_events(completed_events())

        self.assertEqual(parsed["thread_id"], "thread-123")
        self.assertEqual(parsed["usage"], {
            "input_tokens": 100,
            "cached_input_tokens": 80,
            "output_tokens": 10,
            "total_tokens": 110,
        })

        impossible_usage_events = completed_events().replace(
            '"cached_input_tokens": 80',
            '"cached_input_tokens": 101',
        )
        impossible_usage = run.parse_events(impossible_usage_events)
        valid_response = json.dumps({"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-b", "dispatch_workers", True),
        ]})
        rejected = run.evaluate_run(CASES, ACTIONS, valid_response, impossible_usage_events, 0)

        self.assertIsNone(impossible_usage["usage"])
        self.assertIn("missing_or_malformed_usage", impossible_usage["failures"])
        self.assertFalse(rejected["accepted"])
        self.assertIsNone(rejected["usage"])

    def test_unknown_events_do_not_claim_tool_free_or_accepted(self) -> None:
        response_text = json.dumps({"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-b", "dispatch_workers", True),
        ]})
        result = run.evaluate_run(
            CASES,
            ACTIONS,
            response_text,
            completed_events(extra_events=[{"type": "future.event"}]),
            0,
        )

        self.assertFalse(result["accepted"])
        self.assertIsNone(result["tool_event_detection"]["unexpected_tool_events"])
        self.assertIsNone(result["tool_event_detection"]["tool_free"])

    def test_malformed_item_lifecycle_events_fail_closed(self) -> None:
        response_text = json.dumps({"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-b", "dispatch_workers", True),
        ]})
        lifecycle_types = ("item.started", "item.updated", "item.completed", "item.delta")
        malformed_events = (
            {},
            {"item": None},
            {"item": "agent_message"},
            {"item": []},
        )

        for event_type in lifecycle_types:
            for malformed in malformed_events:
                with self.subTest(event_type=event_type, malformed=malformed):
                    event = {"type": event_type, **malformed}
                    result = run.evaluate_run(
                        CASES,
                        ACTIONS,
                        response_text,
                        completed_events(extra_events=[event]),
                        0,
                    )

                    self.assertFalse(result["accepted"])
                    self.assertIsNone(result["tool_event_detection"]["unexpected_tool_events"])
                    self.assertIsNone(result["tool_event_detection"]["tool_free"])
                    self.assertIn("tool_free_not_verified", result["execution_failures"])

    def test_known_non_item_and_non_tool_item_events_remain_accepted(self) -> None:
        response_text = json.dumps({"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-b", "dispatch_workers", True),
        ]})
        valid_events = [None] + [
            {"type": event_type, "item": {"type": "agent_message"}}
            for event_type in ("item.started", "item.updated", "item.completed", "item.delta")
        ]

        for event in valid_events:
            with self.subTest(event=event):
                extra = [event] if event is not None else None
                result = run.evaluate_run(
                    CASES,
                    ACTIONS,
                    response_text,
                    completed_events(extra_events=extra),
                    0,
                )

                self.assertTrue(result["accepted"])
                self.assertFalse(result["tool_event_detection"]["unexpected_tool_events"])
                self.assertTrue(result["tool_event_detection"]["tool_free"])

    def test_unknown_outer_event_stays_unknown_with_known_agent_item(self) -> None:
        response_text = json.dumps({"decisions": [
            decision("case-a", "work_directly", False),
            decision("case-b", "dispatch_workers", True),
        ]})
        result = run.evaluate_run(
            CASES,
            ACTIONS,
            response_text,
            completed_events(extra_events=[{
                "type": "future.event",
                "item": {"type": "agent_message"},
            }]),
            0,
        )

        self.assertFalse(result["accepted"])
        self.assertIsNone(result["tool_event_detection"]["unexpected_tool_events"])
        self.assertIsNone(result["tool_event_detection"]["tool_free"])
        self.assertIn("future.event", result["tool_event_detection"]["unknown_event_types"])


class CliBoundaryTests(unittest.TestCase):
    def test_existing_output_directory_is_refused_without_modification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "prior-attempt"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("previous result", encoding="utf-8")
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    run.main([
                        "--model", "requested-model",
                        "--effort", "medium",
                        "--output", str(output),
                    ])

            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(marker.read_text(encoding="utf-8"), "previous result")
            self.assertFalse((output / "prompt.txt").exists())
            self.assertIn("output path already exists", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
