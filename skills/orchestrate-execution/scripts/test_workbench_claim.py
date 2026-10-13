import json
from pathlib import Path
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
from uuid import UUID, uuid4


SCRIPT = Path(__file__).with_name("workbench_claim.py")


class WorkbenchClaimCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"

    def run_cli(self, command, **values):
        args = [sys.executable, str(SCRIPT), command]
        for key, value in values.items():
            args.extend(("--" + key.replace("_", "-"), str(value)))
        args.extend(("--state-dir", str(self.state)))
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            self.fail(f"CLI did not return JSON (exit {result.returncode}): {result.stdout!r}; {result.stderr!r}; {error}")
        self.assertNotIn("Traceback", result.stderr)
        return result.returncode, payload

    def acquire_args(self, chat_id=None, owner_id=None, request_id="run-1", claim_id=None, project_id="g-p-local"):
        return {
            "chat_id": chat_id or str(uuid4()),
            "project_id": project_id,
            "owner_id": owner_id or str(uuid4()),
            "request_id": request_id,
            "claim_id": claim_id or str(uuid4()),
        }

    def test_concurrent_acquires_choose_one_owner_and_chats_are_independent(self):
        chat_id = str(uuid4())
        barrier = Barrier(8)

        def contender(index):
            args = self.acquire_args(chat_id=chat_id, request_id=f"run-{index}")
            barrier.wait(timeout=15)
            return self.run_cli("acquire", **args)

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(contender, range(8)))
        self.assertEqual([code for code, _ in outcomes].count(0), 1, outcomes)
        self.assertEqual([code for code, _ in outcomes].count(2), 7, outcomes)
        self.assertEqual([body["status"] for _, body in outcomes].count("reserved"), 1)
        self.assertEqual([body["status"] for _, body in outcomes].count("busy"), 7)
        winner = next(body for code, body in outcomes if code == 0)
        for code, body in outcomes:
            if code == 2:
                self.assertEqual(body["reservation"], {key: value for key, value in winner.items() if key != "status"})

        first = self.acquire_args()
        second = self.acquire_args()
        self.assertNotEqual(first["chat_id"], second["chat_id"])
        self.assertEqual(self.run_cli("acquire", **first)[0], 0)
        self.assertEqual(self.run_cli("acquire", **second)[0], 0)

    def test_status_does_not_create_storage_and_repeat_acquire_stays_busy(self):
        args = self.acquire_args()
        free_code, free = self.run_cli("status", chat_id=args["chat_id"])
        self.assertEqual((free_code, free), (0, {"status": "free", "chat_id": args["chat_id"]}))
        self.assertFalse(self.state.exists())

        code, reserved = self.run_cli("acquire", **args)
        self.assertEqual(code, 0)
        self.assertEqual(reserved["status"], "reserved")
        busy_code, busy = self.run_cli("status", chat_id=args["chat_id"])
        self.assertEqual(busy_code, 0)
        self.assertEqual(busy, {"status": "busy", "reservation": {key: value for key, value in reserved.items() if key != "status"}})

        repeat_code, repeat = self.run_cli("acquire", **args)
        self.assertEqual(repeat_code, 2)
        self.assertEqual(repeat, busy)

    def test_uppercase_uuid_spellings_resolve_to_the_same_chat(self):
        chat_id = "abcdefab-cdef-abcd-efab-cdefabcdefab"
        args = self.acquire_args(chat_id=chat_id, owner_id="01234567-89ab-cdef-0123-456789abcdef",
                                 claim_id="fedcba98-7654-3210-fedc-ba9876543210")
        code, reserved = self.run_cli("acquire", **args)
        self.assertEqual(code, 0)
        self.assertEqual(reserved["chat_id"], chat_id)

        upper = dict(args, chat_id=chat_id.upper(), owner_id=args["owner_id"].upper(),
                     claim_id=args["claim_id"].upper())
        repeat_code, repeat = self.run_cli("acquire", **upper)
        self.assertEqual(repeat_code, 2)
        self.assertEqual(repeat["status"], "busy")
        self.assertEqual(repeat["reservation"]["chat_id"], chat_id)
        status_code, status = self.run_cli("status", chat_id=chat_id.upper())
        self.assertEqual(status_code, 0)
        self.assertEqual(status["reservation"]["chat_id"], chat_id)

    def test_release_requires_current_identity_and_allows_next_owner(self):
        first = self.acquire_args()
        second = self.acquire_args(chat_id=first["chat_id"], request_id="run-2")
        third = self.acquire_args(chat_id=first["chat_id"], request_id="run-3")
        self.assertEqual(self.run_cli("acquire", **first)[0], 0)

        wrong = dict(first, owner_id=str(uuid4()))
        code, mismatch = self.run_cli("release", chat_id=wrong["chat_id"], owner_id=wrong["owner_id"],
                                      request_id=wrong["request_id"], claim_id=wrong["claim_id"])
        self.assertEqual((code, mismatch["status"]), (3, "mismatch"))
        self.assertEqual(self.run_cli("status", chat_id=first["chat_id"])[1]["status"], "busy")

        self.assertEqual(self.run_cli("release", chat_id=first["chat_id"], owner_id=first["owner_id"],
                                      request_id=first["request_id"], claim_id=first["claim_id"])[0], 0)
        self.assertEqual(self.run_cli("acquire", **second)[0], 0)

        stale_code, stale = self.run_cli("release", chat_id=first["chat_id"], owner_id=first["owner_id"],
                                         request_id=first["request_id"], claim_id=first["claim_id"])
        self.assertEqual((stale_code, stale["status"]), (3, "mismatch"))
        current = self.run_cli("status", chat_id=first["chat_id"])[1]
        self.assertEqual(current["reservation"]["claim_id"], str(UUID(second["claim_id"])))

        self.assertEqual(self.run_cli("release", chat_id=second["chat_id"], owner_id=second["owner_id"],
                                      request_id=second["request_id"], claim_id=second["claim_id"])[0], 0)
        self.assertEqual(self.run_cli("acquire", **third)[0], 0)

    def test_malformed_identifiers_are_rejected_before_storage_use(self):
        good = self.acquire_args()
        cases = (
            ("acquire", dict(good, chat_id="not-a-uuid"), "invalid_uuid"),
            ("acquire", dict(good, project_id="bad\nproject"), "invalid_project_id"),
            ("acquire", dict(good, owner_id="{}"), "invalid_uuid"),
            ("acquire", dict(good, request_id="bad/request"), "invalid_request_id"),
            ("acquire", dict(good, claim_id="bad"), "invalid_uuid"),
            ("status", {"chat_id": "not-a-uuid"}, "invalid_uuid"),
            ("release", {"chat_id": good["chat_id"], "owner_id": good["owner_id"],
                          "request_id": "bad request", "claim_id": good["claim_id"]}, "invalid_request_id"),
        )
        for command, values, reason in cases:
            with self.subTest(command=command, reason=reason):
                code, payload = self.run_cli(command, **values)
                self.assertEqual(code, 2)
                self.assertEqual(payload, {"status": "rejected", "reason": reason})
                self.assertFalse(self.state.exists())

    def test_corrupt_database_fails_closed_and_preserves_original_bytes(self):
        self.state.mkdir()
        database = self.state / "claims.sqlite3"
        original = b"not a sqlite database\x00\xff"
        database.write_bytes(original)
        args = self.acquire_args()
        operations = (
            ("acquire", args),
            ("status", {"chat_id": args["chat_id"]}),
            ("release", {"chat_id": args["chat_id"], "owner_id": args["owner_id"],
                          "request_id": args["request_id"], "claim_id": args["claim_id"]}),
        )
        for command, values in operations:
            with self.subTest(command=command):
                code, payload = self.run_cli(command, **values)
                self.assertEqual(code, 4)
                self.assertEqual(payload["status"], "error")
                self.assertEqual(payload["reason"], "storage_corrupt")
                self.assertEqual(database.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
