# Releases

## v0.3.0 — Typed routing and accountable next steps

23 October 2026

- Add an optional OpenAI routing path with two typed worker routes. The coordinator still confirms runtime readiness and dispatches the saved assignment.
- Add offline reuse for unchanged routing packets and a version 3 selector for next action, resume triage and analytics interpretation.
- Add `prepare-step`, `apply-step` compatibility and `settle-step` guidance. A suggestion is not execution or acceptance; pending work is not replayed, and downstream evidence is required to record use.
- Match existing native session and turn cwd aliases by filesystem identity, including Windows case and 8.3 spellings; keep URI, device, unsupported remote and runtime authority checks intact.
- Require exactly one matching, evidenced eliminated stage for accepted coordinator steps, while preserving false and unknown acceptance with no eliminated stage.
- Document the current worker dispatch/readiness profile: actual `danger-full-access` with approval `never`, confirmed through runtime-authorized controls. Restricted or approval-based worker dispatch is unsupported.
- Package the standard-library routing, adviser and evidence-projection helpers with their source tests. Add portable provenance hashes and package dependency checks.

Historical benchmark figures remain unchanged. No new savings or production-performance measurement is claimed. [Local release checks](docs/release-checks.md) record the verification and reused unaffected checks.

## v0.2.0 — Choose how the work moves

13 October 2026

Two optional modes join direct execution and active native workers:

- **Hardcore mode** gives a settled job its own worker chat. The parent ends its turn and resumes from a terminal return to verify the result. Includes the local receipt helper for artifact checks and duplicate handling.
- **Native ChatGPT handover** sends substantial research and writing to a registered existing conversation, then retrieves and checks the full artifact. Includes shared local conversation reservations and numbered delivery for long reports.

The [mode guide](docs/modes.md) covers benefits, use cases, setup and ready-to-adapt prompts. Both workflows ship inside the installable skill folder and load their instructions only when selected. Helpers use Python's standard library; CI exercises their 32 tests alongside the existing 16 benchmark-runner tests on Windows and Ubuntu.

Historical benchmark figures remain unchanged. This release adds execution choices and tested local helpers; it does not introduce a new comparative savings measurement. [Release verification](docs/release-checks.md).

## Initial public package

13 October 2026

Published the MIT-licensed core skill, worked examples, evaluations, visual product page and installation instructions. The initial main-branch package preceded the v0.2.0 versioned release.
