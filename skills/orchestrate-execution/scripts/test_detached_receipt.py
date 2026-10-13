import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

import detached_receipt as receipts


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.artifact = self.artifacts / "proof.txt"
        self.artifact.write_text("verified test result\n", encoding="utf-8")
        self.state = self.root / "claims"
        self.path = self.root / "receipt.json"
        self.run = str(uuid4())
        self.parent = str(uuid4())
        self.data = {"version": 1, "run_id": self.run, "parent_thread_id": self.parent,
                     "outcome": "completed", "summary": "Bounded task passed.",
                     "artifacts": [{"path": str(self.artifact), "sha256": receipts.hash_file(self.artifact)}],
                     "checks": [{"name": "fixture acceptance", "result": "pass"}]}

    def write(self, data=None):
        self.path.write_text(json.dumps(self.data if data is None else data), encoding="utf-8")

    def claim(self, **overrides):
        args = dict(receipt=self.path, state_dir=self.state, run_id=self.run,
                    parent_thread=self.parent, artifact_root=self.artifacts)
        args.update(overrides)
        return receipts.claim(**args)

    def reject(self, reason, data=None, **overrides):
        self.write(data)
        with self.assertRaises(receipts.ReceiptError) as result:
            self.claim(**overrides)
        self.assertEqual(result.exception.reason, reason)

    def test_completed_and_duplicate(self):
        self.write()
        self.assertEqual(self.claim()["status"], "claimed")
        self.assertEqual(self.claim()["status"], "duplicate")

    def test_blocked_and_failed(self):
        for outcome in ("blocked", "failed"):
            self.data.update(run_id=str(uuid4()), outcome=outcome, artifacts=[], checks=[])
            self.run = self.data["run_id"]
            self.write()
            result = self.claim()
            self.assertEqual((result["status"], result["outcome"]), ("claimed", outcome))

    def test_wrong_parent_and_run(self):
        self.reject("wrong_run_or_parent", parent_thread=str(uuid4()))
        self.reject("wrong_run_or_parent", run_id=str(uuid4()))

    def test_malformed_ids(self):
        for value in ("../../escape", "", "{" + self.run + "}", self.run.replace("-", ""), None):
            with self.subTest(value=value):
                self.reject("invalid_uuid", run_id=value)

    def test_case_does_not_create_second_claim(self):
        self.write()
        self.assertEqual(self.claim()["status"], "claimed")
        self.assertEqual(self.claim(run_id=self.run.upper(), parent_thread=self.parent.upper())["status"], "duplicate")

    def test_version_and_outcome(self):
        for version in (2, True, "1", None):
            bad = dict(self.data, version=version)
            self.reject("unsupported_version", bad)
        self.reject("unsupported_outcome", dict(self.data, outcome="running"))

    def test_unknown_or_missing_fields(self):
        self.reject("invalid_fields", dict(self.data, command="do something"))
        bad = dict(self.data)
        del bad["checks"]
        self.reject("invalid_fields", bad)

    def test_duplicate_json_keys(self):
        self.path.write_text('{"version":1,' + json.dumps(self.data)[1:], encoding="utf-8")
        with self.assertRaisesRegex(receipts.ReceiptError, "duplicate_json_key"):
            self.claim()

    def test_invalid_json_and_encoding(self):
        for raw in (b'{', b'\xff', b'{"x": NaN}'):
            self.path.write_bytes(raw)
            with self.assertRaisesRegex(receipts.ReceiptError, "invalid_json"):
                self.claim()

    def test_bounded_receipt(self):
        self.path.write_bytes(b" " * (receipts.MAX_RECEIPT_BYTES + 1))
        with self.assertRaisesRegex(receipts.ReceiptError, "json_too_large"):
            self.claim()

    def test_summary(self):
        for summary in ("", "  ", "x" * 2001, [], None):
            self.reject("invalid_summary", dict(self.data, summary=summary))

    def test_proof_required(self):
        for changed in ({"artifacts": []}, {"checks": []},
                        {"checks": [{"name": "acceptance", "result": "fail"}]},
                        {"checks": [{"name": "acceptance", "result": "not_run"}]}):
            self.reject("completion_proof_required", dict(self.data, **changed))

    def test_invalid_check(self):
        self.reject("invalid_check_name", dict(self.data, checks=[{"name": "", "result": "pass"}]))
        self.reject("invalid_check_result", dict(self.data, checks=[{"name": "test", "result": "maybe"}]))
        self.reject("invalid_proof_lists", dict(self.data, checks={}))

    def test_stale_artifact(self):
        self.artifact.write_text("changed", encoding="utf-8")
        self.reject("stale_artifact")

    def test_missing_artifact(self):
        self.artifact.unlink()
        self.reject("missing_or_nonfile_artifact")

    def test_nonfile_artifact(self):
        self.data["artifacts"][0]["path"] = str(self.artifacts)
        self.reject("missing_or_nonfile_artifact")

    def test_root_escape_and_relative_paths(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        self.data["artifacts"][0] = {"path": str(outside), "sha256": receipts.hash_file(outside)}
        self.reject("artifact_outside_root")
        self.data["artifacts"][0]["path"] = "../outside.txt"
        self.reject("absolute_path_required")

    def test_symlink_escape(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link = self.artifacts / "link.txt"
        try:
            link.symlink_to(outside)
        except OSError as error:
            self.skipTest("Host does not permit symlink creation: " + str(error.winerror))
        self.data["artifacts"][0] = {"path": str(link), "sha256": receipts.hash_file(outside)}
        self.reject("artifact_outside_root")

    def test_duplicate_artifact(self):
        self.data["artifacts"].append(copy.deepcopy(self.data["artifacts"][0]))
        self.reject("duplicate_artifact")

    def test_invalid_hash(self):
        self.data["artifacts"][0]["sha256"] = "bad"
        self.reject("invalid_artifact_hash")

    def test_conflicting_receipt(self):
        self.write()
        self.claim()
        self.data["summary"] = "Different result for the same run"
        self.reject("conflicting_receipt")

    def test_cancel_before_claim(self):
        self.assertEqual(receipts.cancel(self.state, self.run, self.parent)["status"], "canceled")
        self.assertEqual(receipts.cancel(self.state, self.run, self.parent)["status"], "already_canceled")
        self.reject("run_canceled")

    def test_cancel_after_claim_preserves_marker(self):
        self.write()
        self.claim()
        marker = self.state / (self.run + ".json")
        before = marker.read_bytes()
        self.assertEqual(receipts.cancel(self.state, self.run, self.parent)["status"], "already_claimed")
        self.assertEqual(marker.read_bytes(), before)

    def test_partial_marker_requires_recovery(self):
        self.state.mkdir()
        marker = self.state / (self.run + ".json")
        marker.write_bytes(b'{"version":')
        self.write()
        with self.assertRaises(receipts.ReceiptError) as result:
            self.claim()
        self.assertTrue(result.exception.recovery)
        self.assertEqual(marker.read_bytes(), b'{"version":')

    def test_concurrent_claims(self):
        self.write()
        def attempt(_):
            try:
                return self.claim()["status"]
            except receipts.ReceiptError as error:
                return error.reason
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(20)))
        self.assertEqual(results.count("claimed"), 1)
        self.assertTrue(set(results) <= {"claimed", "duplicate", "marker_recovery_needed"}, results)

    def test_cli_validation_error_is_json(self):
        self.write()
        result = subprocess.run([sys.executable, receipts.__file__, "claim", "--receipt", str(self.path),
                                 "--state-dir", str(self.state), "--run-id", "invalid", "--parent-thread", self.parent,
                                 "--artifact-root", str(self.artifacts)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason"], "invalid_uuid")
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
