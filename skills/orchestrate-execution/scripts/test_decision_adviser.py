"""CLI and verified HTTPS-boundary tests for decision_adviser."""

from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
from threading import Thread
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest


SCRIPT = Path(__file__).with_name("decision_adviser.py")
LOCAL_RUNNER = """
import os, runpy, socket, sys
script = sys.argv[1]
arguments = sys.argv[2:]
port = int(os.environ['DECISION_ADVISER_TEST_PORT'])
allowed_hosts = {'api.openai.com'}
if os.environ.get('DECISION_ADVISER_TEST_BLOCK_ENVIRONMENT') == '1':
    real_environment_get = os.environ.get
    def blocked_credential_get(name, *args, **kwargs):
        if name in ('OPENAI_API_KEY', 'TYPESAFE_API_KEY'):
            raise AssertionError('credential lookup blocked by test')
        return real_environment_get(name, *args, **kwargs)
    os.environ.get = blocked_credential_get
real_create_connection = socket.create_connection
real_getaddrinfo = socket.getaddrinfo
def local_getaddrinfo(host, service, *args, **kwargs):
    if host in allowed_hosts:
        host, service = '127.0.0.1', port
    elif host not in ('127.0.0.1', '::1', 'localhost'):
        raise OSError('test fixture blocks nonlocal DNS')
    return real_getaddrinfo(host, service, *args, **kwargs)
def local_create_connection(address, timeout=None, source_address=None, *, all_errors=False):
    host, _port = address[:2]
    if host not in allowed_hosts:
        raise OSError('test fixture blocks non-provider connections')
    return real_create_connection(('127.0.0.1', port), timeout, source_address, all_errors=all_errors)
socket.getaddrinfo = local_getaddrinfo
socket.create_connection = local_create_connection
for name in ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
    os.environ.pop(name, None)
sys.argv = [script, *arguments]
runpy.run_path(script, run_name='__main__')
"""

