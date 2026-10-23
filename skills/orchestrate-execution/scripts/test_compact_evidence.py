"""Observable CLI projections: retain failures and identity without raw transport."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

import compact_evidence as compact
import detached_receipt


class CompactEvidenceCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, kind, data):
        source = self.root / "source.json"
        source.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
        return self.cli_source(kind, source)

    def cli_source(self, kind, source):
        before = source.read_bytes()
        result = subprocess.run([sys.executable, "-B", str(Path(compact.__file__)), kind, str(source)], capture_output=True)
        self.assertEqual(source.read_bytes(), before)
        return result, source, before

    def test_large_native_read_retains_statuses_and_final_without_tool_payloads(self):
        turns = [{"id": "turn-"+str(i), "status": "failed" if i == 0 else "completed", "items": [
            {"type": "toolCall", "arguments": "RAW-ARGUMENTS"*20000, "output": "RAW-OUTPUT"*20000},
            {"type": "agentMessage", "phase": "final_answer", "text": "Result " + str(i) + " "+"z"*500}]} for i in range(6)]
        turns.append({"id": "latest", "status": "unrecognized", "items": []})
        result, source, raw = self.cli("thread", {"thread_id": "worker-1", "turns": turns})
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["source"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(summary["source"]["path"], str(source))
        self.assertEqual((summary["failures"], summary["unknowns"], summary["turn_id"]), (1, 1, "latest"))
        self.assertEqual(summary["status"], "unknown")
        self.assertEqual(summary["omissions"]["turn_details"], 3)
        self.assertEqual(summary["omissions"]["nonfinal_items"], 6)
        self.assertGreater(summary["omissions"]["final_answer_characters"], 0)
        self.assertLess(len(result.stdout), 4096)
        self.assertNotIn(b"RAW-", result.stdout)

    def test_native_thread_root_accepts_v2_and_mcp_text_wrapper_with_newest_first_turns(self):
        def native(status):
            turns = []
            for index in range(8, -1, -1):
                turns.append({"id": f"native-turn-{index}",
                              "status": status if index == 8 else "completed",
                              "startedAt": 1000 + index,
                              "items": [{"type": "toolCall", "arguments": "RAW-ARGUMENT-"*100,
                                         "output": "RAW-OUTPUT-"*100},
                                        {"type": "agentMessage", "phase": "final_answer",
                                         "text": f"Answer {index}: " + "x"*500}]})
            return {"schemaVersion": 2, "thread": {"id": "thread-native-2"}, "turns": turns}

        for status in ("failed", "inProgress"):
            with self.subTest(latest_status=status):
                source_value = native(status)
                wrapped = {"isError": False, "content": [{"type": "text", "text": json.dumps(source_value)}]}
                for envelope in (source_value, wrapped):
                    result, _, _ = self.cli("thread", envelope)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    summary = json.loads(result.stdout)
                    self.assertEqual((summary.get("thread_id"), summary.get("turn_id"), summary["status"]),
                                     ("thread-native-2", "native-turn-8", status))
                    self.assertEqual(summary["turn_status_counts"],
                                     {"completed": 8, "inProgress": int(status == "inProgress"),
                                      "failed": int(status == "failed"), "interrupted": 0, "unknown": 0})
                    self.assertEqual([turn["turn_id"] for turn in summary["turns"]],
                                     [f"native-turn-{index}" for index in range(8, 4, -1)])
                    self.assertEqual(summary["omissions"]["turn_details"], 5)
                    self.assertGreater(summary["omissions"]["final_answer_characters"], 1500)
                    self.assertEqual((summary["failures"], summary["unknowns"]),
                                     (int(status == "failed"), 0))
                    self.assertNotIn(b"RAW-", result.stdout)

    def test_native_read_shape_rejects_inconsistent_newest_first_timestamps_without_identity(self):
        value = {"schemaVersion": 2, "thread": {"id": "must-not-be-claimed"},
                 "turns": [{"id": "older", "status": "completed", "startedAt": 10, "items": []},
                           {"id": "newer", "status": "failed", "startedAt": 20, "items": []}]}
        result, _, _ = self.cli("thread", value)
        self.assertEqual(result.returncode, 0)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "unknown")
        self.assertEqual(summary["category"], "unsupported_thread_shape")
        self.assertNotIn("thread_id", summary)
        self.assertNotIn("turn_id", summary)
        self.assertIsNone(summary["failures"])
        self.assertIsNone(summary["unknowns"])

    def test_receipt_counts_every_failed_and_unknown_check_without_dumping_artifacts(self):
        value = {"version": 1, "run_id": "run-1", "parent_thread_id": "parent-1", "outcome": "failed",
                 "summary": "Exact failure result " + "s"*3000,
                 "checks": [{"name": "failed "+str(i), "result": "fail"} for i in range(50)] +
                           [{"name": "not run", "result": "not_run"}, {"name": "new shape", "result": "new"}],
                 "artifacts": [{"path": "FULL-ARTIFACT-DETAIL"*1000, "sha256": "x"} for _ in range(100)]}
        result, _, _ = self.cli("receipt", value)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual((summary["failures"], summary["unknowns"]), (50, 2))
        self.assertEqual(summary["checks"], {"pass": 0, "fail": 50, "not_run": 1, "unknown": 1})
        self.assertEqual(summary["omissions"]["nonpassing_check_details"], 44)
        self.assertEqual(summary["omissions"]["artifact_details"], 100)
        self.assertLess(len(result.stdout), 4096)
        self.assertNotIn(b"FULL-ARTIFACT-DETAIL", result.stdout)

    def test_valid_unicode_receipt_stays_within_serialized_byte_budget(self):
        source = self.root / "unicode-failed-receipt.json"
        run_id, parent_thread_id = str(uuid.uuid4()), str(uuid.uuid4())
        checks = [{"name": "😀" * 160, "result": "fail"} for _ in range(8)]
        detached_receipt.write_receipt(
            str(source), run_id, parent_thread_id, str(self.root), "failed",
            "😀" * 1200, artifacts=[], checks=checks,
        )
        receipt, _ = detached_receipt.validate_receipt(
            str(source), run_id, parent_thread_id, str(self.root)
        )
        self.assertEqual(receipt["outcome"], "failed")
        self.assertEqual((receipt["run_id"], receipt["parent_thread_id"]),
                         (run_id, parent_thread_id))
        self.assertEqual(len(receipt["summary"]), 1200)
        self.assertEqual(len(receipt["checks"]), 8)
        self.assertTrue(all(len(check["name"]) == 160 for check in receipt["checks"]))

        result, _, raw = self.cli_source("receipt", source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(len(result.stdout), compact.MAX_OUTPUT_BYTES)
        summary = json.loads(result.stdout)
        self.assertEqual((summary["status"], summary["run_id"], summary["parent_thread_id"]),
                         ("failed", run_id, parent_thread_id))
        self.assertEqual(summary["failures"], 8)
        self.assertEqual(summary["unknowns"], 0)
        self.assertEqual(summary["checks"], {"pass": 0, "fail": 8, "not_run": 0, "unknown": 0})
        self.assertEqual(summary["source"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(summary["omissions"]["summary_characters"],
                         1200 - len(summary["final_answer"]))
        omitted_name_characters = 8 * 160 - sum(
            len(check["name"] or "") for check in summary["nonpassing_checks"]
        )
        self.assertGreater(omitted_name_characters, 0)
        self.assertEqual(summary["omissions"]["nonpassing_check_name_characters"],
                         omitted_name_characters)

    def test_exec_results_retain_terminal_pending_and_unknown_without_raw_dump(self):
        for fields, status, failures, unknowns in (
                ({"exit_code": 0}, "completed", 0, 0),
                ({"exit_code": 7}, "failed", 1, 0),
                ({"session_id": 42}, "running", 0, 0),
                ({"exit_code": None, "session_id": 42}, "running", 0, 0),
                ({}, "unknown", None, None),
                ({"exit_code": True}, "unknown", None, None),
                ({"exit_code": 0, "session_id": 42}, "unknown", None, None),
                ({"session_id": "42"}, "unknown", None, None)):
            with self.subTest(fields=fields):
                output = "😀" * 20000
                value = {"chunk_id": "\U0001f600" * 160, "wall_time_seconds": 0.5,
                         "original_token_count": 12345, "output": output, **fields}
                result, source, raw = self.cli("exec", value)
                self.assertEqual(result.returncode, 0, result.stderr)
                summary = json.loads(result.stdout)
                self.assertEqual((summary["status"], summary["failures"], summary["unknowns"]),
                                 (status, failures, unknowns))
                self.assertLessEqual(len(result.stdout), compact.MAX_OUTPUT_BYTES)
                self.assertEqual(summary["source"]["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(source.read_bytes(), raw)
                if status != "unknown":
                    self.assertEqual(summary["exit_code"], fields.get("exit_code"))
                    self.assertEqual(summary["session_id"], fields.get("session_id"))
                    self.assertEqual(summary["chunk_id"], "\U0001f600" * 160)
                    self.assertEqual(summary["original_token_count"], 12345)
                    self.assertEqual(summary["wall_time_seconds"], 0.5)
                    self.assertEqual(summary["omissions"]["output_characters"],
                                     len(output) - len(summary["output"]))
                    self.assertTrue(output.startswith(summary["output"]))
        for value in ({"exit_code": 0}, {"output": 123, "exit_code": 0},
                      {"output": "ok", "exit_code": 0, "unexpected": "producer drift"}):
            result, _, _ = self.cli("exec", value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "unknown")

    def test_malformed_unsupported_and_oversized_inputs_are_explicit(self):
        for raw in (b"{", b'{"turns":NaN}', b'{"turns":[],"turns":[]}', b" "*(compact.MAX_INPUT_BYTES+1)):
            with self.subTest(raw=raw[:50]):
                result, _, _ = self.cli("thread", raw)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stderr)["status"], "error")
        for kind in ("thread", "receipt"):
            result, _, _ = self.cli(kind, {"unexpected": "shape"})
            self.assertEqual(result.returncode, 0)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "unknown")
            self.assertIsNone(summary["failures"])
            self.assertIsNone(summary["unknowns"])


if __name__ == "__main__":
    unittest.main()
