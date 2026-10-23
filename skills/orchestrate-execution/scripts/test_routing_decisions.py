from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import routing_decisions as router

_REAL_PROCESS_RUN = subprocess.run


def _process_is_running(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# A fixed normalized adviser receipt, independent of the compiler under test.
KNOWN_COMPLETE_REPORT = {
    "status": "complete",
    "provider": "openai",
    "attempted_call": True,
    "elapsed_seconds": 0.15,
    "model": "gpt-6-luna",
    "answers": {
        "small": {
            "type": "choice",
            "status": "answered",
            "choice": "worker_luna",
            "probabilities": [
                {"value": "hold", "probability": 0.1},
                {"value": "owner", "probability": 0.1},
                {"value": "worker_luna", "probability": 0.7},
                {"value": "worker_sol", "probability": 0.1},
            ],
            "confidence": 0.8,
            "confidence_semantics": "separate_provider_field",
        },
        "broad": {
            "type": "choice",
            "status": "answered",
            "choice": "worker_sol",
            "probabilities": [
                {"value": "hold", "probability": 0.1},
                {"value": "owner", "probability": 0.1},
                {"value": "worker_luna", "probability": 0.1},
                {"value": "worker_sol", "probability": 0.7},
            ],
            "confidence": 0.8,
            "confidence_semantics": "separate_provider_field",
        },
        "owner_case": {
            "type": "choice",
            "status": "answered",
            "choice": "owner",
            "probabilities": [
                {"value": "hold", "probability": 0.1},
                {"value": "owner", "probability": 0.7},
                {"value": "worker_luna", "probability": 0.1},
                {"value": "worker_sol", "probability": 0.1},
            ],
            "confidence": 0.8,
            "confidence_semantics": "separate_provider_field",
        },
    },
    "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    "error": None,
}


class RoutingDecisionsCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.py"
        self.source.write_text("def source(): return 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def task(
        self,
        task_id: str,
        *,
        authorized: bool = True,
        export_approved: bool = True,
        inputs_ready: bool = True,
    ) -> dict[str, object]:
        return {
            "id": task_id,
            "objective": f"Objective for {task_id}",
            "context": f"Context for {task_id}",
            "allowed_files": [str(self.source.resolve())],
            "checks": [f"Check {task_id}"],
            "authorized": authorized,
            "export_approved": export_approved,
            "inputs_ready": inputs_ready,
        }

    def batch_file(
        self,
        name: str,
        tasks: list[dict[str, object]],
        *,
        coordinator_id: str = "coordinator-42",
    ) -> Path:
        path = self.root / name
        batch = {
            "schema_version": 1,
            "coordinator_id": coordinator_id,
            "tasks": tasks,
        }
        path.write_text(json.dumps(batch, ensure_ascii=True), encoding="utf-8")
        return path

    def report_bytes(self, task_ids: list[str] | None = None) -> bytes:
        report = copy.deepcopy(KNOWN_COMPLETE_REPORT)
        if task_ids is not None:
            report["answers"] = {
                task_id: copy.deepcopy(KNOWN_COMPLETE_REPORT["answers"][task_id])
                for task_id in task_ids
            }
        return (json.dumps(report, ensure_ascii=True, separators=(",", ":")) + "\n").encode()

    def invoke_run(
        self,
        batch_path: Path,
        run_dir: Path,
        *,
        stdout: bytes | None = None,
        returncode: int = 0,
        side_effect: object | None = None,
        summary: bool = False,
    ) -> tuple[int, str, str, unittest.mock.Mock]:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=self.report_bytes() if stdout is None else stdout,
            stderr=b"ignored child diagnostics",
        )
        child = patch.object(router.subprocess, "run", return_value=completed)
        mocked = child.start()
        self.addCleanup(child.stop)
        if side_effect is not None:
            mocked.side_effect = side_effect
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch.object(
            socket, "socket", side_effect=AssertionError("network access in test")
        ):
            argv = ["run", str(batch_path), str(run_dir)]
            if summary:
                argv.append("--summary")
            code = router.main(argv)
        return code, out.getvalue(), err.getvalue(), mocked

    def run_success(self, batch_path: Path, run_dir: Path, report: bytes) -> bytes:
        code, output, error, child = self.invoke_run(batch_path, run_dir, stdout=report)
        self.assertEqual(code, 0, error)
        child.assert_called_once()
        return output.encode("ascii")

    def cli_error(self, args: list[str]) -> tuple[int, dict[str, object]]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch.object(
            socket, "socket", side_effect=AssertionError("network access in test")
        ):
            code = router.main(args)
        self.assertEqual(out.getvalue(), "")
        return code, json.loads(err.getvalue())

    def invoke_emit(
        self, batch_path: Path, run_dir: Path, *, summary: bool = False
    ) -> tuple[int, str, str, unittest.mock.Mock]:
        out = io.StringIO()
        err = io.StringIO()
        child = patch.object(router.subprocess, "run")
        mocked = child.start()
        self.addCleanup(child.stop)
        with redirect_stdout(out), redirect_stderr(err), patch.object(
            socket, "socket", side_effect=AssertionError("network access in test")
        ):
            argv = ["emit", str(batch_path), str(run_dir)]
            if summary:
                argv.append("--summary")
            code = router.main(argv)
        return code, out.getvalue(), err.getvalue(), mocked

    def write_readiness_session(
        self,
        path: Path,
        *,
        session_id: str = "01a1b94c-9a2d-7e11-a6ef-000000000001",
        parent_thread_id: str = "coordinator-42",
        agent_path: str = "/root/compact_routing",
        session_cwd: str | None = None,
        turn_cwd: str | None = None,
        model: str = "gpt-6-luna",
        effort: str = "max",
        approval_policy: str = "never",
        sandbox_type: str = "danger-full-access",
        source: object | None = None,
        legacy_agent_path: str | None = None,
        include_session: bool = True,
        turn_contexts: list[dict[str, object]] | None = None,
        extra_lines: list[dict[str, object]] | None = None,
    ) -> None:
        session_cwd = str(self.root) if session_cwd is None else session_cwd
        turn_cwd = str(self.root) if turn_cwd is None else turn_cwd
        records: list[dict[str, object]] = []
        if include_session:
            if source is None:
                source = {
                    "subagent": {
                        "thread_spawn": {
                            "parent_thread_id": parent_thread_id,
                            "agent_path": agent_path,
                        }
                    }
                }
            payload: dict[str, object] = {
                "id": session_id,
                "cwd": session_cwd,
                "source": source,
            }
            if legacy_agent_path is not None:
                payload["agent_path"] = legacy_agent_path
            records.append(
                {
                    "type": "session_meta",
                    "payload": payload,
                }
            )
        if turn_contexts is None:
            turn_contexts = [
                {
                    "type": "turn_context",
                    "payload": {
                        "turn_id": "turn-2",
                        "cwd": turn_cwd,
                        "model": model,
                        "effort": effort,
                        "approval_policy": approval_policy,
                        "sandbox_policy": {"type": sandbox_type},
                    },
                }
            ]
        records.extend(turn_contexts)
        records.extend(extra_lines or [])
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=True) + "\n" for record in records),
            encoding="utf-8",
        )

    def invoke_readiness(
        self,
        batch_path: Path,
        run_dir: Path,
        session_path: Path,
        *,
        cwd: str | None = None,
        worker_kind: str | None = None,
        agent_path: str | None = "/root/compact_routing",
        parent_thread: str = "coordinator-42",
        thread_id: str = "01a1b94c-9a2d-7e11-a6ef-000000000001",
    ) -> tuple[int, dict[str, object], str]:
        out = io.StringIO()
        err = io.StringIO()
        argv = [
            "readiness",
            str(batch_path),
            str(run_dir),
            str(session_path),
            "--task-id",
            "small",
            "--thread-id",
            thread_id,
            "--parent-thread",
            parent_thread,
            "--cwd",
            str(self.root) if cwd is None else cwd,
        ]
        if worker_kind is not None:
            argv.extend(["--worker-kind", worker_kind])
        if agent_path is not None:
            argv.extend(["--agent-path", agent_path])
        with redirect_stdout(out), redirect_stderr(err), patch.object(
            socket, "socket", side_effect=AssertionError("network access in test")
        ):
            code = router.main(argv)
        result_text = out.getvalue() or err.getvalue()
        return code, json.loads(result_text), err.getvalue()

    @staticmethod
    def same_object_path_alias(directory: Path) -> str:
        if os.name == "nt":
            return str(directory).swapcase()
        return str(directory) + os.sep + "."

    def windows_short_path_alias(self, directory: Path) -> str:
        import ctypes
        from ctypes import wintypes

        get_short_path_name = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
        get_short_path_name.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short_path_name.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        result = get_short_path_name(str(directory), buffer, len(buffer))
        self.assertNotEqual(result, 0, f"GetShortPathNameW failed with {ctypes.get_last_error()}")
        alias = buffer.value
        self.assertNotEqual(
            os.path.normcase(alias), os.path.normcase(str(directory)),
            "the filesystem did not expose a real 8.3 alias for this directory",
        )
        self.assertIn("~", Path(alias).name, "GetShortPathNameW did not return an 8.3 basename")
        self.assertTrue(Path(alias).samefile(directory), "the returned short path is not the same directory")
        return alias

    def make_delivery_run(self, *, include_owner: bool = False, include_hold: bool = False):
        parent_thread = str(uuid4())
        tasks = [self.task("small")]
        report_ids = ["small"]
        if include_owner:
            tasks.append(self.task("owner_case"))
            report_ids.append("owner_case")
        if include_hold:
            tasks.append(self.task("held_case", authorized=False))
        batch = self.batch_file(
            "delivery-batch.json", tasks, coordinator_id=parent_thread
        )
        run_dir = self.root / "runs" / "delivery"
        self.run_success(batch, run_dir, self.report_bytes(report_ids))
        artifact_root = self.root / "evidence"
        artifact_root.mkdir()
        return batch, run_dir, parent_thread, artifact_root

    def invoke_delivery(
        self,
        batch: Path,
        run_dir: Path,
        *,
        task_id: str = "small",
        run_id: str | None = None,
        receipt: Path,
        artifact_root: Path,
        output: Path,
        callback_authorized: bool = True,
    ):
        argv = [
            "delivery",
            str(batch),
            str(run_dir),
            "--task-id",
            task_id,
            "--run-id",
            str(uuid4()) if run_id is None else run_id,
            "--receipt",
            str(receipt),
            "--artifact-root",
            str(artifact_root),
            "--output",
            str(output),
        ]
        if callback_authorized:
            argv.append("--callback-authorized")
        out = io.StringIO()
        err = io.StringIO()
        with patch.object(router.subprocess, "run") as provider, redirect_stdout(out), redirect_stderr(err), patch.object(
            socket, "socket", side_effect=AssertionError("network access in test")
        ):
            code = router.main(argv)
        return code, out.getvalue(), err.getvalue(), provider

    def trail_cli(self, command, batch, run_dir, *options):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch.object(router.subprocess, "run") as provider, patch.object(
            socket, "socket", side_effect=AssertionError("network access in test")
        ):
            code = router.main([command, str(batch), str(run_dir), *map(str, options)])
        provider.assert_not_called()
        self.last_cli_stdout = out.getvalue()
        return code, json.loads(out.getvalue() or err.getvalue())

    def action_input(self, delivery, name, **fields):
        evidence = self.root / "owner-proof.txt"
        if not evidence.exists():
            evidence.write_text("Owner inspected exact dispatched assignment and downstream outcome.\n", encoding="utf-8")
        refs = [{"path": str(evidence), "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]
        record = {"schema_version": 1, "task_id": delivery["task_id"],
                  "owner_id": delivery["parent_thread_id"], "run_id": delivery["run_id"],
                  "action_id": delivery["action_id"], "packet_sha256": delivery["source_packet"]["sha256"],
                  "assignment_message": delivery["assignment_message"], "reason": "Observed exact action", "evidence": refs, **fields}
        path = self.root / name
        path.write_text(json.dumps(record), encoding="utf-8")
        return path, refs

    def dispatch_input(self, delivery, name):
        path, _ = self.action_input(delivery, name)
        session = self.root / (name + ".jsonl")
        thread = str(uuid4())
        self.write_readiness_session(session, session_id=thread, source="vscode",
            parent_thread_id=delivery["parent_thread_id"], model=delivery["model"], effort=delivery["reasoning_effort"])
        data = json.loads(path.read_bytes())
        data["readiness"] = {"session_path": str(session), "thread_id": thread, "cwd": str(self.root), "worker_kind": "app", "agent_path": None}
        path.write_text(json.dumps(data))
        return path

    def prepare_request(self, parent, root):
        session = root / "session.jsonl"
        thread = str(uuid4())
        self.write_readiness_session(session, session_id=thread, source="vscode", parent_thread_id=parent,
                                     model="gpt-6-luna", effort="max")
        evidence = root / "ready-proof.txt"
        evidence.write_text("Visibility, input-read and worker access were verified.")
        request = {"schema_version": 1, "task_id": "small", "run_id": str(uuid4()),
                   "receipt": str(root / "receipt.json"), "artifact_root": str(root),
                   "reason": "Dispatch verified bounded assignment", "callback_authorized": True,
                   "evidence": [{"path": str(evidence), "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
                   "readiness": {"session_path": str(session), "thread_id": thread, "cwd": str(self.root),
                                 "worker_kind": "app", "agent_path": None}}
        path = root / "owner-request.json"
        path.write_text(json.dumps(request))
        return path, request

    def step_task(self, task_id="triage", boundary="resume_triage"):
        ref = {"id": "local_source", "path": str(self.source), "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}
        return {"id": task_id, "kind": "coordinator_step", "boundary": boundary, "goal": "Choose a useful supported follow-up.",
                "facts": [{"id": "gap", "text": "Two outcome gaps remain.", "evidence_ids": ["local_source"]}],
                "evidence": [ref], "candidates": [
                    {"id": "repair", "description": "Inspect the implementation outcome first.", "fact_ids": ["gap"],
                     "plan": {"kind": "inspect_evidence", "instructions": "LOCAL_PRIVATE_PLAN_CANARY: inspect the named result.", "evidence_ids": ["local_source"], "existing_record_id": None}},
                    {"id": "measurement", "description": "Inspect the measurement outcome first.", "fact_ids": ["gap"],
                     "plan": {"kind": "record_interpretation", "instructions": "Keep the measurement coverage unknown until linked.", "evidence_ids": ["local_source"], "existing_record_id": None}}],
                "authorized": True, "export_approved": True, "inputs_ready": True, "authority_evidence_ids": ["local_source"]}

    def step_batch(self, tasks=None, name="step.json", owner=None):
        path = self.root / name
        path.write_text(json.dumps({"schema_version": 3, "coordinator_id": owner or str(uuid4()), "tasks": tasks or [self.step_task()]}, ensure_ascii=False), encoding="utf-8")
        return path

    def step_report(self, choice="c0", questions=1):
        report = {"status": "complete", "provider": "openai", "attempted_call": True, "elapsed_seconds": 0.2, "model": "gpt-6-luna", "answers": {},
                  "usage": {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12}, "error": None}
        for i in range(questions):
            report["answers"][f"q{i}"] = {"type": "choice", "status": "answered", "choice": choice,
                  "probabilities": [{"value": "c0", "probability": 0.6}, {"value": "c1", "probability": 0.3}, {"value": "hold", "probability": 0.1}],
                  "confidence": 0.01, "confidence_semantics": "separate_provider_field"}
        return json.dumps(report).encode()

    def make_step(self, boundary="resume_triage"):
        batch = self.step_batch([self.step_task(boundary=boundary)])
        run = self.root / "step-run"
        code, out, err, child = self.invoke_run(batch, run, stdout=self.step_report())
        self.assertEqual(code, 0, err); self.assertEqual(child.call_count, 1)
        return batch, run, json.loads(out)

    def step_apply(self, batch, run, name="apply.json"):
        owner = json.loads(batch.read_bytes())["coordinator_id"]
        record = {"schema_version": 2, "owner_id": owner, "task_id": "triage", "run_id": str(uuid4()), "artifact_root": str(self.root),
                  "reason": "Use selected evidence plan", "evidence": [{"path": str(self.source), "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}]}
        path = self.root / name; path.write_text(json.dumps(record))
        code, result = self.trail_cli("apply-step", batch, run, "--task-id", "triage", "--record", path)
        self.assertEqual(code, 0, result)
        return path, result, json.loads(Path(result["step_path"]).read_bytes())

    def step_settlement(self, step, applied, *, accepted=True, state="completed", name="settlement.json"):
        result = self.root / (name + "-result.json")
        result.write_text(json.dumps({"finding": "Inspected the actual local result; acceptance remains unknown.", "action_id": step["action_id"]}))
        ref = {"path": str(result), "sha256": hashlib.sha256(result.read_bytes()).hexdigest()}
        use = self.root / (name + "-use.json")
        use.write_text(json.dumps({"schema_version": 1, "kind": "coordinator_step_use", **{k: step[k] for k in ("owner_id", "task_id", "action_id", "candidate_id", "plan_sha256")},
                                  "consumer": "coordinator_task", "used_at": "2026-10-20T16:00:00Z", "result_evidence": [ref]}))
        use_ref = {"path": str(use), "sha256": hashlib.sha256(use.read_bytes()).hexdigest()}
        record = {**{k: step[k] for k in ("schema_version", "owner_id", "task_id", "action_id", "run_id", "packet_sha256", "plan_sha256")},
                  "step_artifact": {"path": applied["step_path"], "sha256": applied["step_sha256"]}, "reason": "Observed the selected local step", "evidence": [ref],
                  "observation": {"state": state, "use_evidence": [use_ref] if state in {"used", "completed", "interrupted"} else []},
                  "acceptance": {"accepted": accepted, "reason": "Owner checked selected result", "evidence": [ref],
                     "eliminated_stages": [{"stage": "evidence_triage", "reason": "Used the saved selected plan", "evidence": [ref]}]}}
        path = self.root / name; path.write_text(json.dumps(record))
        return path, record

    def test_step_choice_projection_and_exact_plan_are_consumable_at_three_boundaries(self):
        for boundary in ("next_action", "resume_triage", "analytics_interpretation"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as folder:
                self.root = Path(folder); self.source = self.root / "source_PRIVATE_PATH_CANARY.py"; self.source.write_text("PRIVATE_CODE_CANARY")
                batch, run, packet = self.make_step(boundary)
                self.assertEqual(packet["kind"], "coordinator_step"); self.assertEqual(packet["schema_version"], 2)
                item = packet["tasks"][0]
                self.assertEqual((item["status"],item["candidate_id"]),("recommended","repair"))
                self.assertEqual(item["plan"], self.step_task(boundary=boundary)["candidates"][0]["plan"])
                self.assertNotIn("assignment_message", item); self.assertNotIn("route", item)
                request = json.loads((run / "request.json").read_bytes())
                state, questions = router.adviser._validate_request(request)
                wire = router.adviser._encode_payload(router.adviser._provider_payload("openai",state,questions))
                for text in ((run/"request.json").read_bytes(),wire):
                    for secret in (b"PRIVATE_PATH_CANARY",b"PRIVATE_CODE_CANARY",b"LOCAL_PRIVATE_PLAN_CANARY",b"local_source",b'"triage"',b'"repair"'):
                        self.assertNotIn(secret,text)
                _, applied, step = self.step_apply(batch,run)
                self.assertIs(step["execution_authority"],False)
                export = router.export_adoption(run)
                self.assertEqual(export["opportunities"][0]["actions"][0]["confirmed_use"],False)
                path, record = self.step_settlement(step,applied)
                record["acceptance"]["eliminated_stages"][0]["stage"] = {"next_action":"next_action_selection","resume_triage":"evidence_triage","analytics_interpretation":"analytics_interpretation"}[boundary]
                path.write_text(json.dumps(record))
                code, result = self.trail_cli("settle-step",batch,run,"--task-id","triage","--record",path)
                self.assertEqual(code,0,result)
                action = router.export_adoption(run)["opportunities"][0]["actions"][0]
                self.assertTrue(action["confirmed_use"]); self.assertIs(action["acceptance"]["accepted"],True)

    def test_prepare_step_consumes_selected_plan_without_credit_or_replay(self):
        # Public consumer owns plan preparation; existing settlement tests own
        # lifecycle validation. A summary must never become downstream proof.
        batch, run, packet = self.make_step()
        request, _, _ = self.step_apply(batch, run)
        # A separately applied step is already pending and cannot be prepared again.
        with patch.object(router.subprocess, 'run') as child:
            code, pending = self.trail_cli('prepare-step', batch, run, '--task-id', 'triage')
            self.assertEqual(code, 0, pending)
            self.assertEqual(pending['status'], 'pending')
            self.assertIsNone(pending['plan'])
            self.assertFalse(pending['execution_authority'])
            self.assertEqual(self.trail_cli('prepare-step', batch, run, '--task-id', 'triage', '--record', request)[0], 2)
            child.assert_not_called()
        with tempfile.TemporaryDirectory() as folder:
            self.root = Path(folder); self.source = self.root/'source.py'; self.source.write_text('actual input')
            batch, run, packet = self.make_step()
            request = self.root/'apply.json'
            request.write_text(json.dumps({'schema_version': 2, 'owner_id': packet['coordinator_id'], 'task_id': 'triage',
                'run_id': str(uuid4()), 'artifact_root': str(self.root), 'reason': 'Inspect selected evidence',
                'evidence': [{'path': str(self.source), 'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()}]}))
            with patch.object(router.subprocess, 'run') as child:
                code, prepared = self.trail_cli('prepare-step', batch, run, '--task-id', 'triage', '--record', request)
                self.assertEqual(code, 0, prepared); child.assert_not_called()
            self.assertEqual(prepared['status'], 'prepared')
            self.assertEqual(prepared['plan'], packet['tasks'][0]['plan'])
            self.assertEqual(prepared['candidate_id'], 'repair')
            self.assertEqual(prepared['sources']['authority_evidence_ids'], ['local_source'])
            self.assertEqual(prepared['sources']['sha256'], hashlib.sha256((run/'batch-snapshot.json').read_bytes()).hexdigest())
            self.assertLessEqual(len(router._json_bytes(prepared)), 4096)
            applied = {'step_path': prepared['step_artifact']['path'], 'step_sha256': prepared['step_artifact']['sha256']}
            step = json.loads(Path(applied['step_path']).read_bytes())
            copy_path = self.root/'copied-preparation.json'; copy_path.write_text(json.dumps(prepared, indent=3))
            settlement, record = self.step_settlement(step, applied)
            self.step_link_result(settlement, record, copy_path)
            code, result = self.trail_cli('settle-step', batch, run, '--task-id', 'triage', '--record', settlement)
            self.assertEqual((code, result.get('category')), (2, 'step_use_invalid'), result)
            action = router.export_adoption(run)['opportunities'][0]['actions'][0]
            self.assertFalse(action['confirmed_use']); self.assertIsNone(action['acceptance'])
            settlement, _ = self.step_settlement(step, applied, name='actual.json')
            self.assertEqual(self.trail_cli('settle-step', batch, run, '--task-id', 'triage', '--record', settlement)[0], 0)
            with patch.object(router.subprocess, 'run') as child:
                code, reused = self.trail_cli('prepare-step', batch, run, '--task-id', 'triage')
                self.assertEqual(code, 0, reused); child.assert_not_called()
            self.assertEqual(reused['status'], 'already_consumed')
            self.assertEqual(reused['state'], 'completed'); self.assertIsNone(reused['plan'])
            self.assertEqual(reused['action_id'], step['action_id'])
            self.source.write_text('source mismatch')
            code, result = self.trail_cli('prepare-step', batch, run, '--task-id', 'triage')
            self.assertEqual((code, result.get('category')), (2, 'source_drift'))

    def test_prepare_step_oversized_projection_leaves_no_application(self):
        # A valid step and apply record can have metadata larger than stdout's
        # budget. Size rejection must precede the exclusive application claim.
        nested = self.root / ('\u00e9' * 100) / ('\u00e9' * 100)
        nested.mkdir(parents=True)
        batch = self.step_batch(); run = nested / 'run'; artifacts = nested / 'artifacts'
        artifacts.mkdir()
        code, _, err, _ = self.invoke_run(batch, run, stdout=self.step_report())
        self.assertEqual(code, 0, err)
        owner = json.loads(batch.read_bytes())['coordinator_id']
        request = self.root / 'apply.json'
        request.write_text(json.dumps({'schema_version': 2, 'owner_id': owner, 'task_id': 'triage',
            'run_id': str(uuid4()), 'artifact_root': str(artifacts), 'reason': 'Inspect retained evidence',
            'evidence': [{'path': str(self.source), 'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()}]}))
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(router.subprocess, 'run') as child:
            code, result = self.trail_cli('prepare-step', batch, run, '--task-id', 'triage', '--record', request)
            self.assertEqual((code, result.get('category')), (2, 'step_summary_too_large'), result)
            child.assert_not_called()
        row = router.export_adoption(run)['opportunities'][0]
        self.assertEqual(row['actions'], [])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_prepare_step_direct_hold_and_unknown_remain_offline(self):
        for disposition in ('direct', 'hold', 'unknown', 'interrupted'):
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as folder:
                self.root = Path(folder); self.source = self.root/'source.py'; self.source.write_text('input')
                task = self.step_task()
                if disposition == 'direct':
                    task.update(candidates=task['candidates'][:1], export_approved=False)
                    task['candidates'][0]['plan']['instructions'] = '\u00e9' * 1024
                if disposition == 'hold': task.update(inputs_ready=False)
                batch = self.step_batch([task]); run = self.root/'run'
                code, _, err, _ = self.invoke_run(batch, run, stdout=self.step_report())
                self.assertEqual(code, 0, err)
                if disposition in ('unknown', 'interrupted'):
                    _, applied, step = self.step_apply(batch, run)
                    settlement, record = self.step_settlement(step, applied, state=disposition, accepted=None)
                    record['acceptance'] = None; settlement.write_text(json.dumps(record))
                    self.assertEqual(self.trail_cli('settle-step', batch, run, '--task-id', 'triage', '--record', settlement)[0], 0)
                before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
                with patch.object(router.subprocess, 'run') as child:
                    code, result = self.trail_cli('prepare-step', batch, run, '--task-id', 'triage')
                    self.assertEqual(code, 0, result); child.assert_not_called()
                self.assertEqual(result['state'], disposition if disposition in ('unknown', 'interrupted') else 'unapplied')
                self.assertEqual(result['status'], disposition if disposition in ('direct', 'hold') else 'already_consumed' if disposition == 'interrupted' else 'pending')
                if disposition == 'direct':
                    self.assertEqual(result['plan']['kind'], 'inspect_evidence')
                    self.assertNotIn('instructions', result['plan'])
                    saved = json.loads(Path(result['selection']['path']).read_bytes())
                    self.assertEqual(saved['tasks'][0]['plan']['instructions'], '\u00e9' * 1024)
                    self.assertIn('instructions_pointer', result)
                    self.assertLessEqual(len(router._json_bytes(result)), 4096)
                else:
                    self.assertIsNone(result['plan'])
                self.assertFalse(result['execution_authority'])
                self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_step_local_admission_and_hold_require_no_provider(self):
        for index, (change,status) in enumerate([
            (lambda t:t.update(authorized=False),"hold"),(lambda t:t.update(inputs_ready=False),"hold"),
            (lambda t:t.update(export_approved=False),"hold"),(lambda t:t.update(candidates=[]),"hold"),
            (lambda t:t.update(candidates=t["candidates"][:1],export_approved=False),"direct"),
            (lambda t:t.update(local_disposition={"route":"hold","reason":"Owner prerequisites unresolved"}),"hold")]):
            task = self.step_task(f"case{index}");change(task)
            batch=self.step_batch([task],name=f"local-{index}.json");run=self.root/f"local-{index}"
            code,out,err,child=self.invoke_run(batch,run,summary=True)
            self.assertEqual(code,0,err);child.assert_not_called();self.assertLessEqual(len(out.encode()),4096)
            self.assertEqual(json.loads(out)["tasks"][0]["status"],status)
            self.assertFalse((run/"submission-intent.json").exists())

    def test_step_malformed_inputs_reject_before_submission(self):
        mutations=[lambda t:t["facts"][0].update(evidence_ids=["missing"]),lambda t:t["candidates"][0].update(extra=True),
                   lambda t:t["facts"][0].update(text="\u00e9"*81),lambda t:t["candidates"].append(t["candidates"][0]),
                   lambda t:t["candidates"][0]["plan"].update(command="do something"),lambda t:t["facts"][0].update(text="\ud800")]
        for i, mutate in enumerate(mutations):
            task=self.step_task();mutate(task);batch=self.step_batch([task],name=f"invalid-{i}.json") if i!=5 else self.root/'unicode.json'
            if i==5:batch.write_text(json.dumps({"schema_version":3,"coordinator_id":str(uuid4()),"tasks":[task]}))
            run=self.root/f"invalid-run-{i}";code,_,_,child=self.invoke_run(batch,run)
            self.assertEqual(code,2);child.assert_not_called();self.assertFalse(run.exists())
    def test_step_invalid_returns_preserve_failure_and_hold_is_not_applicable(self):
        for i, mutate in enumerate([lambda r:r.update(status="partial"),lambda r:r.update(provider="other"),
                                   lambda r:r["answers"]["q0"].update(choice="execute_shell")]):
            report=json.loads(self.step_report());mutate(report);batch=self.step_batch([self.step_task(f"bad{i}")],name=f"bad{i}.json");run=self.root/f"bad{i}"
            code,_,_,child=self.invoke_run(batch,run,stdout=json.dumps(report).encode())
            self.assertEqual(code,2);child.assert_called_once();self.assertTrue((run/"provider-return.json").exists());self.assertFalse((run/"packets.json").exists())
            row=router.export_adoption(run)["opportunities"][0];self.assertTrue(row["eligible"]);self.assertEqual(row["decision"]["status"],"rejected");self.assertEqual(row["actions"],[])
        batch=self.step_batch(name="hold.json");run=self.root/"hold-run"
        code,out,err,_=self.invoke_run(batch,run,stdout=self.step_report("hold"));self.assertEqual(code,0,err)
        self.assertIsNone(json.loads(out)["tasks"][0]["plan"])
        code,result=self.trail_cli("apply-step",batch,run,"--task-id","triage","--record",self.root/"does-not-exist.json")
        self.assertEqual((code,result["category"]),(2,"step_not_applicable"))

    def test_step_offline_reuse_replay_and_wrong_kind_hold(self):
        batch,run,packet=self.make_step()
        code,result=self.trail_cli("emit",batch,run,"--summary")
        self.assertEqual(code,0,result);self.assertEqual(result["tasks"][0]["candidate_id"],"repair")
        code,_,_,child=self.invoke_run(batch,self.root/"same-revision-new-run",stdout=self.step_report())
        self.assertEqual(code,2);child.assert_not_called()
        for command in ("delivery","dispatch","readiness","resume","observe","accept","prepare-dispatch"):
            code,result=self.trail_cli(command,batch,run)
            self.assertEqual((code,result["category"]),(2,"wrong_decision_kind"))
        wb,wr,_,_=self.make_delivery_run()
        code,result=self.trail_cli("apply-step",wb,wr,"--task-id","small","--record",self.root/"missing-apply.json")
        self.assertEqual((code,result["category"]),(2,"wrong_decision_kind"))
        code,result=self.trail_cli("prepare-step",wb,wr,"--task-id","small")
        self.assertEqual((code,result["category"]),(2,"wrong_decision_kind"))
        self.source.write_text("Changed actual input")
        code,result=self.trail_cli("apply-step",batch,run,"--task-id","triage","--record",self.root/"not-created")
        self.assertEqual(code,2);self.assertEqual(result["category"],"source_drift")

    def test_step_application_losses_and_concurrency_cannot_reapply(self):
        for loss in ("step","claim","reservation","accepted_decision","packet","attempt","registration"):
            with self.subTest(loss=loss),tempfile.TemporaryDirectory() as folder:
                self.root=Path(folder);self.source=self.root/"source.py";self.source.write_text("source")
                batch,run,_=self.make_step();request,applied,step=self.step_apply(batch,run)
                row=router.export_adoption(run)["opportunities"][0];trail=Path(row["trail_path"])
                target={"step":Path(applied["step_path"]),"claim":trail/"claim-000000.json","reservation":trail/"000000/reservation.json","accepted_decision":run/"decision-accepted.json","packet":run/"packets.json","attempt":next(trail.glob("attempt-*.json")),"registration":trail/"registration.json"}[loss]
                target.unlink();code,_=self.trail_cli("apply-step",batch,run,"--task-id","triage","--record",request)
                self.assertEqual(code,2)
                self.assertEqual(self.trail_cli("prepare-step",batch,run,"--task-id","triage")[0],2)
                exported=router.export_adoption(run)["opportunities"][0];self.assertTrue(exported["eligible"]);self.assertEqual(exported["action_coverage"]["status"],"unresolved")
        with tempfile.TemporaryDirectory() as folder:
            from concurrent.futures import ThreadPoolExecutor
            self.root=Path(folder);self.source=self.root/"source.py";self.source.write_text("source")
            batch,run,_=self.make_step();owner=json.loads(batch.read_bytes())["coordinator_id"]
            request=self.root/'apply.json';request.write_text(json.dumps({"schema_version":2,"owner_id":owner,"task_id":"triage","run_id":str(uuid4()),"artifact_root":str(self.root),"reason":"Use result","evidence":[{"path":str(self.source),"sha256":hashlib.sha256(self.source.read_bytes()).hexdigest()}]}))
            def apply():
                try:return router.apply_step(batch,run,"triage",request)["status"]
                except (router.RoutingError,OSError):return "held"
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:apply(),range(2)))
            self.assertEqual(results.count("prepared"),1);self.assertEqual(results.count("held"),1)

    def test_step_use_and_acceptance_are_distinct_and_history_loss_holds(self):
        batch,run,_=self.make_step();_,applied,step=self.step_apply(batch,run)
        path,record=self.step_settlement(step,applied,accepted=None)
        broken=copy.deepcopy(record);broken["observation"]["use_evidence"]=[];bad=self.root/'bad-use.json';bad.write_text(json.dumps(broken))
        code,_=self.trail_cli("settle-step",batch,run,"--task-id","triage","--record",bad);self.assertEqual(code,2)
        invalid=copy.deepcopy(record);invalid["acceptance"]["eliminated_stages"][0]["stage"]="route_classification"
        bad.write_text(json.dumps(invalid));self.assertEqual(self.trail_cli("settle-step",batch,run,"--task-id","triage","--record",bad)[0],2)
        code,result=self.trail_cli("settle-step",batch,run,"--task-id","triage","--record",path);self.assertEqual(code,0,result)
        code,result=self.trail_cli("settle-step",batch,run,"--task-id","triage","--record",path);self.assertEqual(code,0,result);self.assertEqual(result["status"],"duplicate")
        record["observation"]=None;record["acceptance"]["accepted"]=True;path=self.root/'accept-later.json';path.write_text(json.dumps(record))
        code,result=self.trail_cli("settle-step",batch,run,"--task-id","triage","--record",path);self.assertEqual(code,0,result)
        record["acceptance"]["accepted"]=False;bad.write_text(json.dumps(record));code,_=self.trail_cli("settle-step",batch,run,"--task-id","triage","--record",bad);self.assertEqual(code,2)
        row=router.export_adoption(run)["opportunities"][0];directory=Path(row["trail_path"])/'000000'
        (directory/'event-000002.json').unlink()
        row=router.export_adoption(run)["opportunities"][0]
        self.assertEqual(row["action_coverage"]["status"],"unresolved");self.assertEqual(row["actions"],[])


    def test_step_true_acceptance_requires_one_matching_evidenced_stage(self):
        cases = (("true-empty", True, False, 2), ("true-evidenced", True, True, 0),
                 ("false-empty", False, False, 0), ("unknown-empty", None, False, 0))
        for name, accepted, include_stage, expected_code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                self.root = Path(folder); self.source = self.root / "source.py"
                self.source.write_text("source", encoding="utf-8")
                boundary = "resume_triage"
                batch, run, _ = self.make_step(boundary)
                _, applied, step = self.step_apply(batch, run)
                path, record = self.step_settlement(step, applied, accepted=accepted, name=name + ".json")
                if include_stage:
                    record["acceptance"]["eliminated_stages"] = [{
                        "stage": router.STEP_STAGES[boundary],
                        "reason": "Used the saved selected plan",
                        "evidence": record["acceptance"]["evidence"],
                    }]
                else:
                    record["acceptance"]["eliminated_stages"] = []
                path.write_text(json.dumps(record), encoding="utf-8")
                code, result = self.trail_cli("settle-step", batch, run, "--task-id", "triage", "--record", path)
                self.assertEqual(code, expected_code, result)
                if expected_code:
                    self.assertEqual(result["category"], "stage_evidence_invalid")
                    continue
                self.assertEqual(result["status"], "recorded")
                action = router.export_adoption(run)["opportunities"][0]["actions"][0]
                self.assertIs(action["acceptance"]["accepted"], accepted)


    def test_step_selected_task_isolation_retains_full_packet_binding(self):
        first=self.step_task();second=self.step_task('sibling');other=self.root/'other.txt';other.write_text('Other source')
        second['evidence'][0].update(path=str(other),sha256=hashlib.sha256(other.read_bytes()).hexdigest())
        batch=self.step_batch([first,second]);run=self.root/'siblings'
        code,_,err,_=self.invoke_run(batch,run,stdout=self.step_report(questions=2));self.assertEqual(code,0,err)
        other.write_text('Sibling changed after selection')
        _,applied,_=self.step_apply(batch,run);self.assertEqual(applied['status'],'prepared')
        code,result=self.trail_cli('emit',batch,run);self.assertEqual((code,result['category']),(2,'source_drift'))

    def test_step_settlement_intent_holds_failure_before_final_marker(self):
        batch,run,_=self.make_step();request,applied,step=self.step_apply(batch,run);path,_=self.step_settlement(step,applied)
        original=router._write_new
        def interrupted(target,raw):
            if target.name=='published-000001.json':raise OSError('interrupted append')
            return original(target,raw)
        with patch.object(router,'_write_new',side_effect=interrupted):
            code,_=self.trail_cli('settle-step',batch,run,'--task-id','triage','--record',path)
        self.assertNotEqual(code,0)
        row=router.export_adoption(run)['opportunities'][0]
        self.assertEqual(row['action_coverage']['status'],'unresolved');self.assertEqual(row['actions'],[])
        directory=Path(row['trail_path'])/'000000';before={p.name:p.read_bytes() for p in directory.iterdir()}
        self.assertEqual(self.trail_cli('settle-step',batch,run,'--task-id','triage','--record',path)[0],2)
        self.assertEqual(self.trail_cli('apply-step',batch,run,'--task-id','triage','--record',request)[0],2)
        self.assertEqual(before,{p.name:p.read_bytes() for p in directory.iterdir()})
        null_paths={Path(r['path']).name for r in row['action_coverage']['frontier']['required'] if r['sha256'] is None}
        self.assertEqual(null_paths,{'event-000001.json','published-000001.json'})

    def test_step_downstream_copy_and_identity_forgery_cannot_count_as_use(self):
        batch,run,_=self.make_step();_,applied,step=self.step_apply(batch,run)
        for name,change in [('copied-plan',lambda use,result:result.write_text(json.dumps(step['plan']))),
                           ('wrong-owner',lambda use,result:use.update(owner_id=str(uuid4()))),
                           ('self-result',lambda use,result:use.update(result_evidence=[{'path':applied['step_path'],'sha256':applied['step_sha256']}]))]:
            path,record=self.step_settlement(step,applied,name=name+'.json')
            usepath=Path(record['observation']['use_evidence'][0]['path']);use=json.loads(usepath.read_bytes());result=Path(use['result_evidence'][0]['path'])
            change(use,result)
            if name!='self-result':use['result_evidence'][0]['sha256']=hashlib.sha256(result.read_bytes()).hexdigest()
            usepath.write_text(json.dumps(use));record['observation']['use_evidence'][0]['sha256']=hashlib.sha256(usepath.read_bytes()).hexdigest()
            # The owner evidence remains valid independently of the rejected use record.
            record['evidence']=[{'path':str(self.source),'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest()}]
            path.write_text(json.dumps(record));code,_=self.trail_cli('settle-step',batch,run,'--task-id','triage','--record',path);self.assertEqual(code,2)
        row=router.export_adoption(run)['opportunities'][0];self.assertEqual(row['actions'][0]['state'],'pending');self.assertFalse(row['actions'][0]['confirmed_use'])

    def test_step_preparation_artifacts_and_copies_cannot_count_as_use(self):
        # Owner: settle-step's downstream-use boundary. Preparation alone must
        # never earn use/acceptance; CLI settlement and exported state expose it.
        names = ['reservation', 'claim', 'registration', 'attempt', 'step',
                 'manifest.json', 'batch-snapshot.json', 'opportunities.json',
                 'request.json', 'submission-intent.json', 'child-result.json',
                 'provider-return.json', 'packets.json', 'decision-accepted.json']
        for name in names + ['external-result']:
            for copied in (False, True):
                with self.subTest(name=name, copied=copied), tempfile.TemporaryDirectory() as folder:
                    self.root = Path(folder); self.source = self.root/'source.py'
                    self.source.write_text('source', encoding='utf-8')
                    batch, run, _ = self.make_step(); _, applied, step = self.step_apply(batch, run)
                    row = router.export_adoption(run)['opportunities'][0]
                    trail = Path(row['trail_path'])
                    paths = {'reservation': trail/'000000/reservation.json',
                             'claim': trail/'claim-000000.json',
                             'registration': trail/'registration.json',
                             'attempt': next(trail.glob('attempt-*.json')),
                             'step': Path(applied['step_path'])}
                    path, record = self.step_settlement(step, applied)
                    usepath = Path(record['observation']['use_evidence'][0]['path'])
                    use = json.loads(usepath.read_bytes())
                    result = (Path(use['result_evidence'][0]['path']) if name == 'external-result'
                              else paths.get(name, run/name))
                    self.assertTrue(result.is_file(), str(result))
                    if copied:
                        value = json.loads(result.read_bytes()); result = self.root/'copied.json'
                        result.write_text(json.dumps(value, indent=3, sort_keys=True), encoding='utf-8')
                    ref = {'path': str(result), 'sha256': hashlib.sha256(result.read_bytes()).hexdigest()}
                    use['result_evidence'] = [ref]; usepath.write_text(json.dumps(use), encoding='utf-8')
                    record['observation']['use_evidence'][0]['sha256'] = hashlib.sha256(usepath.read_bytes()).hexdigest()
                    record['evidence'] = [ref]; record['acceptance']['evidence'] = [ref]
                    record['acceptance']['eliminated_stages'][0]['evidence'] = [ref]
                    path.write_text(json.dumps(record), encoding='utf-8')
                    code, result = self.trail_cli('settle-step', batch, run, '--task-id', 'triage', '--record', path)
                    self.assertEqual(code, 0 if name == 'external-result' else 2, result)
                    action = router.export_adoption(run)['opportunities'][0]['actions'][0]
                    self.assertEqual(action['confirmed_use'], name == 'external-result')
                    self.assertEqual(action['state'], 'completed' if name == 'external-result' else 'pending')

    def step_link_result(self, path, record, result):
        ref = {'path': str(result), 'sha256': hashlib.sha256(result.read_bytes()).hexdigest()}
        usepath = Path(record['observation']['use_evidence'][0]['path'])
        use = json.loads(usepath.read_bytes()); use['result_evidence'] = [ref]
        usepath.write_text(json.dumps(use), encoding='utf-8')
        record['observation']['use_evidence'][0]['sha256'] = hashlib.sha256(usepath.read_bytes()).hexdigest()
        record['evidence'] = [ref]; record['acceptance']['evidence'] = [ref]
        record['acceptance']['eliminated_stages'][0]['evidence'] = [ref]
        path.write_text(json.dumps(record), encoding='utf-8')

    def test_step_public_apply_summary_copies_cannot_settle(self):
        for reformatted in (False, True):
            with self.subTest(reformatted=reformatted), tempfile.TemporaryDirectory() as folder:
                self.root = Path(folder); self.source = self.root/'source.py'; self.source.write_text('source')
                batch, run, _ = self.make_step(); _, applied, step = self.step_apply(batch, run)
                public_stdout = self.last_cli_stdout.encode('ascii')
                self.assertEqual(json.loads(public_stdout), applied)
                result = self.root/'external-inspection.json'
                result.write_bytes(json.dumps(json.loads(public_stdout), indent=3, sort_keys=True).encode()
                                   if reformatted else public_stdout)
                path, record = self.step_settlement(step, applied)
                self.step_link_result(path, record, result)
                code, outcome = self.trail_cli('settle-step', batch, run, '--task-id', 'triage', '--record', path)
                self.assertEqual((code, outcome.get('category')), (2, 'step_use_invalid'), outcome)
                row = router.export_adoption(run)['opportunities'][0]; action = row['actions'][0]
                self.assertEqual(action['state'], 'pending'); self.assertFalse(action['confirmed_use'])
                self.assertIsNone(action['acceptance'])
                self.assertFalse((Path(row['trail_path'])/'000000/settlement-000000.json').exists())

    def test_step_external_typed_receipt_result_can_settle(self):
        batch, run, _ = self.make_step(); _, applied, step = self.step_apply(batch, run)
        result = self.root/'actual-inspection-receipt.json'
        source_bytes = self.source.read_bytes()
        result.write_text(json.dumps({'version': 1, 'outcome': 'completed',
            'artifacts': [{'path': str(self.source), 'sha256': hashlib.sha256(source_bytes).hexdigest()}],
            'checks': [{'name': 'inspected source bytes', 'result': 'pass'}],
            'inspection': {'bytes': len(source_bytes), 'lines': len(source_bytes.splitlines())}}))
        path, record = self.step_settlement(step, applied)
        self.step_link_result(path, record, result)
        code, outcome = self.trail_cli('settle-step', batch, run, '--task-id', 'triage', '--record', path)
        self.assertEqual(code, 0, outcome)
        action = router.export_adoption(run)['opportunities'][0]['actions'][0]
        self.assertTrue(action['confirmed_use']); self.assertEqual(action['state'], 'completed')
        self.assertIs(action['acceptance']['accepted'], True)

    def test_step_swapped_same_owner_continuation_delivery_is_rejected(self):
        # Owner: immutable delivery join. A valid different opportunity must not
        # replace the saved selection even with the same owner and real dispatch.
        wb, wr, owner, root = self.make_delivery_run()
        deliveries = []
        for index in (0, 1):
            if index:
                other_task = self.task('small'); other_task['objective'] = 'Different worker opportunity'
                wb = self.batch_file('other-worker.json', [other_task], coordinator_id=owner)
                wr = self.root/'other-worker-run'; self.run_success(wb, wr, self.report_bytes(['small']))
            target = root/f'delivery-{index}.json'
            code, out, err, _ = self.invoke_delivery(wb, wr, receipt=root/f'receipt-{index}.json', artifact_root=root, output=target)
            self.assertEqual(code, 0, (out, err))
            delivery = json.loads(target.read_bytes())
            self.assertEqual(self.trail_cli('dispatch', wb, wr, '--task-id', 'small', '--record', self.dispatch_input(delivery, f'send-{index}.json'))[0], 0)
            observed, _ = self.action_input(delivery, f'interrupted-{index}.json', state='interrupted')
            self.assertEqual(self.trail_cli('observe', wb, wr, '--task-id', 'small', '--record', observed)[0], 0)
            deliveries.append(target)
            if not index:
                task = self.step_task(); task['evidence'].append({'id': 'original', 'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
                task['candidates'][0]['plan'].update(kind='continue_existing', existing_record_id='original', evidence_ids=['original'])
                batch = self.step_batch([task], owner=owner); run = self.root/'continuation-decision'
                code, _, err, _ = self.invoke_run(batch, run, stdout=self.step_report()); self.assertEqual(code, 0, err)
                _, applied, step = self.step_apply(batch, run)
        feedback, _ = self.action_input(delivery, 'other-feedback.json')
        continued_path = root/'other-continued.json'
        code, result = self.trail_cli('resume', wb, wr, '--task-id', 'small', '--run-id', str(uuid4()), '--receipt', root/'other-continued-receipt.json', '--artifact-root', root, '--output', continued_path, '--callback-authorized', '--reason', 'Complete existing correction', '--record', feedback)
        self.assertEqual(code, 0, result); continued = json.loads(continued_path.read_bytes())
        code, dispatch = self.trail_cli('dispatch', wb, wr, '--task-id', 'small', '--record', self.dispatch_input(continued, 'other-continued-send.json'))
        self.assertEqual(code, 0, dispatch)
        observed, _ = self.action_input(continued, 'other-continued-observed.json', state='dispatched')
        self.assertEqual(self.trail_cli('observe', wb, wr, '--task-id', 'small', '--record', observed)[0], 0)
        deliveries[0].write_bytes(deliveries[1].read_bytes())
        path, record = self.step_settlement(step, applied, name='swapped-use.json')
        usepath = Path(record['observation']['use_evidence'][0]['path']); use = json.loads(usepath.read_bytes())
        resultpath = Path(use['result_evidence'][0]['path']); resultpath.write_text(json.dumps(dispatch), encoding='utf-8')
        ref = {'path': str(resultpath), 'sha256': hashlib.sha256(resultpath.read_bytes()).hexdigest()}
        use.update(consumer='existing_continuation', result_evidence=[ref]); usepath.write_text(json.dumps(use), encoding='utf-8')
        record['observation']['use_evidence'][0]['sha256'] = hashlib.sha256(usepath.read_bytes()).hexdigest()
        record['evidence'] = [ref]; record['acceptance']['evidence'] = [ref]
        record['acceptance']['eliminated_stages'][0]['evidence'] = [ref]; path.write_text(json.dumps(record), encoding='utf-8')
        code, result = self.trail_cli('settle-step', batch, run, '--task-id', 'triage', '--record', path)
        self.assertEqual(code, 2, result)
        self.assertIn('step_continuation_invalid', str(result))
        action = router.export_adoption(run)['opportunities'][0]['actions'][0]
        self.assertFalse(action['confirmed_use']); self.assertEqual(action['state'], 'pending')

    def test_step_unknown_reconciliation_never_erases_confirmed_use(self):
        batch,run,_=self.make_step();_,applied,step=self.step_apply(batch,run)
        path,record=self.step_settlement(step,applied,state='used',name='used.json');record['acceptance']=None;path.write_text(json.dumps(record))
        self.assertEqual(self.trail_cli('settle-step',batch,run,'--task-id','triage','--record',path)[0],0)
        path,record=self.step_settlement(step,applied,state='unknown',name='unknown.json');record['acceptance']=None;path.write_text(json.dumps(record))
        self.assertEqual(self.trail_cli('settle-step',batch,run,'--task-id','triage','--record',path)[0],0)
        path,record=self.step_settlement(step,applied,state='not_used',accepted=False,name='not-used.json');path.write_text(json.dumps(record))
        self.assertEqual(self.trail_cli('settle-step',batch,run,'--task-id','triage','--record',path)[0],2)
        path,record=self.step_settlement(step,applied,accepted=False,name='rejected.json');path.write_text(json.dumps(record))
        self.assertEqual(self.trail_cli('settle-step',batch,run,'--task-id','triage','--record',path)[0],0)
        action=router.export_adoption(run)['opportunities'][0]['actions'][0]
        self.assertTrue(action['confirmed_use']);self.assertIs(action['acceptance']['accepted'],False)
        with tempfile.TemporaryDirectory() as folder:
            self.root=Path(folder);self.source=self.root/"source.py";self.source.write_text("source",encoding="utf-8")
            batch,run,_=self.make_step();_,applied,step=self.step_apply(batch,run)
            path,record=self.step_settlement(step,applied,state="unknown",name="never-confirmed.json");record["acceptance"]=None;path.write_text(json.dumps(record),encoding="utf-8")
            self.assertEqual(self.trail_cli("settle-step",batch,run,"--task-id","triage","--record",path)[0],0)
            path,_=self.step_settlement(step,applied,state="not_used",accepted=False,name="confirmed-unused.json")
            self.assertEqual(self.trail_cli("settle-step",batch,run,"--task-id","triage","--record",path)[0],0)
            action=router.export_adoption(run)["opportunities"][0]["actions"][0]
            self.assertFalse(action["confirmed_use"]);self.assertEqual(action["state"],"not_used")


    def test_step_continuation_uses_existing_owner_and_retains_historical_use_after_source_change(self):
        if os.name == "nt":
            self.root = Path(self.windows_short_path_alias(self.root))
        wb,wr,parent,root=self.make_delivery_run();delivery_path=root/'delivery.json'
        self.assertEqual(self.invoke_delivery(wb,wr,receipt=root/'receipt.json',artifact_root=root,output=delivery_path)[0],0)
        original=json.loads(delivery_path.read_bytes())
        task=self.step_task();task['evidence'].append({'id':'original','path':str(delivery_path),'sha256':hashlib.sha256(delivery_path.read_bytes()).hexdigest()})
        task['candidates'][0]['plan'].update(kind='continue_existing',existing_record_id='original',evidence_ids=['original'])
        sibling = copy.deepcopy(task); sibling['id'] = 'unapplied'
        batch=self.step_batch([task, sibling],owner=parent);run=self.root/'continuation-decision'
        code,_,_,child=self.invoke_run(batch,run,stdout=self.step_report())
        self.assertEqual(code,2);child.assert_not_called();self.assertFalse(run.exists())
        self.assertEqual(self.trail_cli('dispatch',wb,wr,'--task-id','small','--record',self.dispatch_input(original,'original-send.json'))[0],0)
        observed,_=self.action_input(original,'original-interrupted.json',state='interrupted')
        self.assertEqual(self.trail_cli('observe',wb,wr,'--task-id','small','--record',observed)[0],0)
        code,_,err,_=self.invoke_run(batch,run,stdout=self.step_report(questions=2));self.assertEqual(code,0,err)
        with patch.object(router.subprocess, 'run') as child:
            code, selected = self.trail_cli('prepare-step', batch, run, '--task-id', 'triage')
            self.assertEqual(code, 0, selected); child.assert_not_called()
        self.assertEqual(selected['continuation'], {'delivery': {**task['evidence'][1], 'path': str(delivery_path.resolve(strict=True))}, 'action_id': original['action_id'],
            'task_id': 'small', 'next_operation': 'prepare-dispatch', 'mode': 'offline_reuse'})
        self.assertEqual(selected['plan'], task['candidates'][0]['plan'])
        _,applied,step=self.step_apply(batch,run)
        feedback,_=self.action_input(original,'feedback.json')
        continued_path=root/'continued.json'
        code,result=self.trail_cli('resume',wb,wr,'--task-id','small','--run-id',str(uuid4()),'--receipt',root/'continued-receipt.json','--artifact-root',root,'--output',continued_path,'--callback-authorized','--reason','Complete the existing correction','--record',feedback)
        self.assertEqual(code,0,result);continued=json.loads(continued_path.read_bytes())
        code,dispatch=self.trail_cli('dispatch',wb,wr,'--task-id','small','--record',self.dispatch_input(continued,'continued-send.json'));self.assertEqual(code,0,dispatch)
        observed,_=self.action_input(continued,'continued-observed.json',state='dispatched')
        self.assertEqual(self.trail_cli('observe',wb,wr,'--task-id','small','--record',observed)[0],0)
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(router.subprocess, 'run') as child:
            code, reconciled = self.trail_cli('prepare-step', batch, run, '--task-id', 'triage')
            self.assertEqual(code, 0, reconciled); child.assert_not_called()
        self.assertEqual((reconciled['status'], reconciled['state']), ('pending', 'pending'))
        self.assertIsNone(reconciled['plan']); self.assertEqual(reconciled['action_id'], step['action_id'])
        self.assertFalse(reconciled['execution_authority'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        # Fresh validation still rejects the stale delivery: reconciliation is
        # read-only and grants neither a replacement application nor execution.
        code, blocked = self.trail_cli('apply-step', batch, run, '--task-id', 'triage', '--record', self.root/'apply.json')
        self.assertEqual((code, blocked.get('category')), (2, 'step_continuation_pending'))
        code, blocked = self.trail_cli('emit', batch, run)
        self.assertEqual((code, blocked.get('category')), (2, 'step_continuation_pending'))
        code, blocked = self.trail_cli('prepare-step', batch, run, '--task-id', 'unapplied')
        self.assertEqual((code, blocked.get('category')), (2, 'step_continuation_pending'))
        path,record=self.step_settlement(step,applied,name='continued-use.json')
        usepath=Path(record['observation']['use_evidence'][0]['path']);use=json.loads(usepath.read_bytes());resultpath=Path(use['result_evidence'][0]['path']);resultpath.write_text(json.dumps(dispatch));ref={'path':str(resultpath),'sha256':hashlib.sha256(resultpath.read_bytes()).hexdigest()}
        use.update(consumer='existing_continuation',result_evidence=[ref]);usepath.write_text(json.dumps(use));record['observation']['use_evidence'][0]['sha256']=hashlib.sha256(usepath.read_bytes()).hexdigest()
        record['evidence']=[ref];record['acceptance']['evidence']=[ref];record['acceptance']['eliminated_stages'][0]['evidence']=[ref];path.write_text(json.dumps(record))
        self.assertEqual(self.trail_cli('settle-step',batch,run,'--task-id','triage','--record',path)[0],0)
        code, reconciled = self.trail_cli('prepare-step', batch, run, '--task-id', 'triage')
        self.assertEqual(code, 0, reconciled)
        self.assertEqual((reconciled['status'], reconciled['state']), ('already_consumed', 'completed'))
        self.assertIsNone(reconciled['plan']); self.assertEqual(reconciled['action_id'], step['action_id'])
        self.source.write_text('A later implementation changed the allowed source')
        data=router.export_adoption(run);router.validate_step_export(data)
        self.assertTrue(data['opportunities'][0]['actions'][0]['confirmed_use'])
        for row in data["opportunities"]:
            paths = [ref["path"] for ref in row["evidence"]]
            self.assertEqual(len(paths), len(set(paths)))
        duplicate = copy.deepcopy(data)
        duplicate["opportunities"][0]["evidence"].append(copy.deepcopy(duplicate["opportunities"][0]["evidence"][0]))
        with self.assertRaisesRegex(router.RoutingError, "step_export_invalid"):
            router.validate_step_export(duplicate)
        worker_export = router.export_adoption(wr)
        for row in worker_export["opportunities"]:
            paths = [ref["path"] for ref in row["evidence"]]
            self.assertEqual(len(paths), len(set(paths)))
        changed_hash = copy.deepcopy(data)
        changed_hash["opportunities"][0]["evidence"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(router.RoutingError, "step_export_invalid"):
            router.validate_step_export(changed_hash)


    def test_step_exact_serialized_unicode_limit_has_a_valid_control(self):
        for size in (32768,32769):
            tasks=[self.step_task(f'bounded{i}') for i in range(8)]
            def request_bytes():
                questions={}
                for i,task in enumerate(tasks):
                    fmap={f['id']:f'f{j}' for j,f in enumerate(task['facts'])}
                    instructions=json.dumps({'boundary':task['boundary'],'goal':task['goal'],'facts':[{'id':fmap[f['id']],'text':f['text']} for f in task['facts']],
                        'candidate_facts':{f'c{j}':[fmap[f] for f in c['fact_ids']] for j,c in enumerate(task['candidates'])}},ensure_ascii=False,separators=(',',':'))
                    choices={f'c{j}':c['description'] for j,c in enumerate(task['candidates'])};choices['hold']='Hold because the approved facts do not support choosing an option.'
                    questions[f'q{i}']={'type':'choice','instructions':instructions,'choices':choices}
                return (json.dumps({'state':router.STEP_STATE,'questions':questions},ensure_ascii=True,sort_keys=True,separators=(',',':'))+'\n').encode('ascii')
            for task in tasks:
                task['facts']=[{'id':f'fact{j}','text':'\u00e9','evidence_ids':['local_source']} for j in range(8)]
                task['candidates'][0]['fact_ids']=['fact0'];task['candidates'][1]['fact_ids']=['fact1']
            while len(request_bytes())+384<=size:
                for task in tasks:
                    for fact in task['facts']:fact['text']+='\u00e9'
            remaining=size-len(request_bytes())
            for task in tasks:
                padding=min(remaining,256-len(task['goal'].encode()));task['goal']+='a'*padding;remaining-=padding
            self.assertEqual(remaining,0);self.assertEqual(len(request_bytes()),size)
            batch=self.root/f'byte-{size}.json';batch.write_text(json.dumps({'schema_version':3,'coordinator_id':str(uuid4()),'tasks':tasks},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
            self.assertLess(batch.stat().st_size,32768)
            run=self.root/f'byte-run-{size}';code,_,err,child=self.invoke_run(batch,run,stdout=self.step_report(questions=8))
            if size==32768:
                self.assertEqual(code,0,err);child.assert_called_once();self.assertEqual((run/'request.json').stat().st_size,size)
                req=json.loads((run/'request.json').read_bytes());state,questions=router.adviser._validate_request(req)
                self.assertLessEqual(len(router.adviser._encode_payload(router.adviser._provider_payload('openai',state,questions))),32768)
            else:
                self.assertEqual(code,2);child.assert_not_called();self.assertFalse(run.exists())


    def test_prepare_dispatch_cli_saves_exact_send_once_and_holds_publication_loss(self):
        batch, run, parent, root = self.make_delivery_run()
        request, data = self.prepare_request(parent, root)
        # Exercise the real process CLI, with no provider available or needed.
        argv = [sys.executable, "-B", str(router.ROUTER_PATH), "prepare-dispatch", str(batch), str(run), "--record", str(request)]
        result = _REAL_PROCESS_RUN(argv, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        compact = json.loads(result.stdout)
        self.assertEqual(compact["status"], "dispatch_once")
        self.assertNotIn("assignment_message", compact)
        artifacts = compact["artifacts"]
        proof_path = Path(artifacts["dispatch"]["path"])
        proof = json.loads(proof_path.read_bytes())
        send = json.loads(Path(artifacts["send_input"]["path"]).read_bytes())
        self.assertEqual(send["assignment_message"], proof["assignment_message"])
        self.assertEqual(hashlib.sha256(proof["assignment_message"].encode()).hexdigest(), compact["assignment_message_sha256"])
        for ref in artifacts.values():
            self.assertEqual(hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest(), ref["sha256"])
        # Lost proof after consumption cannot be recreated by retrying preparation.
        proof_path.unlink()
        again = _REAL_PROCESS_RUN(argv, capture_output=True)
        self.assertEqual(again.returncode, 2)
        self.assertFalse(proof_path.exists())
        self.assertEqual(self.trail_cli("dispatch", batch, run, "--task-id", "small", "--record", artifacts["send_input"]["path"])[0], 2)

    def test_native_prepare_dispatch_uses_final_delivery(self):
        batch, run, parent, root = self.make_delivery_run()
        request, data = self.prepare_request(parent, root)
        ready = data["readiness"]
        ready["worker_kind"] = "native"
        ready["agent_path"] = "/root/compact_routing"
        self.write_readiness_session(Path(ready["session_path"]),
            session_id=ready["thread_id"], parent_thread_id=parent,
            model="gpt-6-luna", effort="max")
        request.write_text(json.dumps(data))
        code, result = self.trail_cli("prepare-dispatch", batch, run, "--record", request)
        self.assertEqual(code, 0, result)
        delivery = json.loads(Path(result["artifacts"]["delivery"]["path"]).read_bytes())
        message = delivery["assignment_message"]
        self.assertIn("native final-result delivery", message)
        self.assertNotIn("send exactly one user-authorized callback", message)
        self.assertIn(data["run_id"], message)
        expected_receipt = str(Path(data["receipt"]).parent.resolve(strict=True) / Path(data["receipt"]).name)
        self.assertEqual(delivery["receipt"], expected_receipt)
        self.assertIn(expected_receipt, message)
        self.assertEqual(self.trail_cli("prepare-dispatch", batch, run, "--record", request)[0], 2)
        interrupted, _ = self.action_input(delivery, "native-interrupted.json", state="interrupted")
        self.assertEqual(self.trail_cli("observe", batch, run, "--task-id", "small", "--record", interrupted)[0], 0)
        evidence, _ = self.action_input(delivery, "native-continuation.json")
        continued = root / "native-continued.json"
        code, result = self.trail_cli("resume", batch, run, "--task-id", "small",
            "--run-id", str(uuid4()), "--receipt", root / "native-continued-receipt.json",
            "--artifact-root", root, "--output", continued, "--callback-authorized",
            "--worker-kind", "native", "--reason", "Finish same assignment with original budget", "--record", evidence)
        self.assertEqual(code, 0, result)
        resumed = json.loads(continued.read_bytes())
        self.assertIn("native final-result delivery", resumed["assignment_message"])
        self.assertNotIn("send exactly one user-authorized callback", resumed["assignment_message"])
        self.assertEqual(resumed["source_packet"], delivery["source_packet"])

    def test_dispatch_cli_accepts_same_directory_session_cwd_alias(self) -> None:
        batch, run, parent, root = self.make_delivery_run()
        output = root / "dispatch-identity-delivery.json"
        code, _stdout, error, _provider = self.invoke_delivery(
            batch, run, receipt=root / "dispatch-identity-receipt.json",
            artifact_root=root, output=output,
        )
        self.assertEqual(code, 0, error)
        delivery = json.loads(output.read_bytes())
        request = self.dispatch_input(delivery, "dispatch-identity-send.json")
        record = json.loads(request.read_bytes())
        ready = record["readiness"]
        expected_cwd = self.root / "dispatch-identity-working-directory"
        expected_cwd.mkdir()
        alias = self.same_object_path_alias(expected_cwd)
        ready["cwd"] = str(expected_cwd)
        self.write_readiness_session(
            Path(ready["session_path"]),
            session_id=ready["thread_id"],
            parent_thread_id=parent,
            source="vscode",
            session_cwd=alias,
            turn_cwd=str(expected_cwd),
            model=delivery["model"],
            effort=delivery["reasoning_effort"],
        )
        request.write_text(json.dumps(record), encoding="utf-8")

        code, dispatched = self.trail_cli(
            "dispatch", batch, run, "--task-id", "small", "--record", request
        )
        self.assertEqual(code, 0, dispatched)
        self.assertEqual(dispatched["assignment_message"], delivery["assignment_message"])

    def test_prepare_dispatch_accepts_same_directory_turn_cwd_alias(self) -> None:
        batch, run, parent, root = self.make_delivery_run()
        request, data = self.prepare_request(parent, root)
        ready = data["readiness"]
        expected_cwd = self.root / "prepare-identity-working-directory"
        expected_cwd.mkdir()
        alias = self.same_object_path_alias(expected_cwd)
        ready["cwd"] = str(expected_cwd)
        self.write_readiness_session(
            Path(ready["session_path"]),
            session_id=ready["thread_id"],
            parent_thread_id=parent,
            source="vscode",
            session_cwd=str(expected_cwd),
            turn_cwd=alias,
            model="gpt-6-luna",
            effort="max",
        )
        request.write_text(json.dumps(data), encoding="utf-8")

        code, prepared = self.trail_cli(
            "prepare-dispatch", batch, run, "--record", request
        )
        self.assertEqual(code, 0, prepared)
        self.assertEqual(prepared["status"], "dispatch_once")
        self.assertEqual(prepared["task_id"], "small")

    def test_prepare_rejects_invalid_inputs_before_launch_state_and_single_concurrent_winner(self):
        batch, run, parent, root = self.make_delivery_run()
        path, original = self.prepare_request(parent, root)
        for field, value, category in (
                ("extra", True, "prepare_request_invalid"),
                ("reason", "", "prepare_request_invalid"),
                ("callback_authorized", False, "prepare_request_invalid"),
                ("mode", [], "prepare_request_invalid"),
                ("readiness", {}, "dispatch_readiness_required"),
                ("readiness", {**original["readiness"], "thread_id": str(uuid4())}, "dispatch_readiness_blocked"),
                ("receipt", original["evidence"][0]["path"], "delivery_path_exists")):
            with self.subTest(field=field, value=value):
                path.write_text(json.dumps({**original, field: value}))
                code, error = self.trail_cli("prepare-dispatch", batch, run, "--record", path)
                self.assertEqual((code, error["category"]), (2, category))
                self.assertFalse(list(root.glob("prepare-*")))
        path.write_text(json.dumps(original))
        from concurrent.futures import ThreadPoolExecutor
        argv = [sys.executable, "-B", str(router.ROUTER_PATH), "prepare-dispatch", str(batch), str(run), "--record", str(path)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: _REAL_PROCESS_RUN(argv, capture_output=True), range(2)))
        self.assertEqual(sorted(r.returncode for r in results), [0, 2])

    def test_continuation_payload_rejects_invalid_before_reservation_and_legacy_delivers_refs(self):
        batch, run, parent, root = self.make_delivery_run()
        output = root / "delivery.json"
        self.assertEqual(self.invoke_delivery(batch, run, receipt=root / "receipt.json", artifact_root=root, output=output)[0], 0)
        delivery = json.loads(output.read_bytes())
        record, _ = self.action_input(delivery, "not-sent.json", state="not_sent")
        self.assertEqual(self.trail_cli("observe", batch, run, "--task-id", "small", "--record", record)[0], 0)
        record, refs = self.action_input(delivery, "correction.json")
        base = json.loads(record.read_bytes())
        options = ("--task-id", "small", "--run-id", str(uuid4()), "--receipt", root / "next-receipt.json",
                   "--artifact-root", root, "--output", root / "next.json", "--callback-authorized",
                   "--reason", "Fix the retained correction", "--record", record)
        for payload in (None, "text", {}, {"instructions": ""}, {"instructions": "x"*8001},
                        {"instructions": "Fix", "expected_artifacts": "wrong"},
                        {"instructions": "Fix", "expected_artifacts": [str(self.root / "escape.json")]},
                        {"instructions": "Fix", "expected_artifacts": [str(root / "bad\0path")]},
                        {"instructions": "Fix", "expected_artifacts": [3]}):
            with self.subTest(payload=str(payload)[:80]):
                record.write_text(json.dumps({**base, "continuation": payload}))
                self.assertEqual(self.trail_cli("resume", batch, run, *options)[0], 2)
                self.assertFalse((root / "next.json").exists())
        record.write_text(json.dumps(base))
        self.assertEqual(self.trail_cli("resume", batch, run, *options)[0], 0)
        message = json.loads((root / "next.json").read_bytes())["assignment_message"]
        self.assertIn("Fix the retained correction", message)
        self.assertIn(refs[0]["path"], message)
        self.assertIn(refs[0]["sha256"], message)
        continued = json.loads((root / "next.json").read_bytes())
        not_sent, _ = self.action_input(continued, "continued-not-sent.json", state="not_sent")
        self.assertEqual(self.trail_cli("observe", batch, run, "--task-id", "small", "--record", not_sent)[0], 0)
        request_path, request = self.prepare_request(parent, root)
        request.update(mode="offline_reuse", receipt=str(root / "third-receipt.json"),
                       continuation={"instructions": "Apply the exact retained correction.",
                                     "expected_artifacts": [str(root / "fixed.json")]})
        request_path.write_text(json.dumps(request))
        code, result = self.trail_cli("prepare-dispatch", batch, run, "--record", request_path)
        self.assertEqual(code, 0, result)
        dispatched = json.loads(Path(result["artifacts"]["dispatch"]["path"]).read_bytes())
        self.assertIn(request["continuation"]["instructions"], dispatched["assignment_message"])

    def test_prepare_publication_interruption_and_stale_source_cannot_return_another_launch(self):
        batch, run, parent, root = self.make_delivery_run()
        path, original = self.prepare_request(parent, root)
        raw = self.source.read_bytes()
        self.source.write_text("source drift")
        code, result = self.trail_cli("prepare-dispatch", batch, run, "--record", path)
        self.assertEqual((code, result["category"]), (2, "source_drift"))
        self.assertFalse(list(root.glob("prepare-*")))
        self.source.write_bytes(raw)
        delivery_write = router._write_delivery
        def interrupted(path, raw):
            if path.name.endswith(".dispatch.json"):
                raise router.RoutingError("delivery_write_failed")
            delivery_write(path, raw)
        with patch.object(router, "_write_delivery", side_effect=interrupted):
            code, result = self.trail_cli("prepare-dispatch", batch, run, "--record", path)
        self.assertEqual((code, result["category"]), (2, "delivery_write_failed"))
        self.assertEqual(self.trail_cli("prepare-dispatch", batch, run, "--record", path)[0], 2)
        original["run_id"] = str(uuid4())
        path.write_text(json.dumps(original))
        self.assertEqual(self.trail_cli("prepare-dispatch", batch, run, "--record", path)[0], 2)
        self.assertFalse(list(root.glob("*.dispatch.json")))

    def test_published_transition_history_holds_single_artifact_loss_and_interruption(self):
        original_root,original_source=self.root,self.source
        cases=('intact','sole_event','tail_event','middle_event','marker_lost','marker_partial','marker_mismatch','event_partial','acceptance_event','acceptance_marker','interrupted_append')
        for mutation in cases:
            with self.subTest(publication=mutation):
                self.root=original_root/mutation;self.root.mkdir();self.source=self.root/'source.py';self.source.write_text('original',encoding='utf-8')
                try:
                    batch,run,parent,root=self.make_delivery_run();output=root/'delivery.json'
                    self.assertEqual(self.invoke_delivery(batch,run,receipt=root/'receipt.json',artifact_root=root,output=output)[0],0)
                    delivery=json.loads(output.read_bytes());request=self.dispatch_input(delivery,'dispatch.json')
                    self.assertEqual(self.trail_cli('dispatch',batch,run,'--task-id','small','--record',request)[0],0)
                    states=('dispatched',) if mutation in ('sole_event','marker_lost','marker_partial','marker_mismatch','interrupted_append') else ('dispatched','unknown','completed')
                    for state in states:
                        record,_=self.action_input(delivery,state+'.json',state=state)
                        self.assertEqual(self.trail_cli('observe',batch,run,'--task-id','small','--record',record)[0],0)
                    row=json.loads((run/'opportunities.json').read_bytes())['opportunities'][0];directory=Path(row['trail_path'])/'000000'
                    if mutation in ('intact','acceptance_event','acceptance_marker'):
                        accepted,_=self.action_input(delivery,'accepted.json',accepted=True,eliminated_stages=[])
                        self.assertEqual(self.trail_cli('accept',batch,run,'--task-id','small','--record',accepted)[0],0)
                    if mutation=='sole_event':(directory/'event-000000.json').unlink()
                    elif mutation=='tail_event':(directory/'event-000002.json').unlink()
                    elif mutation=='middle_event':(directory/'event-000001.json').unlink()
                    elif mutation=='event_partial':(directory/'event-000001.json').write_bytes(b'{')
                    elif mutation=='marker_lost':(directory/'published-000000.json').unlink(missing_ok=True)
                    elif mutation=='marker_partial':(directory/'published-000000.json').write_bytes(b'{')
                    elif mutation=='marker_mismatch':(directory/'published-000000.json').write_text('{"event_sha256":"wrong"}',encoding='utf-8')
                    elif mutation=='acceptance_event':(directory/'event-000003.json').unlink()
                    elif mutation=='acceptance_marker':(directory/'published-000003.json').unlink(missing_ok=True)
                    elif mutation=='interrupted_append':
                        record,_=self.action_input(delivery,'interrupt.json',state='unknown');write=router._write_new
                        def interrupted(path,raw):
                            if path.name=='event-000001.json':raise router.RoutingError('run_state_unavailable')
                            return write(path,raw)
                        with patch.object(router,'_write_new',side_effect=interrupted):self.assertEqual(self.trail_cli('observe',batch,run,'--task-id','small','--record',record)[0],2)
                    export=root/'adoption.json';self.assertEqual(self.trail_cli('adoption',batch,run,'--output',export)[0],0)
                    exported=json.loads(export.read_bytes())['opportunities'][0]
                    if mutation=='intact':
                        self.assertEqual(exported['action_coverage']['status'],'complete')
                        self.assertIs(exported['actions'][0]['acceptance']['accepted'],True)
                        self.assertEqual(len(exported['actions'][0]['event_publications']),4)
                        self.assertEqual(self.trail_cli('accept',batch,run,'--task-id','small','--record',accepted)[1]['status'],'duplicate')
                        continuation,_=self.action_input(delivery,'continuation.json')
                        self.assertEqual(self.trail_cli('resume',batch,run,'--task-id','small','--run-id',str(uuid4()),'--receipt',root/'continued-receipt.json','--artifact-root',root,'--output',root/'continued.json','--callback-authorized','--reason','Known completed bounded follow-up','--record',continuation)[0],0)
                    else:
                        self.assertEqual(exported['action_coverage']['status'],'unresolved')
                        self.assertEqual(exported['actions'],[])
                        self.assertEqual(self.trail_cli('resume',batch,run,'--task-id','small')[0],2)
                        record,_=self.action_input(delivery,'cannot-reconcile.json',state='not_sent')
                        self.assertEqual(self.trail_cli('observe',batch,run,'--task-id','small','--record',record)[0],2)
                finally:self.root,self.source=original_root,original_source

    def test_canonical_v2_uuid_identity_and_concurrent_event_publication(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        parent=str(uuid4());batch=self.batch_file('upper.json',[self.task('small')],coordinator_id=parent.upper())
        raw=json.loads(batch.read_bytes());raw['schema_version']=2;batch.write_text(json.dumps(raw),encoding='utf-8');original=batch.read_bytes();run=self.root/'upper-run'
        packet=json.loads(self.run_success(batch,run,self.report_bytes(['small'])));self.assertEqual(packet['coordinator_id'],parent)
        root=self.root/'evidence';root.mkdir();output=root/'delivery.json'
        self.assertEqual(self.invoke_delivery(batch,run,receipt=root/'receipt.json',artifact_root=root,output=output)[0],0)
        delivery=json.loads(output.read_bytes());self.assertEqual(delivery['parent_thread_id'],parent)
        request=self.dispatch_input(delivery,'dispatch.json');request_data=json.loads(request.read_bytes());request_data['owner_id']=parent.upper();request_data['run_id']=delivery['run_id'].upper();request.write_text(json.dumps(request_data),encoding='utf-8')
        ready=request_data['readiness'];self.assertEqual(self.trail_cli('readiness',batch,run,ready['session_path'],'--worker-kind','app','--task-id','small','--thread-id',ready['thread_id'].upper(),'--parent-thread',parent.upper(),'--cwd',self.root)[0],0)
        self.assertEqual(self.trail_cli('dispatch',batch,run,'--task-id','small','--record',request)[0],0)
        dispatched,_=self.action_input(delivery,'dispatched.json',state='dispatched');self.assertEqual(self.trail_cli('observe',batch,run,'--task-id','small','--record',dispatched)[0],0)
        complete,_=self.action_input(delivery,'complete.json',state='completed');unknown,_=self.action_input(delivery,'unknown.json',state='unknown')
        competing,_=self.action_input(delivery,'competing.json',state='unknown')
        competing_data=json.loads(competing.read_bytes());competing_data['reason']='Independent competing observation';competing.write_text(json.dumps(competing_data),encoding='utf-8')
        # Both callers have selected the same sequence before either exclusive
        # publication write. No scheduler timing or production-only hook.
        barrier=Barrier(2);write=router._write_new
        def collide(path,raw):
            if path.name=='published-000001.json':barrier.wait(timeout=10)
            return write(path,raw)
        def append(path):
            try:return router.record_action(batch,run,'small',path)
            except router.RoutingError as error:return error.category
        with patch.object(router,'_write_new',side_effect=collide),ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(append,[unknown,competing]))
        self.assertEqual(sum(isinstance(item,dict) for item in results),1)
        self.assertEqual([item for item in results if isinstance(item,str)],['run_state_unavailable'])
        export=root/'adoption.json';self.assertEqual(self.trail_cli('adoption',batch,run,'--output',export)[0],0)
        row=json.loads(export.read_bytes())['opportunities'][0];self.assertEqual(row['coordinator_id'],parent)
        self.assertEqual(len(row['actions'][0]['events']),2);self.assertEqual(len(row['actions'][0]['event_publications']),2)
        self.assertEqual(row['actions'][0]['state'],'unknown')
        # A subsequent caller takes the next sequence: unknown->completed is
        # valid serialization, separate from the forced same-sequence race.
        self.assertEqual(self.trail_cli('observe',batch,run,'--task-id','small','--record',complete)[0],0)
        self.assertEqual(self.trail_cli('observe',batch,run,'--task-id','small','--record',complete)[1]['status'],'duplicate')
        accepted,_=self.action_input(delivery,'accepted.json',accepted=True,eliminated_stages=[])
        accepted_data=json.loads(accepted.read_bytes());accepted_data['owner_id']=parent.upper();accepted_data['run_id']=delivery['run_id'].upper();accepted.write_text(json.dumps(accepted_data),encoding='utf-8')
        self.assertEqual(self.trail_cli('accept',batch,run,'--task-id','small','--record',accepted)[0],0)
        self.assertEqual(self.trail_cli('resume',batch,run,'--task-id','small')[1]['state'],'completed')
        lower=self.root/'lower.json';raw['coordinator_id']=parent;lower.write_text(json.dumps(raw),encoding='utf-8');lower_run=self.root/'lower-run'
        code,_,_,child=self.invoke_run(lower,lower_run,stdout=self.report_bytes(['small']));self.assertEqual(code,2);child.assert_not_called()
        lower_row=json.loads((lower_run/'opportunities.json').read_bytes())['opportunities'][0];self.assertEqual(lower_row['opportunity_id'],row['opportunity_id'])
        self.assertEqual(batch.read_bytes(),original)
        legacy=self.batch_file('legacy-label.json',[self.task('broad')],coordinator_id='legacy-owner');legacy_run=self.root/'legacy-label-run'
        saved=self.run_success(legacy,legacy_run,self.report_bytes(['broad']));self.assertEqual(self.invoke_emit(legacy,legacy_run)[1].encode(),saved)
        legacy_upper=self.batch_file('legacy-upper.json',[self.task('small')],coordinator_id=parent.upper());legacy_upper_run=self.root/'legacy-upper-run'
        self.run_success(legacy_upper,legacy_upper_run,self.report_bytes(['small']))
        self.assertEqual(self.invoke_delivery(legacy_upper,legacy_upper_run,receipt=root/'legacy-receipt.json',artifact_root=root,output=root/'legacy-delivery.json')[0],2)
        self.assertFalse((root/'legacy-delivery.json').exists())

    def test_dispatch_consumption_claim_holds_lost_intent_and_partial_claim(self):
        from concurrent.futures import ThreadPoolExecutor
        original_root, original_source = self.root, self.source
        for mutation in ("intact", "lost_intent", "partial_claim"):
            with self.subTest(state=mutation):
                self.root=original_root/mutation;self.root.mkdir();self.source=self.root/'source.py';self.source.write_text('original',encoding='utf-8')
                try:
                    batch,run,parent,root=self.make_delivery_run();output=root/'delivery.json'
                    self.assertEqual(self.invoke_delivery(batch,run,receipt=root/'receipt.json',artifact_root=root,output=output)[0],0)
                    delivery=json.loads(output.read_bytes());request=self.dispatch_input(delivery,'dispatch.json')
                    if mutation == 'intact':
                        def dispatch_once(_):
                            try:return router.dispatch_action(batch,run,'small',request)
                            except router.RoutingError as error:return error.category
                        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(dispatch_once,range(2)))
                        self.assertEqual(sum(isinstance(item,dict) for item in results),1)
                        self.assertEqual(next(item for item in results if isinstance(item,dict))['assignment_message'],delivery['assignment_message'])
                    else:
                        code,result=self.trail_cli('dispatch',batch,run,'--task-id','small','--record',request)
                        self.assertEqual(code,0,result);self.assertEqual(result['assignment_message'],delivery['assignment_message'])
                    row=json.loads((run/'opportunities.json').read_bytes())['opportunities'][0]
                    trail=Path(row['trail_path']);intent=trail/'000000/dispatch-intent.json';claim=trail/'consumed-000000.json'
                    if mutation == 'lost_intent': intent.unlink()
                    elif mutation == 'partial_claim': claim.write_bytes(b'{')
                    code,result=self.trail_cli('dispatch',batch,run,'--task-id','small','--record',request)
                    self.assertEqual(code,2,result);self.assertNotIn('assignment_message',result)
                    if mutation == 'lost_intent': self.assertFalse(intent.exists())
                    export=root/'adoption.json';self.assertEqual(self.trail_cli('adoption',batch,run,'--output',export)[0],0)
                    exported=json.loads(export.read_bytes())['opportunities'][0]
                    self.assertTrue(exported['eligible'])
                    self.assertEqual(exported['action_coverage']['status'],'complete' if mutation=='intact' else 'unresolved')
                    if mutation!='intact':self.assertEqual(exported['actions'],[])
                finally:self.root,self.source=original_root,original_source

    def test_not_sent_reconciliation_rejects_prior_confirmed_consumption(self):
        original_root,original_source=self.root,self.source
        for confirmed in (False,True):
            with self.subTest(confirmed=confirmed):
                self.root=original_root/str(confirmed);self.root.mkdir();self.source=self.root/'source.py';self.source.write_text('original',encoding='utf-8')
                try:
                    batch,run,parent,root=self.make_delivery_run();output=root/'delivery.json'
                    self.assertEqual(self.invoke_delivery(batch,run,receipt=root/'receipt.json',artifact_root=root,output=output)[0],0)
                    delivery=json.loads(output.read_bytes());request=self.dispatch_input(delivery,'dispatch.json')
                    self.assertEqual(self.trail_cli('dispatch',batch,run,'--task-id','small','--record',request)[0],0)
                    for state in (('dispatched','unknown') if confirmed else ('unknown',)):
                        record,_=self.action_input(delivery,state+'.json',state=state)
                        self.assertEqual(self.trail_cli('observe',batch,run,'--task-id','small','--record',record)[0],0)
                    record,_=self.action_input(delivery,'not-sent.json',state='not_sent')
                    code,result=self.trail_cli('observe',batch,run,'--task-id','small','--record',record)
                    self.assertEqual(code,2 if confirmed else 0,result)
                    export=root/'adoption.json';self.assertEqual(self.trail_cli('adoption',batch,run,'--output',export)[0],0)
                    action=json.loads(export.read_bytes())['opportunities'][0]['actions'][0]
                    self.assertEqual(action['state'],'unknown' if confirmed else 'not_sent')
                    self.assertEqual(len(action['events']),2)
                finally:self.root,self.source=original_root,original_source

    def test_lost_partial_action_state_holds_execution_and_preserves_registered_population(self):
        original_root, original_source = self.root, self.source
        for mutation in ("lost_root", "lost_action", "missing_reservation", "partial_reservation", "missing_delivery", "partial_event"):
            with self.subTest(state=mutation):
                self.root = original_root / mutation; self.root.mkdir()
                self.source = self.root / "source.py"; self.source.write_text("original")
                try:
                    batch, run_dir, parent, root = self.make_delivery_run()
                    output = root / "delivery.json"
                    self.assertEqual(self.invoke_delivery(batch, run_dir, receipt=root / "receipt.json", artifact_root=root, output=output)[0], 0)
                    delivery = json.loads(output.read_bytes())
                    request = self.dispatch_input(delivery, "dispatch.json")
                    self.assertEqual(self.trail_cli("dispatch", batch, run_dir, "--task-id", "small", "--record", request)[0], 0)
                    row = json.loads((run_dir / "opportunities.json").read_bytes())["opportunities"][0]
                    trail = Path(row["trail_path"]); action = trail / "000000"
                    self.assertTrue(trail.resolve().is_relative_to(self.root.resolve()))
                    if mutation == "lost_root": shutil.rmtree(trail)
                    elif mutation == "lost_action": shutil.rmtree(action)
                    elif mutation == "missing_reservation": (action / "reservation.json").unlink()
                    elif mutation == "partial_reservation": (action / "reservation.json").write_bytes(b'{')
                    elif mutation == "missing_delivery": output.unlink()
                    else: (action / "event-000000.json").write_bytes(b'{')
                    export = root / "unresolved.json"
                    code, result = self.trail_cli("adoption", batch, run_dir, "--output", export)
                    self.assertEqual(code, 0, result)
                    unresolved = json.loads(export.read_bytes())["opportunities"][0]
                    self.assertTrue(unresolved["eligible"])
                    self.assertEqual(unresolved.get("action_coverage", {}).get("status"), "unresolved")
                    self.assertEqual(unresolved["actions"], [])
                    self.assertEqual(self.invoke_delivery(batch, run_dir, receipt=root / "other-receipt.json", artifact_root=root, output=root / "other-delivery.json")[0], 2)
                    self.assertEqual(self.trail_cli("resume", batch, run_dir, "--task-id", "small")[0], 2)
                    self.assertEqual(self.trail_cli("dispatch", batch, run_dir, "--task-id", "small", "--record", request)[0], 2)
                    self.assertFalse((root / "other-delivery.json").exists())
                    if mutation == "lost_root":
                        self.assertFalse(trail.exists())
                        guarded=json.loads(batch.read_bytes());guarded["schema_version"]=2
                        retry=self.root/"new-batch.json";retry.write_text(json.dumps(guarded),encoding="utf-8")
                        code,_,_,provider=self.invoke_run(retry,self.root/"new-run-id",stdout=self.report_bytes(["small"]))
                        self.assertEqual(code,2);provider.assert_not_called();self.assertFalse(trail.exists())
                finally:
                    self.root, self.source = original_root, original_source

    def test_selected_task_consumers_ignore_only_unrelated_source_changes(self):
        original_root, original_source = self.root, self.source
        for mutation, collision in (("changed", None), ("deleted", None), ("deleted", "receipt"), ("deleted", "output")):
            with self.subTest(other_source=mutation, artifact_collision=collision):
                self.root = original_root / (mutation + ("-" + collision if collision else "")); self.root.mkdir()
                self.source = self.root / "a.py"; self.source.write_text("A original")
                other = self.root / "b.py"; other.write_text("B original")
                try:
                    a, b = self.task("small"), self.task("broad"); b["allowed_files"] = [str(other)]
                    parent = str(uuid4()); batch = self.batch_file("batch.json", [a,b], coordinator_id=parent)
                    run = self.root / "run"; self.run_success(batch, run, self.report_bytes(["small", "broad"]))
                    if mutation == "changed": self.source.write_text("A completed change")
                    else: self.source.unlink()
                    self.assertEqual(self.invoke_emit(batch, run)[0], 2)  # full emit stays batch-wide
                    root = self.root / "evidence"; root.mkdir(); output = root / "b-delivery.json"
                    if collision is not None:
                        # A ready sibling may continue, but neither its receipt
                        # nor its delivery may recreate the deleted source.
                        def state():
                            return ({str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()},
                                    sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_dir()))
                        before = state()
                        receipt = self.source if collision == "receipt" else root / "blocked-receipt.json"
                        target = root / ".." / self.source.name if collision == "output" else root / "blocked-delivery.json"
                        code, _, error, provider = self.invoke_delivery(batch, run, task_id="broad", receipt=receipt, artifact_root=self.root, output=target)
                        provider.assert_not_called()
                        self.assertEqual(code, 2, error)
                        self.assertEqual(json.loads(error)["category"], "delivery_path_conflict")
                        self.assertFalse(self.source.exists())
                        self.assertEqual(state(), before)
                    code, _, error, _ = self.invoke_delivery(batch, run, task_id="broad", receipt=root / "b-receipt.json", artifact_root=root, output=output)
                    self.assertEqual(code, 0, error)
                    delivery = json.loads(output.read_bytes()); request = self.dispatch_input(delivery, "b-dispatch.json")
                    ready = json.loads(request.read_bytes())["readiness"]
                    code, status = self.trail_cli("readiness", batch, run, ready["session_path"], "--worker-kind", "app", "--task-id", "broad", "--thread-id", ready["thread_id"], "--parent-thread", parent, "--cwd", self.root)
                    self.assertEqual((code, status["status"]), (0, "ready"))
                    self.assertEqual(self.trail_cli("dispatch", batch, run, "--task-id", "broad", "--record", request)[0], 0)
                    self.assertEqual(self.trail_cli("resume", batch, run, "--task-id", "broad")[0], 0)
                    other.write_text("B unapproved change")
                    code, status = self.trail_cli("resume", batch, run, "--task-id", "broad")
                    self.assertEqual((code, status["category"]), (2, "source_drift"))
                finally:
                    self.root, self.source = original_root, original_source

    def test_receipt_argument_vector_preserves_literal_shell_characters(self):
        batch, run, parent, root = self.make_delivery_run()
        special = root / "space $proof 'quote' $()"; special.mkdir()
        output = special / "delivery.json"; receipt = special / "receipt.json"
        code, _, error, _ = self.invoke_delivery(batch, run, receipt=receipt, artifact_root=special, output=output)
        self.assertEqual(code, 0, error)
        delivery = json.loads(output.read_bytes())
        vector = delivery.get("receipt_command_argv")
        self.assertIsInstance(vector, list)
        self.assertTrue(all(isinstance(item, str) for item in vector))
        self.assertEqual(vector[vector.index("--receipt") + 1], str(receipt.parent.resolve(strict=True) / receipt.name))
        self.assertEqual(vector[vector.index("--artifact-root") + 1], str(special.resolve(strict=True)))
        receiver = self.root / "argv_receiver.py"
        receiver.write_text("import json,sys; print(json.dumps(sys.argv[1:]))", encoding="utf-8")
        suffix = vector[3:] + ["literal $proof", "space and 'single' and \"double\"", "$()", "$( )"]
        argv = [sys.executable, "-B", str(receiver), *suffix]
        result = _REAL_PROCESS_RUN(argv, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(json.loads(result.stdout), suffix)
        for powershell in dict.fromkeys(filter(None, (shutil.which("pwsh"), shutil.which("powershell")))):
            vector_file = self.root / "argv.json"; vector_file.write_text(json.dumps(argv), encoding="utf-8")
            env = {**os.environ, "ROUTING_ARGV_TEST_FILE": str(vector_file), "ROUTING_ARGV_PYTHON": sys.executable}
            script = "@'\nimport json, os, subprocess\nwith open(os.environ[\"ROUTING_ARGV_TEST_FILE\"], encoding=\"utf-8\") as stream: argv = json.load(stream)\nraise SystemExit(subprocess.run(argv, shell=False).returncode)\n'@ | & $env:ROUTING_ARGV_PYTHON -B -; exit $LASTEXITCODE"
            result = _REAL_PROCESS_RUN([powershell, "-NoProfile", "-NonInteractive", "-Command", script], env=env, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(json.loads(result.stdout), suffix)
        shell = shutil.which("sh")
        if shell:
            portable = [Path(sys.executable).as_posix(), "-B", receiver.as_posix(), *suffix]
            result = _REAL_PROCESS_RUN([shell, "-c", 'exec "$@"', "argv-receiver", *portable], env={**os.environ, "MSYS2_ARG_CONV_EXCL": "*"}, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(json.loads(result.stdout), suffix)

    def test_direct_prerequisites_and_null_dispositions_preserve_legitimate_routes(self):
        original_root, original_source = self.root, self.source
        cases = (("unauthorized", False, True, False, "hold"), ("not_ready", True, False, True, "hold"), ("ready_no_export", True, True, False, "owner"))
        for name, authorized, ready, exported, route in cases:
            with self.subTest(direct=name):
                task = self.task(name, authorized=authorized, inputs_ready=ready, export_approved=exported)
                task["local_disposition"] = {"route": "direct", "reason": "Explicit local owner action"}
                batch = self.batch_file(name + ".json", [task]); data = json.loads(batch.read_bytes()); data["schema_version"]=2;batch.write_text(json.dumps(data),encoding="utf-8")
                code, stdout, error, child = self.invoke_run(batch, self.root / (name + "-run"))
                self.assertEqual(code, 0, error); child.assert_not_called()
                packet = json.loads(stdout)["tasks"][0];self.assertEqual(packet["route"], route)
                if route == "owner": self.assertNotIn("export_approval_required", packet["hold_reasons"])
        held = self.task("held", inputs_ready=False); held["local_disposition"] = None
        valid = self.task("small"); valid["local_disposition"] = None
        batch = self.batch_file("null-mixed.json", [valid,held]);data=json.loads(batch.read_bytes());data["schema_version"]=2;batch.write_text(json.dumps(data),encoding="utf-8")
        run=self.root / "null-run";code,stdout,error,child=self.invoke_run(batch,run,stdout=self.report_bytes(["small"]))
        self.assertEqual(code,0,error);child.assert_called_once()
        self.assertEqual([task["route"] for task in json.loads(stdout)["tasks"]],["worker_luna","hold"])

    def test_delivery_reserves_once_and_binds_actual_action_and_owner_acceptance(self):
        batch, run_dir, parent, root = self.make_delivery_run()
        output = root / "delivery.json"
        code, _, err, _ = self.invoke_delivery(batch, run_dir, receipt=root / "receipt.json", artifact_root=root, output=output)
        self.assertEqual(code, 0, err)
        # This public boundary previously allowed a second dispatchable assignment.
        duplicate, _, _, _ = self.invoke_delivery(batch, run_dir, receipt=root / "second-receipt.json", artifact_root=root, output=root / "second.json")
        self.assertEqual(duplicate, 2)
        self.assertFalse((root / "second.json").exists())
        guarded_batch = self.root / "guarded-copy.json"
        guarded = json.loads(batch.read_bytes()); guarded["schema_version"] = 2
        guarded_batch.write_text(json.dumps(guarded), encoding="utf-8")
        code, _, _, attempted = self.invoke_run(guarded_batch, self.root / "new-routing-id", stdout=self.report_bytes(["small"]))
        self.assertEqual(code, 2)
        attempted.assert_not_called()
        delivery = json.loads(output.read_bytes())
        wrong = self.dispatch_input(delivery, "wrong.json")
        refs = json.loads(wrong.read_bytes())["evidence"]
        bad = json.loads(wrong.read_bytes()); bad["assignment_message"] += " changed"; wrong.write_text(json.dumps(bad))
        code, error = self.trail_cli("dispatch", batch, run_dir, "--task-id", "small", "--record", wrong)
        self.assertEqual((code, error["category"]), (2, "dispatch_binding_mismatch"))
        request = self.dispatch_input(delivery, "dispatch.json")
        valid_request = json.loads(request.read_bytes())
        for field, value in (("schema_version", True), ("run_id", str(uuid4())), ("task_id", "other"), ("owner_id", str(uuid4())), ("packet_sha256", "0" * 64)):
            changed = {**valid_request, field: value}
            invalid = self.root / (field + "-dispatch.json"); invalid.write_text(json.dumps(changed))
            code, error = self.trail_cli("dispatch", batch, run_dir, "--task-id", "small", "--record", invalid)
            self.assertEqual((code, error["category"]), (2, "dispatch_binding_mismatch"))
        self.assertEqual(self.trail_cli("dispatch", batch, run_dir, "--task-id", "small", "--record", request)[0], 0)
        self.assertEqual(self.trail_cli("dispatch", batch, run_dir, "--task-id", "small", "--record", request)[0], 2)
        for name, state in (("sent", "dispatched"), ("done", "completed")):
            record, _ = self.action_input(delivery, name + ".json", state=state)
            self.assertEqual(self.trail_cli("observe", batch, run_dir, "--task-id", "small", "--record", record)[0], 0)
        # A worker may change its allowed sources. Historical observations and
        # owner acceptance still bind the original dispatched bytes.
        self.source.write_text("completed implementation\n")
        acceptance, refs = self.action_input(delivery, "accepted.json", accepted=True,
            eliminated_stages=[{"stage": "assignment_drafting", "reason": "Exact generated assignment was used", "evidence": refs}])
        self.assertEqual(self.trail_cli("accept", batch, run_dir, "--task-id", "small", "--record", acceptance)[0], 0)
        self.assertEqual(self.trail_cli("accept", batch, run_dir, "--task-id", "small", "--record", acceptance)[1]["status"], "duplicate")
        export = root / "adoption.json"
        self.assertEqual(self.trail_cli("adoption", batch, run_dir, "--output", export)[0], 0)
        snapshot = json.loads(export.read_bytes())
        action = snapshot["opportunities"][0]["actions"][0]
        self.assertEqual(action["state"], "completed")
        self.assertIs(action["acceptance"]["accepted"], True)
        self.assertEqual(snapshot["opportunities"][0]["attempt"]["meter"]["usage"]["input_tokens"], 100)
        code, error = self.trail_cli("resume", batch, run_dir, "--task-id", "small")
        self.assertEqual((code, error["category"]), (2, "source_drift"))

    def test_offline_resume_retains_pending_and_links_only_known_continuation(self):
        batch, run_dir, parent, root = self.make_delivery_run()
        output = root / "delivery.json"
        self.assertEqual(self.invoke_delivery(batch, run_dir, receipt=root / "receipt.json", artifact_root=root, output=output)[0], 0)
        delivery = json.loads(output.read_bytes())
        code, status = self.trail_cli("resume", batch, run_dir, "--task-id", "small")
        self.assertEqual((code, status["state"], status["launch_permitted"]), (0, "pending", False))
        self.assertEqual(self.trail_cli("dispatch", batch, run_dir, "--task-id", "small", "--record", self.dispatch_input(delivery, "dispatch.json"))[0], 0)
        reason, refs = self.action_input(delivery, "continuation.json")
        feedback = json.loads(reason.read_bytes())
        feedback["continuation"] = {"instructions": "Correct the missing result: include the verified total.",
                                    "expected_artifacts": [str(root / "corrected.json")]}
        reason.write_text(json.dumps(feedback), encoding="utf-8")
        options = ("--task-id", "small", "--run-id", str(uuid4()), "--receipt", root / "continued-receipt.json",
                   "--artifact-root", root, "--output", root / "continued.json", "--callback-authorized",
                   "--reason", "Finish known interrupted work with unchanged scope and budget", "--record", reason)
        self.assertEqual(self.trail_cli("resume", batch, run_dir, *options)[0], 2)
        unknown, _ = self.action_input(delivery, "unknown.json", state="unknown")
        self.assertEqual(self.trail_cli("observe", batch, run_dir, "--task-id", "small", "--record", unknown)[0], 0)
        self.assertEqual(self.trail_cli("resume", batch, run_dir, *options)[0], 2)
        interrupted, _ = self.action_input(delivery, "interrupted.json", state="interrupted")
        self.assertEqual(self.trail_cli("observe", batch, run_dir, "--task-id", "small", "--record", interrupted)[0], 0)
        code, status = self.trail_cli("resume", batch, run_dir, *options)
        self.assertEqual(code, 0, status)
        continued = json.loads((root / "continued.json").read_bytes())
        packet = json.loads((run_dir / "packets.json").read_bytes())
        self.assertTrue(continued["assignment_message"].startswith(packet["tasks"][0]["assignment_message"]))
        code, dispatched = self.trail_cli("dispatch", batch, run_dir, "--task-id", "small", "--record",
                                         self.dispatch_input(continued, "continued-dispatch.json"))
        self.assertEqual(code, 0, dispatched)
        for value in (options[-3], feedback["continuation"]["instructions"], str(root / "corrected.json"),
                      refs[0]["path"], refs[0]["sha256"]):
            self.assertIn(value, dispatched["assignment_message"])
        self.assertEqual(json.loads(output.read_bytes()), delivery)
        self.assertNotEqual(continued["action_id"], delivery["action_id"])
        self.assertEqual(continued["source_packet"], delivery["source_packet"])
        export = root / "adoption.json"
        self.assertEqual(self.trail_cli("adoption", batch, run_dir, "--output", export)[0], 0)
        actions = json.loads(export.read_bytes())["opportunities"][0]["actions"]
        self.assertEqual(actions[1]["reservation"]["previous_action_id"], delivery["action_id"])
        self.assertEqual(actions[1]["reservation"]["mode"], "offline_reuse")

    def test_guarded_registration_retains_failed_eligible_and_excludes_local_dispositions(self):
        parent = str(uuid4())
        direct = self.task("direct_case"); direct["local_disposition"] = {"route": "direct", "reason": "Small inseparable owner action"}
        hold = self.task("held_case", export_approved=False)
        batch = self.batch_file("guarded.json", [direct, hold], coordinator_id=parent)
        data = json.loads(batch.read_bytes()); data["schema_version"] = 2; batch.write_text(json.dumps(data))
        run_dir = self.root / "local-run"
        code, _, err, child = self.invoke_run(batch, run_dir)
        self.assertEqual(code, 0, err); child.assert_not_called()
        rows = json.loads((run_dir / "opportunities.json").read_bytes())["opportunities"]
        self.assertTrue(all(not row["eligible"] and row["exclusion_reasons"] for row in rows))
        failed_batch = self.batch_file("failed.json", [self.task("small")], coordinator_id=parent)
        data = json.loads(failed_batch.read_bytes()); data["schema_version"] = 2; failed_batch.write_text(json.dumps(data))
        failed_run = self.root / "failed-run"
        code, _, _, child = self.invoke_run(failed_batch, failed_run, stdout=b'{"error":"refused"}', returncode=2)
        self.assertEqual(code, 2); child.assert_called_once()
        export = self.root / "failed-adoption.json"
        self.assertEqual(self.trail_cli("adoption", failed_batch, failed_run, "--output", export)[0], 0)
        row = json.loads(export.read_bytes())["opportunities"][0]
        self.assertTrue(row["eligible"]); self.assertEqual(row["attempt"]["status"], "failed")
        code, _, _, child = self.invoke_run(failed_batch, self.root / "new-id-same-opportunity", stdout=self.report_bytes(["small"]))
        self.assertEqual(code, 2); child.assert_not_called()
        # A newly tracked legacy pending submission also blocks adoption under
        # a fresh version-2 run UUID before a second provider attempt.
        legacy = self.batch_file("legacy.json", [self.task("broad")], coordinator_id=parent)
        code, _, _, child = self.invoke_run(legacy, self.root / "legacy-pending", side_effect=KeyboardInterrupt())
        self.assertEqual(code, 2); child.assert_called_once()
        value = json.loads(legacy.read_bytes()); value["schema_version"] = 2
        upgraded = self.root / "upgraded.json"; upgraded.write_text(json.dumps(value), encoding="utf-8")
        code, _, _, child = self.invoke_run(upgraded, self.root / "upgraded-new-run")
        self.assertEqual(code, 2); child.assert_not_called()

    def test_concurrent_delivery_and_partial_publication_cannot_duplicate_launch(self):
        from concurrent.futures import ThreadPoolExecutor
        batch, run_dir, parent, root = self.make_delivery_run()
        def reserve(index):
            try:
                return router.prepare_delivery(batch, run_dir, task_id="small", run_id=str(uuid4()),
                    receipt=str(root / f"receipt-{index}.json"), artifact_root=str(root),
                    output=str(root / f"delivery-{index}.json"), callback_authorized=True)
            except router.RoutingError as error:
                return error.category
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, range(2)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(len(list(root.glob("delivery-*.json"))), 1)
        # A lost local output remains an uncertain reservation, never a new ID.
        next(root.glob("delivery-*.json")).unlink()
        self.assertIsInstance(reserve(3), str)
        self.assertFalse((root / "delivery-3.json").exists())

    def test_delivery_writes_byte_preserving_compact_offline_record(self) -> None:
        batch, run_dir, parent, artifact_root = self.make_delivery_run()
        packet_raw = (run_dir / "packets.json").read_bytes()
        packet = json.loads(packet_raw)
        base_assignment = packet["tasks"][0]["assignment_message"]
        receipt = artifact_root / "terminal.json"
        output = artifact_root / "delivery.json"
        run_id = str(uuid4())

        code, stdout, stderr, provider = self.invoke_delivery(
            batch,
            run_dir,
            run_id=run_id,
            receipt=receipt,
            artifact_root=artifact_root,
            output=output,
        )

        self.assertEqual(code, 0, stderr)
        provider.assert_not_called()
        self.assertEqual((run_dir / "packets.json").read_bytes(), packet_raw)
        result = json.loads(stdout)
        delivery_raw = output.read_bytes()
        delivery = json.loads(delivery_raw)
        assignment = delivery["assignment_message"]
        self.assertTrue(assignment.encode("utf-8").startswith(base_assignment.encode("utf-8")))
        self.assertGreater(len(assignment), len(base_assignment))
        self.assertEqual(delivery["source_packet"], {
            "path": str((run_dir / "packets.json").resolve()),
            "sha256": hashlib.sha256(packet_raw).hexdigest(),
        })
        self.assertEqual(delivery["run_id"], run_id)
        self.assertEqual(delivery["parent_thread_id"], parent)
        self.assertEqual(delivery["receipt"], str(receipt.resolve()))
        self.assertEqual(delivery["artifact_root"], str(artifact_root.resolve()))
        self.assertEqual((delivery["route"], delivery["model"], delivery["reasoning_effort"]),
                         ("worker_luna", "gpt-6-luna", "max"))
        helper = Path(router.__file__).with_name("detached_receipt.py").resolve()
        self.assertEqual(delivery["receipt_helper"], {
            "path": str(helper),
            "sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
        })
        self.assertEqual(result["delivery_path"], str(output.resolve()))
        self.assertEqual(result["delivery_sha256"], hashlib.sha256(delivery_raw).hexdigest())
        self.assertEqual(result["assignment_message_sha256"], hashlib.sha256(assignment.encode("utf-8")).hexdigest())
        self.assertNotIn(base_assignment, stdout)

    def test_delivery_rejects_owner_hold_and_missing_callback_authorization(self) -> None:
        batch, run_dir, _parent, artifact_root = self.make_delivery_run(
            include_owner=True, include_hold=True
        )
        for task_id, expected in (("owner_case", "delivery_route_not_worker"),
                                  ("held_case", "delivery_route_not_worker")):
            with self.subTest(task_id=task_id):
                receipt = artifact_root / f"{task_id}-receipt.json"
                output = artifact_root / f"{task_id}-delivery.json"
                code, _stdout, stderr, provider = self.invoke_delivery(
                    batch, run_dir, task_id=task_id, receipt=receipt,
                    artifact_root=artifact_root, output=output,
                )
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(stderr)["category"], expected)
                provider.assert_not_called()
                self.assertFalse(output.exists())
        receipt = artifact_root / "unauthorized-receipt.json"
        output = artifact_root / "unauthorized-delivery.json"
        code, _stdout, stderr, provider = self.invoke_delivery(
            batch, run_dir, receipt=receipt, artifact_root=artifact_root,
            output=output, callback_authorized=False,
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["category"], "callback_authorization_required")
        provider.assert_not_called()
        self.assertFalse(output.exists())

    def test_delivery_rejects_escaping_and_existing_paths_without_overwrite(self) -> None:
        batch, run_dir, _parent, artifact_root = self.make_delivery_run()
        outside = self.root / "outside-delivery.json"
        code, _stdout, stderr, provider = self.invoke_delivery(
            batch, run_dir, receipt=artifact_root / "terminal.json",
            artifact_root=artifact_root, output=outside,
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["category"], "delivery_path_escape")
        provider.assert_not_called()
        self.assertFalse(outside.exists())

        existing = artifact_root / "delivery.json"
        existing.write_bytes(b"preserve existing user data\n")
        before = existing.read_bytes()
        code, _stdout, stderr, provider = self.invoke_delivery(
            batch, run_dir, receipt=artifact_root / "terminal.json",
            artifact_root=artifact_root, output=existing,
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["category"], "delivery_path_exists")
        provider.assert_not_called()
        self.assertEqual(existing.read_bytes(), before)

        same = artifact_root / "same.json"
        code, _stdout, stderr, provider = self.invoke_delivery(
            batch, run_dir, receipt=same, artifact_root=artifact_root, output=same
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["category"], "delivery_paths_not_distinct")
        provider.assert_not_called()
        self.assertFalse(same.exists())

    def test_delivery_refuses_tampered_saved_packet(self) -> None:
        batch, run_dir, _parent, artifact_root = self.make_delivery_run()
        packet_path = run_dir / "packets.json"
        packet_path.write_bytes(packet_path.read_bytes().replace(b"worker_luna", b"worker_sol ", 1))
        output = artifact_root / "delivery.json"
        code, _stdout, stderr, provider = self.invoke_delivery(
            batch, run_dir, receipt=artifact_root / "terminal.json",
            artifact_root=artifact_root, output=output,
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["category"], "stored_packet_invalid")
        provider.assert_not_called()
        self.assertFalse(output.exists())

    def test_delivery_requires_uuid_identity_and_matching_task(self) -> None:
        batch, run_dir, _parent, artifact_root = self.make_delivery_run()
        code, _stdout, stderr, provider = self.invoke_delivery(
            batch,
            run_dir,
            run_id="not-a-uuid",
            receipt=artifact_root / "bad-id-receipt.json",
            artifact_root=artifact_root,
            output=artifact_root / "bad-id-delivery.json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["category"], "delivery_uuid_invalid")
        provider.assert_not_called()

        missing_root = self.root / "missing-artifact-root"
        code, _stdout, stderr, provider = self.invoke_delivery(
            batch,
            run_dir,
            receipt=artifact_root / "missing-root-receipt.json",
            artifact_root=missing_root,
            output=artifact_root / "missing-root-delivery.json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["category"], "artifact_root_invalid")
        provider.assert_not_called()

        code, _stdout, stderr, provider = self.invoke_delivery(
            batch,
            run_dir,
            task_id="missing_task",
            receipt=artifact_root / "missing-task-receipt.json",
            artifact_root=artifact_root,
            output=artifact_root / "missing-task-delivery.json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["category"], "delivery_task_invalid")
        provider.assert_not_called()

        bad_parent_batch = self.batch_file(
            "bad-parent-batch.json", [self.task("small")]
        )
        bad_parent_run = self.root / "runs" / "bad-parent"
        self.run_success(bad_parent_batch, bad_parent_run, self.report_bytes(["small"]))
        code, _stdout, stderr, provider = self.invoke_delivery(
            bad_parent_batch,
            bad_parent_run,
            receipt=artifact_root / "bad-parent-receipt.json",
            artifact_root=artifact_root,
            output=artifact_root / "bad-parent-delivery.json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["category"], "delivery_uuid_invalid")
        provider.assert_not_called()

    def test_complete_report_compiles_routes_and_assignment(self) -> None:
        batch = self.batch_file(
            "batch.json",
            [
                self.task("small"),
                self.task("broad"),
                self.task("owner_case"),
            ],
        )
        run_dir = self.root / "runs" / "one"

        packet_raw = self.run_success(batch, run_dir, self.report_bytes())
        packet = json.loads(packet_raw)
        self.assertEqual(packet["coordinator_id"], "coordinator-42")
        small, broad, owner = packet["tasks"]
        self.assertEqual((small["route"], small["model"], small["reasoning_effort"]), ("worker_luna", "gpt-6-luna", "max"))
        self.assertEqual((broad["route"], broad["model"], broad["reasoning_effort"]), ("worker_sol", "gpt-6.1-sol", "medium"))
        self.assertEqual((owner["route"], owner["model"], owner["reasoning_effort"]), ("owner", None, None))
        self.assertTrue(all(item["fork_turns"] == "none" for item in packet["tasks"]))
        self.assertTrue(all("READY only" in item["launch_message"] and "tools" in item["launch_message"] for item in packet["tasks"]))
        source_path = str(self.source.resolve())
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        stable_prefix = (
            "Execution ownership and return:\n"
            "As the execution worker, own implementation, focused tests, and ordinary repairs "
            "within the allowed files and acceptance checks. Save complete evidence locally. "
            "Do not omit failures or relax acceptance. Return one concise terminal summary to "
            "the original coordinator with changed-file identities, exact checks and results, "
            "failure and unknown counts, and artifact pointers. The original coordinator owns "
            "review and final acceptance.\n\n"
            "Act as an execution leaf. Do not launch agents, tasks, or model-backed helpers. "
            "The route choice grants no authority to expand scope, bypass review, or make "
            "acceptance decisions. Do not take external actions or contact services.\n\n"
        )
        assignments = (small, broad)
        self.assertEqual(
            [item["assignment_message"][:len(stable_prefix)] for item in assignments],
            [stable_prefix] * len(assignments),
            "each assignment must begin with the complete stable worker-instruction prefix",
        )
        self.assertNotEqual(small["assignment_message"], broad["assignment_message"])
        for task_id, item in (("small", small), ("broad", broad)):
            assignment = item["assignment_message"]
            self.assertIn(
                f"Execution assignment for the original coordinator coordinator-42.\n"
                f"Objective:\nObjective for {task_id}\n\n",
                assignment,
            )
            self.assertIn(f"Context:\nContext for {task_id}", assignment)
            self.assertIn(f"Allowed files:\n- {source_path}", assignment)
            self.assertIn(f"Acceptance checks:\n- Check {task_id}", assignment)
            self.assertEqual(item["source_sha256"][source_path], source_hash)
            self.assertIn(f"- {source_path} | SHA-256: {source_hash}", assignment)
            self.assertIn("during your first source read before editing", assignment)
            self.assertIn("if any hash differs, stop and report it", assignment)
        self.assertEqual((run_dir / "packets.json").read_bytes(), packet_raw)

    def test_request_omits_held_tasks_and_never_sends_paths_or_checks(self) -> None:
        batch = self.batch_file(
            "batch.json",
            [
                self.task("small"),
                self.task("no_auth", authorized=False),
                self.task("no_export", export_approved=False),
                self.task("not_ready", inputs_ready=False),
            ],
        )
        run_dir = self.root / "run"
        code, output, error, child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        child.assert_called_once()
        request_raw = (run_dir / "request.json").read_bytes()
        request = json.loads(request_raw)
        self.assertEqual(set(request["questions"]), {"small"})
        self.assertNotIn(str(self.source.resolve()), request_raw.decode())
        self.assertNotIn("Check small", request_raw.decode())
        for held_id in ("no_auth", "no_export", "not_ready"):
            self.assertNotIn(held_id, request_raw.decode())
            self.assertNotIn(f"Context for {held_id}", request_raw.decode())
        packet = json.loads(output)
        held = {item["id"]: item for item in packet["tasks"] if item["route"] == "hold"}
        self.assertEqual(set(held), {"no_auth", "no_export", "not_ready"})
        self.assertEqual(held["no_auth"]["hold_reasons"], ["authorization_required"])
        self.assertEqual(held["no_export"]["hold_reasons"], ["export_approval_required"])
        self.assertEqual(held["not_ready"]["hold_reasons"], ["inputs_not_ready"])

    def test_all_held_runs_and_emits_without_subprocess(self) -> None:
        batch = self.batch_file(
            "batch.json",
            [
                self.task("held_one", authorized=False),
                self.task("held_two", export_approved=False),
            ],
        )
        run_dir = self.root / "all-held"
        out = io.StringIO()
        err = io.StringIO()
        with patch.object(router.subprocess, "run") as child, redirect_stdout(out), redirect_stderr(err):
            code = router.main(["run", str(batch), str(run_dir)])
            self.assertEqual(code, 0, err.getvalue())
            run_output = out.getvalue().encode("ascii")
            out.seek(0)
            out.truncate(0)
            code = router.main(["emit", str(batch), str(run_dir)])
        self.assertEqual(code, 0, err.getvalue())
        child.assert_not_called()
        self.assertEqual(run_output, out.getvalue().encode("ascii"))
        self.assertFalse((run_dir / "request.json").exists())
        self.assertFalse((run_dir / "submission-intent.json").exists())
        self.assertFalse((run_dir / "provider-return.json").exists())
        self.assertTrue(all(item["route"] == "hold" for item in json.loads(run_output)["tasks"]))

    def test_emit_is_byte_equivalent_and_never_calls_subprocess(self) -> None:
        batch = self.batch_file("batch.json", [self.task("small")])
        run_dir = self.root / "cache"
        out = io.StringIO()
        err = io.StringIO()
        with patch.object(router.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, self.report_bytes(["small"]), b"")) as child:
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(router.main(["run", str(batch), str(run_dir)]), 0, err.getvalue())
                run_bytes = (run_dir / "packets.json").read_bytes()
                out.seek(0)
                out.truncate(0)
                self.assertEqual(router.main(["emit", str(batch), str(run_dir)]), 0, err.getvalue())
        child.assert_called_once()
        self.assertEqual(run_bytes, out.getvalue().encode("ascii"))

    def test_duplicate_nonfinite_unknown_and_oversized_batches_fail_before_call(self) -> None:
        valid_task = json.dumps(self.task("small"), ensure_ascii=True)
        cases = {
            "duplicate": ('{"schema_version":1,"schema_version":1,"coordinator_id":"c","tasks":[]}', "batch_invalid"),
            "nonfinite": ('{"schema_version":NaN,"coordinator_id":"c","tasks":[]}', "batch_invalid"),
            "unknown": (json.dumps({"schema_version": 1, "coordinator_id": "c", "tasks": [self.task("small")], "extra": 1}), "batch_invalid"),
            "oversized": ('{"padding":"' + "x" * (32 * 1024) + '"}', "batch_invalid"),
        }
        with patch.object(router.subprocess, "run") as child:
            for name, (raw, category) in cases.items():
                with self.subTest(name=name):
                    batch = self.root / f"{name}.json"
                    batch.write_text(raw, encoding="utf-8")
                    code, error = self.cli_error(["run", str(batch), str(self.root / f"run-{name}")])
                    self.assertEqual(code, 2)
                    self.assertEqual(error["category"], category)
        child.assert_not_called()

    def test_partial_wrong_provider_and_bad_choice_are_retained_and_rejected(self) -> None:
        batch = self.batch_file("batch.json", [self.task("small")])
        variants: list[tuple[str, bytes]] = []

        partial = json.loads(self.report_bytes(["small"]))
        partial["status"] = "partial"
        partial["answers"]["small"]["status"] = "unresolved"
        variants.append(("partial", (json.dumps(partial) + "\n").encode()))

        wrong_provider = json.loads(self.report_bytes(["small"]))
        wrong_provider["provider"] = "jev"
        variants.append(("provider", (json.dumps(wrong_provider) + "\n").encode()))

        wrong_choice = json.loads(self.report_bytes(["small"]))
        wrong_choice["answers"]["small"]["choice"] = "run_shell"
        variants.append(("choice", (json.dumps(wrong_choice) + "\n").encode()))

        malformed = b'{"status":"complete","status":"partial"}'
        variants.append(("duplicate_return", malformed))

        call_count = 0
        for name, raw in variants:
            with self.subTest(name=name):
                run_dir = self.root / f"bad-{name}"
                code, _out, err, child = self.invoke_run(batch, run_dir, stdout=raw)
                call_count += child.call_count
                self.assertEqual(code, 2)
                self.assertIn('"category":"response_', err)
                saved = json.loads((run_dir / "child-result.json").read_bytes())
                self.assertEqual((run_dir / "provider-return.json").read_bytes(), raw)
                self.assertEqual(saved["stdout_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertTrue((run_dir / "submission-intent.json").exists())
                self.assertFalse((run_dir / "packets.json").exists())
        self.assertEqual(call_count, len(variants))

    def test_batch_source_router_and_adviser_drift_deny_emit(self) -> None:
        for drift in ("batch", "source", "router", "adviser"):
            with self.subTest(drift=drift):
                batch = self.batch_file(f"{drift}-batch.json", [self.task("small")])
                run_dir = self.root / f"run-{drift}"
                temp_tool = self.root / f"{drift}-tool.py"
                original_constants = (router.ROUTER_PATH, router.ADVISER_PATH)
                try:
                    if drift == "router":
                        temp_tool.write_text("router version 1\n", encoding="utf-8")
                        router.ROUTER_PATH = temp_tool
                    elif drift == "adviser":
                        temp_tool.write_text("adviser version 1\n", encoding="utf-8")
                        router.ADVISER_PATH = temp_tool
                    self.run_success(batch, run_dir, self.report_bytes(["small"]))
                    if drift == "batch":
                        batch.write_text(batch.read_text(encoding="utf-8") + " ", encoding="utf-8")
                        expected = "batch_drift"
                    elif drift == "source":
                        self.source.write_text("def source(): return 2\n", encoding="utf-8")
                        expected = "source_drift"
                    else:
                        temp_tool.write_text("changed tool version\n", encoding="utf-8")
                        expected = "tool_drift"
                    code, error = self.cli_error(["emit", str(batch), str(run_dir)])
                    self.assertEqual(code, 2)
                    self.assertEqual(error["category"], expected)
                finally:
                    router.ROUTER_PATH, router.ADVISER_PATH = original_constants

    def test_fresh_run_rechecks_tool_identity_before_submission_and_after_child(self) -> None:
        for phase in ("before_submission", "after_child"):
            for tool_name in ("router", "adviser"):
                with self.subTest(phase=phase, tool=tool_name):
                    batch = self.batch_file(f"{phase}-{tool_name}.json", [self.task("small")])
                    run_dir = self.root / f"{phase}-{tool_name}-run"
                    temp_tool = self.root / f"{phase}-{tool_name}-tool.py"
                    temp_tool.write_text("tool version 1\n", encoding="utf-8")
                    original_constants = (router.ROUTER_PATH, router.ADVISER_PATH)
                    try:
                        if tool_name == "router":
                            router.ROUTER_PATH = temp_tool
                        else:
                            router.ADVISER_PATH = temp_tool

                        if phase == "before_submission":
                            original_write_new = router._write_new

                            def write_then_drift(path: Path, raw: bytes) -> None:
                                original_write_new(path, raw)
                                if path.name == "submission-intent.json":
                                    temp_tool.write_text("tool version 2\n", encoding="utf-8")

                            with patch.object(router, "_write_new", side_effect=write_then_drift):
                                code, _out, error, child = self.invoke_run(
                                    batch, run_dir, stdout=self.report_bytes(["small"])
                                )
                            self.assertEqual(code, 2)
                            self.assertEqual(json.loads(error)["category"], "tool_drift")
                            child.assert_not_called()
                            self.assertTrue((run_dir / "submission-intent.json").exists())
                            self.assertFalse((run_dir / "provider-return.json").exists())
                            self.assertFalse((run_dir / "packets.json").exists())
                        else:
                            def child_then_drift(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
                                temp_tool.write_text("tool version 2\n", encoding="utf-8")
                                return subprocess.CompletedProcess(
                                    args=[],
                                    returncode=0,
                                    stdout=self.report_bytes(["small"]),
                                    stderr=b"",
                                )

                            code, _out, error, child = self.invoke_run(
                                batch, run_dir, side_effect=child_then_drift
                            )
                            self.assertEqual(code, 2)
                            self.assertEqual(json.loads(error)["category"], "tool_drift")
                            child.assert_called_once()
                            self.assertTrue((run_dir / "submission-intent.json").exists())
                            self.assertTrue((run_dir / "provider-return.json").exists())
                            self.assertFalse((run_dir / "packets.json").exists())
                    finally:
                        router.ROUTER_PATH, router.ADVISER_PATH = original_constants

    def test_all_held_fresh_run_rechecks_tool_identity_before_packets(self) -> None:
        batch = self.batch_file("all-held-tool-drift.json", [self.task("held", authorized=False)])
        run_dir = self.root / "all-held-tool-drift"
        temp_tool = self.root / "all-held-tool.py"
        temp_tool.write_text("tool version 1\n", encoding="utf-8")
        original_router_path = router.ROUTER_PATH
        original_write_new = router._write_new
        try:
            router.ROUTER_PATH = temp_tool

            def write_manifest_then_drift(path: Path, raw: bytes) -> None:
                original_write_new(path, raw)
                if path.name == "manifest.json":
                    temp_tool.write_text("tool version 2\n", encoding="utf-8")

            with patch.object(router, "_write_new", side_effect=write_manifest_then_drift):
                out = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err), patch.object(
                    socket, "socket", side_effect=AssertionError("network access in test")
                ):
                    code = router.main(["run", str(batch), str(run_dir)])
            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(json.loads(err.getvalue())["category"], "tool_drift")
            self.assertFalse((run_dir / "packets.json").exists())
            self.assertFalse((run_dir / "submission-intent.json").exists())
        finally:
            router.ROUTER_PATH = original_router_path

    def test_existing_run_directory_refuses_replay(self) -> None:
        batch = self.batch_file("batch.json", [self.task("small")])
        run_dir = self.root / "single-use"
        _code, _out, _err, child = self.invoke_run(batch, run_dir, stdout=self.report_bytes(["small"]))
        self.assertEqual(child.call_count, 1)
        code, error = self.cli_error(["run", str(batch), str(run_dir)])
        self.assertEqual(code, 2)
        self.assertEqual(error["category"], "run_directory_exists")
        self.assertEqual(child.call_count, 1)

    def test_large_derived_manifest_is_rejected_before_submission(self) -> None:
        # Accepted input bytes expand when canonical paths receive fingerprints.
        # Keep real files and a valid control receipt; only that expansion rejects.
        task = self.task("small")
        task["allowed_files"] = []
        payload = {"schema_version": 1, "coordinator_id": "coordinator-42", "tasks": [task]}
        for index in range(2000):
            path = self.root / f"f{index}"
            path.touch()
            task["allowed_files"].append(path.as_posix())
            if len(json.dumps(payload).encode()) > 32 * 1024:
                task["allowed_files"].pop()
                break
        self.assertGreater(len(json.dumps({str(Path(p)): "0" * 64 for p in task["allowed_files"]}).encode()), 64 * 1024)
        batch = self.root / "large-manifest-batch.json"
        batch.write_text(json.dumps(payload), encoding="utf-8")
        code, _out, error, child = self.invoke_run(batch, self.root / "large-manifest", stdout=self.report_bytes(["small"]))
        self.assertEqual(code, 2, error)
        self.assertEqual(json.loads(error)["category"], "manifest_too_large")
        child.assert_not_called()

    def test_failed_and_interrupted_children_keep_intent_and_refuse_retry(self) -> None:
        batch = self.batch_file("batch.json", [self.task("small")])
        failed_dir = self.root / "failed"
        code, _out, err, child = self.invoke_run(
            batch,
            failed_dir,
            stdout=b"provider error output",
            returncode=1,
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["category"], "provider_failed")
        returned = json.loads((failed_dir / "child-result.json").read_bytes())
        self.assertEqual(returned["state"], "returned")
        self.assertEqual(returned["exit_code"], 1)
        self.assertEqual((failed_dir / "provider-return.json").read_bytes(), b"provider error output")
        self.assertTrue((failed_dir / "submission-intent.json").exists())
        self.assertEqual(self.cli_error(["run", str(batch), str(failed_dir)])[1]["category"], "run_directory_exists")
        self.assertEqual(child.call_count, 1)

        interrupted_dir = self.root / "interrupted"
        code, _out, err, interrupted_child = self.invoke_run(
            batch, interrupted_dir, side_effect=KeyboardInterrupt()
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["category"], "process_interrupted")
        interrupted = json.loads((interrupted_dir / "child-result.json").read_bytes())
        self.assertEqual(interrupted["state"], "interrupted")
        self.assertEqual(interrupted["error_category"], "process_interrupted")
        self.assertTrue((interrupted_dir / "submission-intent.json").exists())
        self.assertEqual(self.cli_error(["run", str(batch), str(interrupted_dir)])[1]["category"], "run_directory_exists")
        self.assertEqual(interrupted_child.call_count, 1)

    def test_stalled_local_child_is_reaped_and_cannot_be_replayed(self) -> None:
        batch = self.batch_file("stalled.json", [self.task("small")])
        run_dir = self.root / "stalled-run"
        pid_log = self.root / "child-pids.txt"
        child_code = (
            "import os, pathlib, sys, time; "
            "pathlib.Path(sys.argv[1]).open('a', encoding='ascii').write(str(os.getpid()) + '\\n'); "
            "sys.stdout.buffer.write(b'partial-before-timeout'); sys.stdout.flush(); "
            "time.sleep(6)"
        )
        command = [router.sys.executable, "-c", child_code, str(pid_log)]
        out = io.StringIO()
        err = io.StringIO()
        started = router.time.perf_counter()
        with patch.object(router, "_command", return_value=command), patch.object(
            router, "ADVISER_PROCESS_TIMEOUT_SECONDS", 1.5, create=True
        ), redirect_stdout(out), redirect_stderr(err), patch.object(
            socket, "socket", side_effect=AssertionError("network access in test")
        ):
            code = router.main(["run", str(batch), str(run_dir)])
        elapsed = router.time.perf_counter() - started

        self.assertLess(elapsed, 5.0)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err.getvalue())["category"], "process_timeout")
        self.assertEqual((run_dir / "provider-return.json").read_bytes(), b"partial-before-timeout")
        returned = json.loads((run_dir / "child-result.json").read_bytes())
        self.assertEqual(returned["state"], "timeout")
        self.assertEqual(returned["error_category"], "process_timeout")
        self.assertGreaterEqual(returned["elapsed_seconds"], 1.0)
        self.assertTrue((run_dir / "submission-intent.json").exists())
        self.assertFalse((run_dir / "packets.json").exists())
        pids = [int(line) for line in pid_log.read_text(encoding="ascii").splitlines()]
        self.assertEqual(len(pids), 1)
        self.assertFalse(_process_is_running(pids[0]))

        code, error = self.cli_error(["run", str(batch), str(run_dir)])
        self.assertEqual(code, 2)
        self.assertEqual(error["category"], "run_directory_exists")
        self.assertEqual(len(pid_log.read_text(encoding="ascii").splitlines()), 1)

    def test_command_is_fixed_openai_adviser_invocation(self) -> None:
        batch = self.batch_file("batch.json", [self.task("small")])
        run_dir = self.root / "command"
        _code, _out, _err, child = self.invoke_run(batch, run_dir, stdout=self.report_bytes(["small"]))
        args, kwargs = child.call_args
        self.assertEqual(
            args[0],
            [
                router.sys.executable,
                "-B",
                str(router.ADVISER_PATH),
                "--provider",
                "openai",
                "--timeout",
                "30",
                str(run_dir.resolve() / "request.json"),
            ],
        )
        self.assertEqual(
            kwargs,
            {
                "capture_output": True,
                "check": False,
                "timeout": 45.0,
            },
        )
        intent = json.loads((run_dir / "submission-intent.json").read_bytes())
        self.assertEqual(intent["command"], args[0])
        self.assertNotIn("OPENAI_API_KEY", json.dumps(intent))

    def test_exact_serialized_request_boundary_precedes_reservation(self) -> None:
        # UTF-8 batch text becomes longer in the transport-input ASCII JSON.
        # One valid control at the limit and the one-byte overflow distinguish
        # the admission boundary from malformed input or missing credentials.
        for size in (32768, 32769):
            with self.subTest(serialized_bytes=size):
                tasks = [self.task(f"t{i}") for i in range(8)]
                for task in tasks:
                    task["context"] = "\u00e9" * 100

                def raw_request():
                    value = {"state": router.REQUEST_STATE, "questions": {
                        t["id"]: {"type": "choice", "instructions": "Objective:\n" + t["objective"] + "\n\nContext:\n" + t["context"],
                                  "choices": router.ROUTE_DESCRIPTIONS} for t in tasks}}
                    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode()

                while len(raw_request()) + 48 <= size:
                    for task in tasks:
                        task["context"] += "\u00e9"
                tasks[-1]["context"] += "a" * (size - len(raw_request()))
                self.assertEqual(len(raw_request()), size)
                batch = self.root / f"boundary-{size}.json"
                batch.write_text(json.dumps({"schema_version": 1, "coordinator_id": "coordinator-42", "tasks": tasks}, ensure_ascii=False), encoding="utf-8")
                self.assertLess(batch.stat().st_size, 32768)
                report = copy.deepcopy(KNOWN_COMPLETE_REPORT)
                report["answers"] = {t["id"]: copy.deepcopy(KNOWN_COMPLETE_REPORT["answers"]["small"]) for t in tasks}
                run_dir = self.root / f"boundary-run-{size}"
                code, _out, error, child = self.invoke_run(batch, run_dir, stdout=json.dumps(report).encode())
                if size == 32768:
                    self.assertEqual(code, 0, error)
                    child.assert_called_once()
                else:
                    self.assertEqual(code, 2, error)
                    self.assertEqual(json.loads(error)["category"], "batch_invalid")
                    child.assert_not_called()
                    self.assertFalse(run_dir.exists())

    def test_compact_run_and_emit_keep_complete_packet_and_hide_assignment(self) -> None:
        batch = self.batch_file(
            "compact-batch.json",
            [self.task("small"), self.task("broad"), self.task("owner_case")],
        )
        run_dir = self.root / "compact-run"
        code, output, error, child = self.invoke_run(batch, run_dir, summary=True)
        self.assertEqual(code, 0, error)
        child.assert_called_once()

        full_raw = (run_dir / "packets.json").read_bytes()
        compact_raw = output.encode("ascii")
        compact = json.loads(output)
        full = json.loads(full_raw)
        self.assertEqual(compact["status"], "complete")
        self.assertEqual(compact["coordinator_id"], "coordinator-42")
        self.assertEqual(compact["packet_path"], str((run_dir / "packets.json").resolve()))
        self.assertEqual(compact["packet_sha256"], hashlib.sha256(full_raw).hexdigest())
        self.assertEqual(compact["eligible_count"], 3)
        self.assertEqual(compact["held_count"], 0)
        self.assertEqual(
            compact["tasks"],
            [
                {
                    "id": task["id"],
                    "route": task["route"],
                    "model": task["model"],
                    "reasoning_effort": task["reasoning_effort"],
                    "assignment_message_sha256": hashlib.sha256(
                        task["assignment_message"].encode("utf-8")
                    ).hexdigest(),
                }
                for task in full["tasks"]
            ],
        )
        self.assertNotIn(b"assignment_message\"", compact_raw)
        self.assertNotIn(b"Objective for", compact_raw)
        self.assertNotIn(b"Context for", compact_raw)
        self.assertLess(len(compact_raw), len(full_raw))

        emit_code, emit_output, emit_error, emit_child = self.invoke_emit(
            batch, run_dir, summary=True
        )
        self.assertEqual(emit_code, 0, emit_error)
        self.assertEqual(emit_output.encode("ascii"), compact_raw)
        emit_child.assert_not_called()

    def test_compact_all_held_is_offline_and_counts_holds(self) -> None:
        batch = self.batch_file(
            "held-compact-batch.json",
            [self.task("held", authorized=False, inputs_ready=False)],
        )
        run_dir = self.root / "held-compact-run"
        code, output, error, child = self.invoke_run(batch, run_dir, summary=True)
        self.assertEqual(code, 0, error)
        child.assert_not_called()
        summary = json.loads(output)
        self.assertEqual(summary["eligible_count"], 0)
        self.assertEqual(summary["held_count"], 1)
        self.assertEqual(summary["tasks"][0]["route"], "hold")
        self.assertTrue((run_dir / "packets.json").is_file())

        emit_code, emit_output, emit_error, emit_child = self.invoke_emit(
            batch, run_dir, summary=True
        )
        self.assertEqual(emit_code, 0, emit_error)
        self.assertEqual(json.loads(emit_output), summary)
        emit_child.assert_not_called()

    def test_compact_emit_rejects_missing_or_altered_stored_packet(self) -> None:
        batch = self.batch_file("tamper-batch.json", [self.task("small")])
        for mode in ("missing", "altered"):
            with self.subTest(mode=mode):
                run_dir = self.root / f"tampered-{mode}"
                code, _output, error, _child = self.invoke_run(
                    batch, run_dir, stdout=self.report_bytes(["small"]), summary=True
                )
                self.assertEqual(code, 0, error)
                packet = run_dir / "packets.json"
                if mode == "missing":
                    packet.unlink()
                else:
                    packet.write_bytes(b"{}\n")
                emit_code, emit_error = self.cli_error(
                    ["emit", str(batch), str(run_dir), "--summary"]
                )
                self.assertEqual(emit_code, 2)
                self.assertEqual(emit_error["category"], "stored_packet_invalid")

    def test_compact_emit_still_rejects_stale_sources(self) -> None:
        batch = self.batch_file("stale-compact-batch.json", [self.task("small")])
        run_dir = self.root / "stale-compact-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"]), summary=True
        )
        self.assertEqual(code, 0, error)
        self.source.write_text("def source(): return 2\n", encoding="utf-8")
        emit_code, emit_error = self.cli_error(
            ["emit", str(batch), str(run_dir), "--summary"]
        )
        self.assertEqual(emit_code, 2)
        self.assertEqual(emit_error["category"], "source_drift")

    def test_native_readiness_reports_metadata_without_transcript_text(self) -> None:
        batch = self.batch_file("readiness-batch.json", [self.task("small")])
        run_dir = self.root / "readiness-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        session = self.root / "native-session.jsonl"
        secret_marker = "TRANSCRIPT-BODY-MUST-NOT-BE-RETURNED"
        self.write_readiness_session(
            session,
            extra_lines=[
                {"type": "response_item", "payload": {"text": secret_marker}}
            ],
        )
        ready_code, ready, ready_error = self.invoke_readiness(batch, run_dir, session)
        self.assertEqual(ready_code, 0, ready_error or json.dumps(ready, sort_keys=True))
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["task_id"], "small")
        self.assertEqual(
            ready["expected"],
            {
                "session_id": "01a1b94c-9a2d-7e11-a6ef-000000000001",
                "source_kind": "native_subagent",
                "parent_thread_id": "coordinator-42",
                "agent_path": "/root/compact_routing",
                "cwd": str(self.root.resolve(strict=True)),
                "model": "gpt-6-luna",
                "effort": "max",
                "approval_policy": "never",
                "sandbox_policy_type": "danger-full-access",
                "packet_coordinator_id": "coordinator-42",
            },
        )
        self.assertEqual(
            ready["observed"],
            {
                "session_id": "01a1b94c-9a2d-7e11-a6ef-000000000001",
                "session_cwd": str(self.root),
                "source_kind": "native_subagent",
                "agent_path": "/root/compact_routing",
                "parent_thread_id": "coordinator-42",
                "turn_id": "turn-2",
                "turn_cwd": str(self.root),
                "model": "gpt-6-luna",
                "effort": "max",
                "approval_policy": "never",
                "sandbox_policy_type": "danger-full-access",
            },
        )
        self.assertEqual(ready["worker_kind"], "native")
        self.assertEqual(ready["packet_coordinator_id"], "coordinator-42")
        self.assertEqual(ready["proof"]["session_path"], str(session.resolve()))
        self.assertEqual(ready["proof"]["session_meta_line"], 1)
        self.assertEqual(ready["proof"]["turn_context_line"], 2)
        self.assertNotIn(secret_marker, json.dumps(ready))

    def test_app_readiness_reports_configuration_and_packet_binding_only(self) -> None:
        coordinator = "coordinator-42"
        batch = self.batch_file(
            "app-readiness-batch.json",
            [self.task("small")],
            coordinator_id=coordinator,
        )
        run_dir = self.root / "app-readiness-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)

        session = self.root / "app-session.jsonl"
        self.write_readiness_session(session, source="vscode")
        ready_code, ready, ready_error = self.invoke_readiness(
            batch,
            run_dir,
            session,
            worker_kind="app",
            agent_path=None,
            parent_thread=coordinator,
        )
        self.assertEqual(ready_code, 0, ready_error or json.dumps(ready, sort_keys=True))
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["worker_kind"], "app")
        self.assertEqual(ready["scope"], "session_configuration_only")
        self.assertEqual(ready["packet_coordinator_id"], coordinator)
        self.assertEqual(ready["expected"]["session_id"], "01a1b94c-9a2d-7e11-a6ef-000000000001")
        self.assertEqual(ready["expected"]["source_kind"], "vscode")
        self.assertEqual(ready["expected"]["packet_coordinator_id"], coordinator)
        self.assertEqual(ready["observed"]["source_kind"], "vscode")
        self.assertEqual(ready["observed"]["model"], "gpt-6-luna")
        self.assertEqual(ready["observed"]["effort"], "max")
        self.assertNotIn("parent_thread_id", ready["expected"])
        self.assertNotIn("agent_path", ready["expected"])
        self.assertNotIn("parent_thread_id", ready["observed"])
        self.assertNotIn("agent_path", ready["observed"])

    def test_readiness_uses_existing_directory_identity_for_session_and_turn_cwd(self) -> None:
        batch = self.batch_file("cwd-identity-batch.json", [self.task("small")])
        run_dir = self.root / "cwd-identity-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        expected_cwd = self.root / "identity%20-compatibility#directory"
        expected_cwd.mkdir()
        aliases = [("case-or-native-spelling", self.same_object_path_alias(expected_cwd))]
        if os.name == "nt":
            aliases.insert(0, ("windows-8dot3", self.windows_short_path_alias(expected_cwd)))
        for _alias_name, alias in aliases:
            self.assertTrue(Path(alias).samefile(expected_cwd), "the cwd alias must name the same directory")
        session = self.root / "cwd-identity-session.jsonl"

        for alias_name, alias in aliases:
            for worker_kind in ("native", "app"):
                for observed_key in ("session_cwd", "turn_cwd"):
                    with self.subTest(alias=alias_name, worker_kind=worker_kind, field=observed_key):
                        session_cwd = alias if observed_key == "session_cwd" else str(expected_cwd)
                        turn_cwd = alias if observed_key == "turn_cwd" else str(expected_cwd)
                        self.write_readiness_session(
                            session,
                            source="vscode" if worker_kind == "app" else None,
                            session_cwd=session_cwd,
                            turn_cwd=turn_cwd,
                        )
                        ready_code, ready, ready_error = self.invoke_readiness(
                            batch,
                            run_dir,
                            session,
                            cwd=str(expected_cwd),
                            worker_kind=worker_kind,
                            agent_path=None if worker_kind == "app" else "/root/compact_routing",
                        )
                        self.assertEqual(
                            (ready_code, ready.get("status"), ready.get("category")),
                            (0, "ready", None),
                            ready_error or json.dumps(ready, sort_keys=True),
                        )
                        self.assertEqual(ready["expected"]["cwd"], str(expected_cwd.resolve(strict=True)))
                        self.assertEqual(ready["observed"][observed_key], alias)

    def test_readiness_blocks_nonmatching_and_unsafe_cwd_before_untrusted_lookup(self) -> None:
        batch = self.batch_file("cwd-blocked-batch.json", [self.task("small")])
        run_dir = self.root / "cwd-blocked-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        expected_cwd = self.root / "expected-cwd"
        expected_cwd.mkdir()
        different_cwd = self.root / "different-cwd"
        different_cwd.mkdir()
        regular_file = self.root / "not-a-directory.txt"
        regular_file.write_text("ordinary file", encoding="utf-8")
        missing_cwd = self.root / "missing-cwd"
        session = self.root / "cwd-blocked-session.jsonl"
        blocked_values = [
            ("different existing directory", str(different_cwd)),
            ("traversal to different directory", str(different_cwd) + os.sep + ".." + os.sep + different_cwd.name),
            ("missing directory", str(missing_cwd)),
            ("regular file", str(regular_file)),
            ("malformed NUL path", str(expected_cwd) + "\x00suffix"),
        ]
        if os.name == "nt":
            untrusted_values = [
                "file:///C:/untrusted/path",
                "https://example.invalid/untrusted/path",
                r"\\server\share\untrusted",
                r"\\?\C:\untrusted",
                r"\\.\PhysicalDrive0",
                "F:relative-path",
            ]
        else:
            untrusted_values = [
                "file:///untrusted/path",
                "https://example.invalid/untrusted/path",
                "//authority/share/untrusted",
                "relative-path",
            ]
        blocked_values.extend(("unsupported URI/remote/device form", value) for value in untrusted_values)

        for name, bad_cwd in blocked_values:
            with self.subTest(cwd=name):
                self.write_readiness_session(
                    session,
                    session_cwd=bad_cwd,
                    turn_cwd=str(expected_cwd),
                )
                ready_code, blocked, ready_error = self.invoke_readiness(
                    batch, run_dir, session, cwd=str(expected_cwd)
                )
                self.assertEqual(
                    (ready_code, blocked.get("status"), blocked.get("category")),
                    (2, "blocked", "cwd_mismatch"),
                    ready_error or json.dumps(blocked, sort_keys=True),
                )

        literal_percent_cwd = self.root / "literal%20#directory"
        decoded_space_cwd = self.root / "literal #directory"
        literal_percent_cwd.mkdir()
        decoded_space_cwd.mkdir()
        self.write_readiness_session(
            session,
            session_cwd=str(literal_percent_cwd),
            turn_cwd=str(literal_percent_cwd),
        )
        ready_code, blocked, ready_error = self.invoke_readiness(
            batch, run_dir, session, cwd=str(decoded_space_cwd)
        )
        self.assertEqual(
            (ready_code, blocked.get("status"), blocked.get("category")),
            (2, "blocked", "cwd_mismatch"),
            ready_error or json.dumps(blocked, sort_keys=True),
        )
        ready_code, ready, ready_error = self.invoke_readiness(
            batch, run_dir, session, cwd=str(literal_percent_cwd)
        )
        self.assertEqual(
            (ready_code, ready.get("status"), ready.get("category")),
            (0, "ready", None),
            ready_error or json.dumps(ready, sort_keys=True),
        )

        # URI, authority, device and malformed inputs must be rejected before
        # pathlib performs a stat or samefile lookup on the observed value.
        for bad_cwd in [*untrusted_values, str(expected_cwd) + "\x00suffix"]:
            with self.subTest(no_lookup=bad_cwd):
                observed_paths = {str(Path(bad_cwd))}
                original_stat = Path.stat
                original_samefile = Path.samefile

                def guarded_stat(path, *args, **kwargs):
                    if str(path) in observed_paths:
                        raise AssertionError("untrusted cwd was stat'ed before rejection")
                    return original_stat(path, *args, **kwargs)

                def guarded_samefile(path, other):
                    if str(path) in observed_paths:
                        raise AssertionError("untrusted cwd was compared before rejection")
                    return original_samefile(path, other)

                self.write_readiness_session(
                    session,
                    session_cwd=bad_cwd,
                    turn_cwd=str(expected_cwd),
                )
                with patch.object(Path, "stat", guarded_stat), patch.object(
                    Path, "samefile", guarded_samefile
                ):
                    ready_code, blocked, ready_error = self.invoke_readiness(
                        batch, run_dir, session, cwd=str(expected_cwd)
                    )
                self.assertEqual(
                    (ready_code, blocked.get("status"), blocked.get("category")),
                    (2, "blocked", "cwd_mismatch"),
                    ready_error or json.dumps(blocked, sort_keys=True),
                )

        denied_cwd = self.root / "inaccessible-cwd"
        denied_cwd.mkdir()
        denied_calls = []
        original_samefile = Path.samefile

        def denied_samefile(path, other):
            if str(path) == str(denied_cwd):
                denied_calls.append(str(path))
                raise PermissionError("simulated denied directory identity lookup")
            return original_samefile(path, other)

        self.write_readiness_session(session, session_cwd=str(denied_cwd), turn_cwd=str(expected_cwd))
        with patch.object(Path, "samefile", denied_samefile):
            ready_code, blocked, ready_error = self.invoke_readiness(
                batch, run_dir, session, cwd=str(expected_cwd)
            )
        self.assertEqual(denied_calls, [str(denied_cwd)])
        self.assertEqual(
            (ready_code, blocked.get("status"), blocked.get("category")),
            (2, "blocked", "cwd_mismatch"),
            ready_error or json.dumps(blocked, sort_keys=True),
        )

        if os.name != "nt":
            case_distinct = expected_cwd.with_name(expected_cwd.name.swapcase())
            case_distinct.mkdir()
            self.write_readiness_session(
                session, session_cwd=str(case_distinct), turn_cwd=str(expected_cwd)
            )
            ready_code, blocked, ready_error = self.invoke_readiness(
                batch, run_dir, session, cwd=str(expected_cwd)
            )
            self.assertEqual(
                (ready_code, blocked.get("status"), blocked.get("category")),
                (2, "blocked", "cwd_mismatch"),
                ready_error or json.dumps(blocked, sort_keys=True),
            )

    def test_equivalent_cwd_does_not_relax_runtime_or_source_guards(self) -> None:
        batch = self.batch_file("cwd-guard-batch.json", [self.task("small")])
        run_dir = self.root / "cwd-guard-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        expected_cwd = self.root / "guard-identity-directory"
        expected_cwd.mkdir()
        alias = self.same_object_path_alias(expected_cwd)
        session = self.root / "cwd-guard-session.jsonl"
        wrong_latest = {
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-2",
                "cwd": str(expected_cwd),
                "model": "gpt-6-luna",
                "effort": "medium",
                "approval_policy": "never",
                "sandbox_policy": {"type": "danger-full-access"},
            },
        }
        cases = [
            ("session thread", {"session_id": "01a1b94c-9a2d-7e11-a6ef-000000000002"}, "session_id_mismatch"),
            ("parent", {"parent_thread_id": "different-parent"}, "parent_thread_mismatch"),
            ("agent", {"agent_path": "/root/different-agent"}, "agent_path_mismatch"),
            ("source", {"source": "other_app"}, "source_mismatch"),
            ("model", {"model": "gpt-6.1-sol"}, "model_mismatch"),
            ("effort", {"effort": "medium"}, "effort_mismatch"),
            ("approval", {"approval_policy": "on-request"}, "approval_policy_mismatch"),
            ("sandbox", {"sandbox_type": "workspace-write"}, "sandbox_policy_mismatch"),
            ("latest turn", {"turn_contexts": [
                {"type": "turn_context", "payload": {
                    "turn_id": "turn-1", "cwd": str(expected_cwd), "model": "gpt-6-luna",
                    "effort": "max", "approval_policy": "never",
                    "sandbox_policy": {"type": "danger-full-access"},
                }},
                wrong_latest,
            ]}, "effort_mismatch"),
        ]
        for name, kwargs, category in cases:
            with self.subTest(guard=name):
                self.write_readiness_session(
                    session,
                    session_cwd=alias,
                    turn_cwd=str(expected_cwd),
                    **kwargs,
                )
                ready_code, blocked, ready_error = self.invoke_readiness(
                    batch, run_dir, session, cwd=str(expected_cwd)
                )
                self.assertEqual(
                    (ready_code, blocked.get("status"), blocked.get("category")),
                    (2, "blocked", category),
                    ready_error or json.dumps(blocked, sort_keys=True),
                )

    def test_readiness_rejects_wrong_sources_missing_nested_agent_and_cli_mismatch(self) -> None:
        coordinator = "coordinator-42"
        batch = self.batch_file(
            "readiness-source-batch.json",
            [self.task("small")],
            coordinator_id=coordinator,
        )
        run_dir = self.root / "readiness-source-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        session = self.root / "readiness-source.jsonl"

        self.write_readiness_session(
            session,
            source={"subagent": {"thread_spawn": {"parent_thread_id": coordinator}}},
            legacy_agent_path="/root/compact_routing",
        )
        blocked_code, blocked, blocked_error = self.invoke_readiness(
            batch, run_dir, session, parent_thread=coordinator
        )
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "agent_path_missing")

        app_sources: list[tuple[str, object]] = [
            ("unknown", "other_app"),
            (
                "native_subagent",
                {"subagent": {"thread_spawn": {"parent_thread_id": coordinator}}},
            ),
        ]
        for name, source in app_sources:
            with self.subTest(app_source=name):
                self.write_readiness_session(session, source=source)
                blocked_code, blocked, blocked_error = self.invoke_readiness(
                    batch,
                    run_dir,
                    session,
                    worker_kind="app",
                    agent_path=None,
                    parent_thread=coordinator,
                )
                self.assertEqual(blocked_code, 2, blocked_error)
                self.assertEqual(blocked["category"], "source_mismatch")

        self.write_readiness_session(session, source="vscode")
        blocked_code, blocked, blocked_error = self.invoke_readiness(
            batch,
            run_dir,
            session,
            worker_kind="app",
            agent_path="/root/compact_routing",
            parent_thread=coordinator,
        )
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "invalid_cli")

        blocked_code, blocked, blocked_error = self.invoke_readiness(
            batch,
            run_dir,
            session,
            agent_path=None,
            parent_thread=coordinator,
        )
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "invalid_cli")

    def test_readiness_requires_packet_coordinator_binding(self) -> None:
        coordinator = "coordinator-42"
        batch = self.batch_file(
            "readiness-packet-binding-batch.json",
            [self.task("small")],
            coordinator_id=coordinator,
        )
        run_dir = self.root / "readiness-packet-binding-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        session = self.root / "readiness-packet-binding.jsonl"
        self.write_readiness_session(session, source="vscode")
        blocked_code, blocked, blocked_error = self.invoke_readiness(
            batch,
            run_dir,
            session,
            worker_kind="app",
            agent_path=None,
            parent_thread="different-coordinator",
        )
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "coordinator_mismatch")
        self.assertEqual(blocked["expected"]["packet_coordinator_id"], "different-coordinator")
        self.assertEqual(blocked["observed"]["packet_coordinator_id"], coordinator)

    def test_native_readiness_blocks_wrong_metadata_and_uses_latest_turn(self) -> None:
        batch = self.batch_file("readiness-mismatch-batch.json", [self.task("small")])
        run_dir = self.root / "readiness-mismatch-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        session = self.root / "native-session-mismatch.jsonl"
        cases: list[tuple[str, dict[str, object], str]] = [
            ("thread", {"session_id": "wrong-thread"}, "session_id_mismatch"),
            ("parent", {"parent_thread_id": "wrong-parent"}, "parent_thread_mismatch"),
            ("agent", {"agent_path": "/root/other"}, "agent_path_mismatch"),
            ("session cwd", {"session_cwd": str(self.root / "wrong")}, "cwd_mismatch"),
            ("turn cwd", {"turn_cwd": str(self.root / "wrong")}, "cwd_mismatch"),
            ("model", {"model": "gpt-6.1-sol"}, "model_mismatch"),
            ("effort", {"effort": "medium"}, "effort_mismatch"),
            ("approval", {"approval_policy": "on-request"}, "approval_policy_mismatch"),
            ("sandbox", {"sandbox_type": "workspace-write"}, "sandbox_policy_mismatch"),
        ]
        for name, kwargs, category in cases:
            with self.subTest(metadata=name):
                self.write_readiness_session(session, **kwargs)
                blocked_code, blocked, blocked_error = self.invoke_readiness(
                    batch, run_dir, session
                )
                self.assertEqual(blocked_code, 2, blocked_error)
                self.assertEqual(blocked["status"], "blocked")
                self.assertEqual(blocked["category"], category)
                self.assertNotIn("TRANSCRIPT", json.dumps(blocked))
                self.assertIn("observed", blocked)
                self.assertEqual(blocked["proof"]["session_path"], str(session.resolve()))

        valid_turn = {
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-1",
                "cwd": str(self.root),
                "model": "gpt-6-luna",
                "effort": "max",
                "approval_policy": "never",
                "sandbox_policy": {"type": "danger-full-access"},
            },
        }
        wrong_latest_turn = copy.deepcopy(valid_turn)
        wrong_latest_turn["payload"]["turn_id"] = "turn-2"
        wrong_latest_turn["payload"]["effort"] = "medium"
        self.write_readiness_session(
            session, turn_contexts=[valid_turn, wrong_latest_turn]
        )
        blocked_code, blocked, blocked_error = self.invoke_readiness(
            batch, run_dir, session
        )
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "effort_mismatch")
        self.assertEqual(blocked["observed"]["effort"], "medium")
        self.assertEqual(blocked["proof"]["turn_context_line"], 3)

    def test_native_readiness_rejects_missing_ambiguous_malformed_and_oversized_evidence(self) -> None:
        batch = self.batch_file("readiness-invalid-batch.json", [self.task("small")])
        run_dir = self.root / "readiness-invalid-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        session = self.root / "native-session-invalid.jsonl"

        self.write_readiness_session(session, include_session=False)
        blocked_code, blocked, blocked_error = self.invoke_readiness(batch, run_dir, session)
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "session_metadata_missing")

        duplicate = {
            "type": "session_meta",
            "payload": {
                "id": "01a1b94c-9a2d-7e11-a6ef-000000000001",
                "cwd": str(self.root),
                "source": {
                    "subagent": {
                        "thread_spawn": {
                            "parent_thread_id": "01a1b94c-9a2d-7e11-a6ef-000000000002"
                        }
                    }
                },
                "agent_path": "/root/compact_routing",
            },
        }
        self.write_readiness_session(session, extra_lines=[duplicate])
        blocked_code, blocked, blocked_error = self.invoke_readiness(batch, run_dir, session)
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "session_metadata_ambiguous")

        self.write_readiness_session(session, turn_contexts=[])
        blocked_code, blocked, blocked_error = self.invoke_readiness(batch, run_dir, session)
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "turn_context_missing")

        valid_turn = {
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-1",
                "cwd": str(self.root),
                "model": "gpt-6-luna",
                "effort": "max",
                "approval_policy": "never",
                "sandbox_policy": {"type": "danger-full-access"},
            },
        }
        missing_latest = copy.deepcopy(valid_turn)
        missing_latest["payload"]["turn_id"] = "turn-2"
        del missing_latest["payload"]["sandbox_policy"]
        self.write_readiness_session(session, turn_contexts=[valid_turn, missing_latest])
        blocked_code, blocked, blocked_error = self.invoke_readiness(batch, run_dir, session)
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "turn_context_invalid")

        self.write_readiness_session(session)
        with session.open("a", encoding="utf-8") as target:
            target.write("{malformed json line}\n")
        blocked_code, blocked, blocked_error = self.invoke_readiness(batch, run_dir, session)
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "session_invalid")

        self.write_readiness_session(session)
        with session.open("ab") as target:
            target.write(b"\xff\n")
        blocked_code, blocked, blocked_error = self.invoke_readiness(batch, run_dir, session)
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "session_invalid")

        self.write_readiness_session(session)
        with patch.object(router, "MAX_SESSION_BYTES", 8):
            blocked_code, blocked, blocked_error = self.invoke_readiness(batch, run_dir, session)
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["category"], "session_too_large")

    def test_native_readiness_reuses_source_drift_check_without_provider_call(self) -> None:
        batch = self.batch_file("readiness-stale-batch.json", [self.task("small")])
        run_dir = self.root / "readiness-stale-run"
        code, _output, error, _child = self.invoke_run(
            batch, run_dir, stdout=self.report_bytes(["small"])
        )
        self.assertEqual(code, 0, error)
        session = self.root / "native-session-stale.jsonl"
        self.write_readiness_session(session)
        self.source.write_text("def source(): return 3\n", encoding="utf-8")
        with patch.object(router.subprocess, "run") as child:
            blocked_code, blocked, blocked_error = self.invoke_readiness(
                batch, run_dir, session
            )
        self.assertEqual(blocked_code, 2, blocked_error)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["category"], "source_drift")
        self.assertIn("observed", blocked)
        self.assertEqual(blocked["observed"]["session_id"], "01a1b94c-9a2d-7e11-a6ef-000000000001")
        self.assertEqual(blocked["proof"]["turn_context_line"], 2)
        child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
