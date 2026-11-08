# Releases

## v0.4.0 — Terra worker routing and everyday Decisions calls

8 November 2026

v0.4.0 adds GPT-6.1 Terra as a worker for scoped implementation, diagnosis, analysis, writing and synthesis. The previous release offered two typed worker routes. This release adds four Terra routes and carries the selected model and effort through readiness checks, dispatch and continuation of the same assignment.

### Choose the worker by the work

| Assignment | Route |
| --- | --- |
| Settled non-browser work with authoritative inputs and an exact check | **Luna/max**. Keep it for established bounded writing when comparable work was accepted with little correction. |
| Scoped work that requires judgment within a clear contract | **Terra/medium**. Use **Terra/high** for harder bounded work, such as engineering or synthesis with several constraints. |
| Actual browser automation | **Terra/medium or high**. Hold the assignment if Terra or the required browser access is unavailable. |
| Difficult coupled implementation with settled requirements, or a demonstrated Terra reasoning failure | **Sol/medium** is the typed execution route. The coordinator owns consequential unresolved requirements and architecture. |

Use **Terra/xhigh** for a specific extra reasoning need. **Terra/max** requires explicit user choice or task evidence that lower effort will miss acceptance. Choose effort at the assignment boundary and preserve the user's model selections and independent review policy. The coordinator verifies the worker's actual settings and access before dispatch, then checks the returned result against the assignment.

### Use Decisions for smaller choices

When the user authorizes OpenAI routing and approves the text for export, use one Decisions call before manually choosing a route for an eligible new dispatch. A single ready assignment qualifies when it has an independent outcome worth handing off. Recheck delegation when a missing fact or a settled procedure makes a substantive chunk ready.

The coordinator-step selector introduced in v0.3.0 also fits recurring choices such as which evidence to inspect next or how to continue after an interruption. Give it two to six permissible plans grounded in available evidence. Run a settled check or the sole permissible action directly. Reuse unchanged packets offline and reconcile an uncertain or pending action with its original record. File contents, local paths and check commands stay local. Decisions proposes a route or step. The coordinator remains responsible for execution and acceptance. [Worked examples](docs/examples.md#route-one-ready-browser-assignment) · [Routing guide](skills/orchestrate-execution/references/openai-routing.md)

### Upgrade an existing installation

Finish or reconcile in-flight routing actions with the original helper and retain their records before replacing the skill. Saved packets bind to the compiler and routing policy that created them. Use v0.4.0 for new work after the upgrade. The included helpers require Python 3.11 or later. The release provides a separate SHA-256 checksum for the installable ZIP. [Installation and upgrade guide](docs/install.md)

### Verification

Windows and Ubuntu CI passed on release commit `e62060e`. The local package and temporary installation checks passed, the Sol/high review reported no actionable P0–P2 findings, and the published ZIP was downloaded and checked against its checksum. Validation covered the routing lifecycle and package. This release provides no new production performance or quota measurement. [Release validation run](https://github.com/K0enna/orchestrate-execution/actions/runs/42467503509)

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
