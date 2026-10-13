# Releases

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