# Test-only self-signed certificate for the loopback HTTPS fixture. The key is
# not a provider credential and must never be used outside this test server.
TEST_CERTIFICATE = """-----BEGIN CERTIFICATE-----
MIIDTTCCAjWgAwIBAgIUEIBLbtzh3hQJlbM9I/EHiqna51owDQYJKoZIhvcNAQEL
BQAwLDEqMCgGA1UEAwwhQ29kZXggbG9jYWwgZGVjaXNpb24tYWR2aXNlciB0ZXN0
MB4XDTI2MTAxMzE4MzIyMloXDTM2MTAxMDE4MzcyMlowLDEqMCgGA1UEAwwhQ29k
ZXggbG9jYWwgZGVjaXNpb24tYWR2aXNlciB0ZXN0MIIBIjANBgkqhkiG9w0BAQEF
AAOCAQ8AMIIBCgKCAQEApDMxAalgspt4sXz1nPDZ9dqyk85JeaPxHSo+dNiaSM3D
a/deTk8O4Q9PBIbvkBREsyayeRc15bgSkMMCs34cKBiMdtGmq2Jh2YG/qJqGf6XE
UXtlxrpIl2Q9RS5Ea0+8r/0Z4njveBuaoGtuBu+nlzSqZMad9ofKh36NYcEXFTWY
i6xB22/03iDjkdm4QWO8hcnxyab2nlLcqdQoshT2pWejsA+wE0JObFPQdyQIKAp1
ARd2MxyK0J/4kS+ovUt6yrjyi5AZP7/xbw+6KfNyH2c5UrLGSgUIXEIWW3zktyEk
QSsilc2NxavoFu33tuq2Ls4V0rFVAk6B3T/uV2hdpQIDAQABo2cwZTASBgNVHRMB
Af8ECDAGAQH/AgEAMCoGA1UdEQQjMCGCDmFwaS5vcGVuYWkuY29tgg9hcGkudHlw
ZXNhZmUuYWkwDgYDVR0PAQH/BAQDAgGmMBMGA1UdJQQMMAoGCCsGAQUFBwMBMA0G
CSqGSIb3DQEBCwUAA4IBAQA+73w9e6Tm1UGWGLGg3x6hXOfvJaIO+UM9SitFzDzE
VvDtThNAv0ryHJiuO7IkWdg14BTjXOw7f18gdt+lFcz2bW/w1iAE9Wz8cfXpmofl
IHrZTOATn2pdokspcR5mDAe6nV3cqyrd3HlvNh7HkcIoyV+j2uHOV280jwSfSnKn
oMSUXEWswKa049MKS50RpnAJpy+ngP9oA7z5JjYxECz+VbCVrpSXMXut624XJWRs
ztFmOQBcxBvU7/l3CwhUzSa3QNwU2AL/65eKecDe8bGq5/aj2LvwBVNFahTUgPW3
OQa1Oc1wKJr4Bh8wv3TIqDZHKY8+Cr8s3B7AX3HF1nwj
-----END CERTIFICATE-----
"""
TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCkMzEBqWCym3ix
fPWc8Nn12rKTzkl5o/EdKj502JpIzcNr915OTw7hD08Ehu+QFESzJrJ5FzXluBKQ
wwKzfhwoGIx20aarYmHZgb+omoZ/pcRRe2XGukiXZD1FLkRrT7yv/RnieO94G5qg
a24G76eXNKpkxp32h8qHfo1hwRcVNZiLrEHbb/TeIOOR2bhBY7yFyfHJpvaeUtyp
1CiyFPalZ6OwD7ATQk5sU9B3JAgoCnUBF3YzHIrQn/iRL6i9S3rKuPKLkBk/v/Fv
D7op83IfZzlSssZKBQhcQhZbfOS3ISRBKyKVzY3Fq+gW7fe26rYuzhXSsVUCToHd
P+5XaF2lAgMBAAECggEACQvr+4o0Mmr37Zlzo8uuSoob1CJlsG68ok15RvFHINM7
XNeyabCX4oT4JsjzanX/afpsE1lYxhkL5s9jtvVwAjKGDKbU3rTrLLNmFpk6504A
ALhCfX42cSbb7FOV/+6S+ARDGJPup6inroZ0t6udCWrkp2w8+D/3g9sQWY4soiWs
74Sc9MvYBURkgCSk9MFmnLjf3j5vkoTTt27fraMAvJ8qxYPb65MmjMNWqJrKFma5
x1XQauE3PbKB01DPPbl6WnYFCdniqs6PIkSnWN5ZZq1nKd1fH54DU1Esw3JDB71I
yKKHYKQ4w8YzfBlH+2xAC70okW1NjC86XpdoTwKUWQKBgQDVW+mw83wV6HaNQmE5
Kj6GwV87BZt4TbGzBpNsGc3dck2KrAuLSrt31YIxrtQdvivcElrZXydoxoB4jvsT
636kot96soZgcUUsqyFr3npSOn/gAHKeZJvYOTAGD1ExF3jyvo1/x3cNemOEGK0l
MvJp5y4yoESLSCif42PqbE1wmQKBgQDFBCdHzCgQ3WyHgxfIWrR0NANxSzFrfo/P
oVUKnm7hyGxCjMEPSao51jFtuV+x5KmtC8N0RwkZrfjAfIhhYS27lyce6eZS9rLs
1fRS+PxJfhP5QFiU3oqsoXLe/wM8y9KgAz2ViSaY96RCAtfC68AKoLH2eb29O2VQ
7bvVhUQg7QKBgQC2aj8C6ynMEVRKsdYt6dBLpkilTcX+tW6YgabJZcZ87p0dUrsL
/HkLm6AUmkUAqPcW0Rqbfp9TFWQBrz07arx8RkSLwtbg3fcmmamZcD1k0F9ERR26
Doqv8zT7+VyRfGAMKp8QAJnpDBrJdc+TXluj7+OvpRb1flw9V0y1wKL1AQKBgQCo
axyJK+U0RZT5Yv95rtCEZdJrjzP4CIE3pVrlcPqo2IRzf4+qWfbC6m/mtIkxsZ+6
5kt3oyIMacQ0CEEtvb0yl8xBiQHz+iCKhXwPUfmZecXpVTBkUrmJSZrBNo618idj
0mFa65urOEeahoObhZzteOGpKfkhQx0hSZlAtmO/IQKBgDP4G+Ef4mCOmSpShBff
boe9l+ZhzIWf3yqRrYq3R48KUrabgBXtAihGoNqp4uQxgiSMdPgQ257fE4+xaqt6
jRanMl3hqhuuITghZ4djnp7WSYDAjijGJtj4rMXVX99IWJ/Q7MMO1FH4nsllSH1K
rwoya9bT/WqVo1rpFfCnFeQI
-----END PRIVATE KEY-----
"""


def sample_request():
    return {
        "state": "PRIVATE-STATE-MUST-NOT-APPEAR",
        "questions": {
            "damaged": {
                "type": "predicate",
                "instructions": "Does the customer report damage?",
            },
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "choices": {
                    "billing": "Payments, invoices, and refunds.",
                    "technical": "Problems using the product.",
                },
            },
            "severity": {
                "type": "score",
                "instructions": "How severe is the damage?",
                "levels": ["minor", "moderate", "major"],
            },
        },
    }


class LocalHttpsServer:
    def __init__(self, directory: Path):
        self.requests = []
        self.status = 200
        self.body = b"{}"
        self.headers = {"Content-Type": "application/json"}
        self.delay_seconds = 0.0
        cert_path = directory / "fixture-cert.pem"
        key_path = directory / "fixture-key.pem"
        cert_path.write_text(TEST_CERTIFICATE, encoding="ascii")
        key_path.write_text(TEST_PRIVATE_KEY, encoding="ascii")
        self.cert_path = cert_path
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def _record(self, method):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                fixture.requests.append(
                    {
                        "method": method,
                        "path": self.path,
                        "host": self.headers.get("Host"),
                        "authorization": self.headers.get("Authorization"),
                        "content_type": self.headers.get("Content-Type"),
                        "body": body,
                    }
                )
                if fixture.delay_seconds:
                    time.sleep(fixture.delay_seconds)
                response_body = fixture.body
                try:
                    self.send_response(fixture.status)
                    for name, value in fixture.headers.items():
                        self.send_header(name, value)
                    self.send_header("Content-Length", str(len(response_body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(response_body)
                except OSError:
                    pass

            def do_POST(self):
                self._record("POST")

            def do_GET(self):
                self._record("GET")

            def log_message(self, _format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(str(cert_path), str(key_path))
        self.server.socket = tls.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def respond(self, payload, *, status=200, headers=None, delay=0.0):
        self.status = status
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}
        if headers:
            self.headers.update(headers)
        self.delay_seconds = delay


class DecisionAdviserCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.fixture = LocalHttpsServer(self.directory)
        self.addCleanup(self.fixture.close)

    def write_request(self, value):
        path = self.directory / "request.json"
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def run_cli(self, *arguments, input_text=None, env_overrides=None, timeout=8):
        environment = os.environ.copy()
        for name in (
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
        ):
            environment.pop(name, None)
        environment.update(
            {
                "SSL_CERT_FILE": str(self.fixture.cert_path),
                "SSL_CERT_DIR": "",
                "DECISION_ADVISER_TEST_PORT": str(self.fixture.port),
                "OPENAI_API_KEY": "DUMMY_OPENAI_KEY_FOR_LOCAL_TESTS",
            }
        )
        if env_overrides:
            for name, value in env_overrides.items():
                if value is None:
                    environment.pop(name, None)
                else:
                    environment[name] = value
        return subprocess.run(
            [sys.executable, "-B", "-c", LOCAL_RUNNER, str(SCRIPT), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input_text,
            env=environment,
            cwd=SCRIPT.parent,
            timeout=timeout,
            check=False,
        )

    def cli_report(self, result):
        self.assertEqual(result.stderr, "")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            self.fail(f"CLI did not return normalized JSON: {error}")

    def set_response(self, payload):
        self.fixture.respond(payload)

    def test_retired_provider_is_rejected_before_credentials_and_network(self):
        path = self.write_request(sample_request())
        result = self.run_cli(
            "--provider", "jev", str(path),
            env_overrides={"DECISION_ADVISER_TEST_BLOCK_ENVIRONMENT": "1"},
        )
        report = self.cli_report(result)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["provider"], "unknown")
        self.assertFalse(report["attempted_call"])
        self.assertEqual(report["error"], {"category": "invalid_provider", "http_status": None})
        self.assertNotIn("jev", result.stdout.lower())
        self.assertEqual(self.fixture.requests, [])

    def test_openai_named_question_array_and_source_usage_are_normalized(self):
        response = {
            "model": "gpt-6-luna",
            "answers": [
                {"type": "predicate", "name": "damaged", "probability": 0.95},
                {
                    "type": "choice",
                    "name": "department",
                    "choice": "billing",
                    "probabilities": [
                        {"value": "billing", "probability": 0.8},
                        {"value": "technical", "probability": 0.2},
                    ],
                    "confidence": 0.75,
                },
                {
                    "type": "score",
                    "name": "severity",
                    "score": 1.2,
                    "probabilities": [
                        {"value": 0, "label": "minor", "probability": 0.2},
                        {"value": 1, "label": "moderate", "probability": 0.4},
                        {"value": 2, "label": "major", "probability": 0.4},
                    ],
                    "confidence": 0.8,
                },
            ],
            "usage": {
                "input_tokens": 12,
                "output_tokens": 5,
                "total_tokens": 17,
                "input_tokens_details": {"cached_tokens": 2, "cache_write_tokens": 1},
                "output_tokens_details": {"reasoning_tokens": 3},
            },
        }
        self.set_response(response)
        path = self.write_request(sample_request())
        result = self.run_cli(
            "--provider", "openai", str(path),
            env_overrides={"UNSELECTED_PROVIDER_KEY": "UNSELECTED_OTHER_PROVIDER_KEY"},
        )
        report = self.cli_report(result)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["provider"], "openai")
        self.assertEqual(report["model"], "gpt-6-luna")
        self.assertEqual(report["answers"]["damaged"]["probability_yes"], 0.95)
        self.assertEqual(report["answers"]["department"]["choice"], "billing")
        self.assertEqual(report["answers"]["department"]["confidence_semantics"], "separate_provider_field")
        self.assertEqual(report["answers"]["severity"]["score"], 1.2)
        self.assertEqual(report["usage"]["total_tokens"], 17)
        self.assertEqual(report["usage"]["input_tokens_details"]["cached_tokens"], 2)
        self.assertEqual(report["usage"]["output_tokens_details"]["reasoning_tokens"], 3)
        self.assertEqual(report["error"], None)
        self.assertEqual(len(self.fixture.requests), 1)
        request = self.fixture.requests[0]
        self.assertEqual(request["path"], "/v1/decisions")
        self.assertEqual(request["host"], "api.openai.com")
        self.assertEqual(request["authorization"], "Bearer DUMMY_OPENAI_KEY_FOR_LOCAL_TESTS")
        wire = json.loads(request["body"])
        self.assertEqual(wire["model"], "gpt-6-luna")
        self.assertEqual(wire["input"], sample_request()["state"])
        self.assertEqual([q["name"] for q in wire["questions"]], ["damaged", "department", "severity"])
        self.assertEqual(
            wire["questions"][1]["choices"],
            [
                {"value": "billing", "description": "Payments, invoices, and refunds."},
                {"value": "technical", "description": "Problems using the product."},
            ],
        )
        self.assertEqual(
            wire["questions"][2]["levels"],
            [{"label": "minor"}, {"label": "moderate"}, {"label": "major"}],
        )
        self.assertNotIn("PRIVATE-STATE-MUST-NOT-APPEAR", result.stdout)
        self.assertNotIn("DUMMY_OPENAI_KEY", result.stdout)

    def test_stdin_request_and_partial_refusal_remain_unresolved(self):
        response = {
            "model": "gpt-6-luna",
            "answers": [
                {"type": "predicate", "name": "first", "probability": 0.8},
                {"type": "refusal", "name": "second", "reason": "PRIVATE-REFUSAL-TEXT"},
            ],
            "usage": {"input_tokens": 7, "output_tokens": 0},
        }
        self.set_response(response)
        request = {
            "state": "synthetic state",
            "questions": {
                name: {"type": "predicate", "instructions": f"Check {name}."}
                for name in ("first", "second", "third")
            },
        }
        result = self.run_cli(
            "--provider", "openai", "-",
            input_text=json.dumps(request),
        )
        report = self.cli_report(result)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["answers"]["first"]["probability_yes"], 0.8)
        self.assertEqual(report["answers"]["second"]["reason"], "refusal")
        self.assertEqual(report["answers"]["third"]["reason"], "missing_answer")
        self.assertNotIn("PRIVATE-REFUSAL-TEXT", result.stdout)
        self.assertEqual(len(self.fixture.requests), 1)

    def test_invalid_requests_and_timeouts_stop_before_http(self):
        normal = sample_request()
        duplicate_key = (
            b'{"state":"one","state":"two","questions":{"q":'
            b'{"type":"predicate","instructions":"Check."}}}'
        )
        nonfinite = b'{"state":"x","questions":{"q":{"type":"predicate","instructions":"Check."}},"extra":NaN}'
        unexpected = dict(normal, extra="DO-NOT-ECHO")
        non_ascii_name = {
            "state": "x",
            "questions": {"nämé": {"type": "predicate", "instructions": "Check."}},
        }
        too_many_questions = {
            "state": "x",
            "questions": {
                f"q{index}": {"type": "predicate", "instructions": "Check."}
                for index in range(17)
            },
        }
        valid_predicate = {"type": "predicate", "instructions": "Check."}
        overlong_name = {"a" * 65: valid_predicate}
        overlong_instructions = {
            "q": {"type": "predicate", "instructions": "x" * 2049}
        }
        too_few_choices = {
            "q": {
                "type": "choice",
                "instructions": "Choose.",
                "choices": {"one": "One."},
            }
        }
        too_many_choices = {
            "q": {
                "type": "choice",
                "instructions": "Choose.",
                "choices": {f"option-{index}": "Option." for index in range(33)},
            }
        }
        overlong_choice_label = {
            "q": {
                "type": "choice",
                "instructions": "Choose.",
                "choices": {"x" * 65: "First.", "second": "Second."},
            }
        }
        overlong_description = {
            "q": {
                "type": "choice",
                "instructions": "Choose.",
                "choices": {"first": "x" * 513, "second": "Second."},
            }
        }
        too_few_levels = {
            "q": {"type": "score", "instructions": "Score.", "levels": ["only"]}
        }
        too_many_levels = {
            "q": {
                "type": "score",
                "instructions": "Score.",
                "levels": [f"level-{index}" for index in range(11)],
            }
        }
        overlong_level = {
            "q": {
                "type": "score",
                "instructions": "Score.",
                "levels": ["x" * 513, "second"],
            }
        }
        oversized_file = b" " * (32 * 1024 + 1)
        cases = (
            (duplicate_key, "invalid_json"),
            (nonfinite, "invalid_json"),
            (unexpected, "invalid_request"),
            (non_ascii_name, "invalid_request"),
            (too_many_questions, "invalid_request"),
            ({"state": "", "questions": {"q": valid_predicate}}, "invalid_request"),
            ({"state": "x", "questions": overlong_name}, "invalid_request"),
            ({"state": "x", "questions": overlong_instructions}, "invalid_request"),
            ({"state": "x", "questions": too_few_choices}, "invalid_request"),
            ({"state": "x", "questions": too_many_choices}, "invalid_request"),
            ({"state": "x", "questions": overlong_choice_label}, "invalid_request"),
            ({"state": "x", "questions": overlong_description}, "invalid_request"),
            ({"state": "x", "questions": too_few_levels}, "invalid_request"),
            ({"state": "x", "questions": too_many_levels}, "invalid_request"),
            ({"state": "x", "questions": overlong_level}, "invalid_request"),
            (oversized_file, "request_too_large"),
        )
        for value, category in cases:
            with self.subTest(category=category, value_type=type(value).__name__):
                path = self.write_request(value)
                result = self.run_cli("--provider", "openai", str(path))
                report = self.cli_report(result)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(report["status"], "error")
                self.assertFalse(report["attempted_call"])
                self.assertEqual(report["error"]["category"], category)
                self.assertEqual(report["error"]["http_status"], None)
        invalid_provider_path = self.write_request(normal)
        invalid_provider = self.run_cli(
            "--provider", "PRIVATE-PROVIDER-TEXT", str(invalid_provider_path)
        )
        invalid_provider_report = self.cli_report(invalid_provider)
        self.assertEqual(invalid_provider.returncode, 2)
        self.assertEqual(invalid_provider_report["provider"], "unknown")
        self.assertEqual(
            invalid_provider_report["error"]["category"], "invalid_provider"
        )
        self.assertFalse(invalid_provider_report["attempted_call"])
        self.assertNotIn("PRIVATE-PROVIDER-TEXT", invalid_provider.stdout)
        for timeout_value in ("0", "121", "nan", "inf", "invalid-value-secret"):
            with self.subTest(timeout=timeout_value):
                path = self.write_request(normal)
                result = self.run_cli(
                    "--provider", "openai", "--timeout", timeout_value, str(path)
                )
                report = self.cli_report(result)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(report["attempted_call"])
                self.assertEqual(report["error"]["category"], "invalid_timeout")
                if timeout_value == "invalid-value-secret":
                    self.assertNotIn(timeout_value, result.stdout)
        self.assertEqual(self.fixture.requests, [])

    def test_provider_encoded_request_limit_is_checked_before_http(self):
        questions = {"q": {"type": "predicate", "instructions": "x"}}
        input_overhead = len(
            json.dumps(
                {"state": "", "questions": questions},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        wire_overhead = len(
            json.dumps(
                {
                    "model": "gpt-6-luna",
                    "input": "",
                    "questions": [
                        {"type": "predicate", "name": "q", "instructions": "x"}
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        state = "x" * (32 * 1024 - input_overhead)
        request_value = {"state": state, "questions": questions}
        raw = json.dumps(request_value, separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(raw), 32 * 1024)
        self.assertGreater(wire_overhead + len(state), 32 * 1024)
        path = self.write_request(raw)
        result = self.run_cli("--provider", "openai", str(path))
        report = self.cli_report(result)

        self.assertEqual(result.returncode, 2)
        self.assertFalse(report["attempted_call"])
        self.assertEqual(report["error"]["category"], "request_too_large")
        self.assertEqual(self.fixture.requests, [])

    def test_invalid_or_partial_meters_stay_unavailable_without_arithmetic(self):
        response = {
            "model": "gpt-6-luna",
            "answers": [{"type": "predicate", "name": "damaged", "probability": 0.6}],
            "usage": {
                "input_tokens": True,
                "output_tokens": -1,
                "input_tokens_details": {"cached_tokens": "not-a-count"},
            },
        }
        self.set_response(response)
        request = {
            "state": "synthetic",
            "questions": {
                "damaged": {"type": "predicate", "instructions": "Is it damaged?"}
            },
        }
        path = self.write_request(request)
        result = self.run_cli("--provider", "openai", str(path))
        report = self.cli_report(result)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(
            report["usage"],
            {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "input_tokens_details": {"cached_tokens": None},
            },
        )
        self.assertNotIn("output_tokens_details", report["usage"])

    def test_malformed_answers_never_become_accepted_advice(self):
        request_path = self.write_request(sample_request())
        invalid_responses = (
            {
                "model": "gpt-6-luna",
                "answers": [{"type": "predicate", "name": "unrequested", "probability": 0.5}],
            },
            {
                "model": "gpt-6-luna",
                "answers": [
                    {"type": "predicate", "name": "damaged", "probability": 0.5},
                    {"type": "predicate", "name": "damaged", "probability": 0.5},
                ],
            },
            {
                "model": "gpt-6-luna",
                "answers": [{"type": "predicate", "name": "damaged", "probability": True}],
            },
            {
                "model": "gpt-6-luna",
                "answers": [
                    {
                        "type": "choice",
                        "name": "department",
                        "choice": "not-an-option",
                        "probabilities": [
                            {"value": "billing", "probability": 0.5},
                            {"value": "technical", "probability": 0.5},
                        ],
                        "confidence": 0.8,
                    }
                ],
            },
            {
                "model": "gpt-6-luna",
                "answers": [
                    {
                        "type": "choice",
                        "name": "department",
                        "choice": "billing",
                        "probabilities": [
                            {"value": "billing", "probability": 0.4},
                            {"value": "technical", "probability": 0.4},
                        ],
                        "confidence": 0.8,
                    }
                ],
            },
            {
                "model": "gpt-6-luna",
                "answers": [
                    {
                        "type": "score",
                        "name": "severity",
                        "score": 1.8,
                        "probabilities": [
                            {"value": 0, "label": "minor", "probability": 0.2},
                            {"value": 1, "label": "moderate", "probability": 0.4},
                            {"value": 2, "label": "major", "probability": 0.4},
                        ],
                        "confidence": 0.8,
                    }
                ],
            },
            {"model": "", "answers": []},
        )
        for index, response in enumerate(invalid_responses):
            with self.subTest(index=index):
                secret_body = {**response, "private_server_detail": "PRIVATE-SERVER-BODY"}
                self.set_response(secret_body)
                result = self.run_cli("--provider", "openai", str(request_path))
                report = self.cli_report(result)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(report["status"], "error")
                self.assertTrue(report["attempted_call"])
                self.assertEqual(report["error"], {"category": "invalid_response", "http_status": 200})
                self.assertEqual(report["answers"], {})
                self.assertNotIn("PRIVATE-SERVER-BODY", result.stdout)
        self.assertEqual(len(self.fixture.requests), len(invalid_responses))

    def test_provider_http_error_and_redirect_do_not_retry_or_print_body(self):
        path = self.write_request(sample_request())
        cases = (
            (429, {}, "RATE-LIMIT-BODY-MUST-STAY-PRIVATE"),
            (503, {}, "UPSTREAM-ERROR-BODY"),
            (
                302,
                {"Location": "https://api.openai.com/v1/redirect-catcher"},
                "REDIRECT-BODY-MUST-STAY-PRIVATE",
            ),
        )
        for status, headers, body in cases:
            with self.subTest(status=status):
                self.fixture.respond(body.encode("ascii"), status=status, headers=headers)
                before = len(self.fixture.requests)
                result = self.run_cli("--provider", "openai", str(path))
                report = self.cli_report(result)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(report["attempted_call"])
                self.assertEqual(report["error"]["category"], "http_error")
                self.assertEqual(report["error"]["http_status"], status)
                self.assertNotIn(body, result.stdout)
                self.assertEqual(len(self.fixture.requests), before + 1)
        self.assertEqual(
            [request["host"] for request in self.fixture.requests],
            ["api.openai.com"] * len(cases),
        )

    def test_oversized_provider_response_is_bounded(self):
        self.fixture.respond(b"x" * (512 * 1024 + 1))
        path = self.write_request(sample_request())
        result = self.run_cli("--provider", "openai", str(path))
        report = self.cli_report(result)

        self.assertEqual(result.returncode, 1)
        self.assertTrue(report["attempted_call"])
        self.assertEqual(report["error"]["category"], "response_too_large")
        self.assertEqual(report["error"]["http_status"], 200)
        self.assertNotIn("x" * 128, result.stdout)
        self.assertEqual(len(self.fixture.requests), 1)
        self.assertLess(len(result.stdout), 4096)

    def test_timeout_and_missing_selected_key_do_not_retry_or_fallback(self):
        path = self.write_request(sample_request())
        self.fixture.respond({"model": "unused", "answers": []}, delay=1.3)
        timeout_result = self.run_cli(
            "--provider", "openai", "--timeout", "1", str(path), timeout=5
        )
        timeout_report = self.cli_report(timeout_result)
        self.assertEqual(timeout_result.returncode, 1)
        self.assertEqual(timeout_report["error"]["category"], "timeout")
        self.assertTrue(timeout_report["attempted_call"])
        self.assertEqual(len(self.fixture.requests), 1)

        self.fixture.delay_seconds = 0
        missing_result = self.run_cli(
            "--provider", "openai", str(path),
            env_overrides={"OPENAI_API_KEY": None, "UNSELECTED_PROVIDER_KEY": "UNSELECTED_OTHER_KEY"},
        )
        missing_report = self.cli_report(missing_result)
        self.assertEqual(missing_result.returncode, 1)
        self.assertEqual(missing_report["error"]["category"], "missing_credentials")
        self.assertFalse(missing_report["attempted_call"])
        self.assertEqual(len(self.fixture.requests), 1)
        self.assertNotIn("UNSELECTED_OTHER_KEY", missing_result.stdout)

    def test_cli_help_lists_explicit_provider_and_stdin_usage(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=SCRIPT.parent,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--provider {openai}", result.stdout)
        self.assertIn("--timeout SECONDS", result.stdout)
        self.assertIn("read stdin", result.stdout)
        self.assertEqual(self.fixture.requests, [])

    def test_cli_parse_errors_are_sanitized_without_call(self):
        marker = "PRIVATE-UNKNOWN-OPTION"
        result = self.run_cli("--provider", "openai", f"--{marker}")
        report = self.cli_report(result)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["provider"], "unknown")
        self.assertEqual(report["error"]["category"], "invalid_cli")
        self.assertFalse(report["attempted_call"])
        self.assertNotIn(marker, result.stdout)
        self.assertEqual(self.fixture.requests, [])


if __name__ == "__main__":
    unittest.main()
