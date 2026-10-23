# OpenAI typed routing and coordinator steps

Use this optional path only when the user has authorized OpenAI decision routing and approved the eligible text for export. The helper supports OpenAI only. It can select a typed worker route or suggest a next step from already permissible alternatives. It does not launch a worker, grant access, inspect or execute a plan, send a message, or accept a result.

Read the local batch and its saved evidence first. The execution batch uses `schema_version: 2` and contains a coordinator ID plus one to eight tasks. Each task has an ID, objective, context, absolute existing `allowed_files`, exact `checks`, and the booleans `authorized`, `export_approved` and `inputs_ready`. These fields record coordinator facts; they do not grant permission. Set `inputs_ready` only when required predecessors and sources are available and exclusive resources are free.

For an eligible task, the request sends its task ID, objective and context. File contents, local paths and check commands remain local. Keep exported text free of secrets and unapproved private details. Direct and held tasks stay local and need no provider request. A fresh `run` makes at most one OpenAI request. A refusal, partial answer, failure or uncertain submission stays unresolved; do not retry it by creating a new run ID.

The helper's route table is fixed:

| Route | Model and effort | Use |
| --- | --- | --- |
| `worker_luna` | GPT-6 Luna / max | Settled, bounded execution with authoritative inputs and a concrete check. |
| `worker_sol` | GPT-6.1 Sol / medium | Broader coupled coding that is outside Luna's eligibility. |

These are the helper's supported routes. Other direct or interactive work follows the models and controls available in the current runtime. The selected route is a recommendation for the original coordinator to dispatch. Confirm the worker's current configuration, permissions, project and input access before sending the saved assignment. The worker does not add a routing layer. The coordinator owns review and final acceptance.

The current worker dispatch/readiness helper supports only an actual `danger-full-access` profile with approval `never`, confirmed through the runtime's authorized controls. Restricted or approval-based worker dispatch is unsupported. Keep authorized work direct or hold a specifically required worker route; never upgrade permissions automatically. This is a bounded helper-profile constraint, not permission authority. Revisit it when a real consuming runtime needs restricted dispatch and a source-bound authorized-policy comparison is implemented.

Readiness keeps the raw session and latest-turn cwd values in diagnostics, while comparing them with the caller's cwd by filesystem identity. Existing absolute native paths pass only when they name the same directory. This covers Windows case and 8.3 aliases; different, missing, non-directory, inaccessible or malformed values remain blocked. URI, scheme, device and unsupported remote forms are rejected before lookup. This check does not grant permission or change the other runtime and source guards.

## Run once, reuse offline

From this reference's sibling `scripts/` directory, run the eligible batch once:

```text
python -B routing_decisions.py run BATCH NEW_RUN_DIRECTORY --summary
```

The helper stores the full accepted packet and prints a compact path/hash summary. Keep the complete evidence locally. To compile the same assignment again, use:

```text
python -B routing_decisions.py emit BATCH EXISTING_RUN_DIRECTORY --summary
```

`emit` makes no provider request. It checks the batch, source files, compiler and transport identity and returns the same saved assignment only when those inputs are unchanged. A material task change needs a new disposition. Existing, pending or uncertain runs must be reconciled through their original record; do not replay them under another ID. Delivery, readiness and dispatch records prepare data for the coordinator, but the helper does not launch or send anything.

## Project a receipt, thread read or command result

`compact_evidence.py` reads one named JSON file and prints a bounded offline projection:

```text
python -B compact_evidence.py receipt RECEIPT.json
python -B compact_evidence.py thread THREAD_READ.json
python -B compact_evidence.py exec COMMAND_RESULT.json
```

The result keeps a source path and hash, a status, failure and unknown counts, and a limited summary. Output is capped; omission counts show when text or detail was left out. The helper is not a secret scanner or redactor. A receipt summary, thread projection or command output may still contain private final-answer text, check names or local paths. Inspect what it produced and keep the full evidence at its existing owner. A compact projection is not proof of acceptance.

## Select and settle a coordinator step

Coordinator-step batches use `schema_version: 3` and `kind: "coordinator_step"`; do not mix them with worker batches. They compare two to six already permissible plans at one boundary: `next_action`, `resume_triage` or `analytics_interpretation`. Evidence and its hashes, local plans, source code, checks, authority records and private IDs stay local. Only approved goal, fact and candidate-description text is projected. If export is not authorized, the existing workflow stays direct or held. One candidate is direct; no candidates hold.

The version 3 selector replaces a coordinator's comparison of already known alternatives. Keep deterministic calculations, source and permission checks, pending sends, ready-worker release and settled choices in their existing owners. An unchanged packet can be emitted offline.

At a resume or evidence-triage boundary, inspect the selected step locally:

```text
python -B routing_decisions.py prepare-step BATCH RUN_DIRECTORY --task-id TASK_ID
python -B routing_decisions.py prepare-step BATCH RUN_DIRECTORY --task-id TASK_ID --record APPLY_RECORD.json
python -B routing_decisions.py settle-step BATCH RUN_DIRECTORY --task-id TASK_ID --record SETTLEMENT.json
```

The result is at most 4 KiB and points to the frozen selection and source snapshot. With the owner's application record, `prepare-step` can reserve and save the exact plan. It performs no inspection, execution, native send or provider call. Use that plan through the existing task owner. `apply-step` remains available for callers that use the earlier interface.

If the saved action is pending, used or unknown, the helper returns the existing action pointers without an actionable plan. Reconcile the existing work; do not apply again or replay under another run ID. For `continue_existing`, carry the original delivery and action identity through the existing offline-reuse continuation path, with its worker and review budget unchanged.

Settle only after the downstream result exists. The settlement record links the exact step artifact and immutable evidence. A copied plan, selection, preparation receipt or application artifact does not show that work happened. Known use needs evidence of the actual inspection, report, task result or linked worker dispatch. Record acceptance separately: `true` needs completed, evidenced use and evidence for the boundary's eliminated stage; completion alone does not imply acceptance. Unresolved acceptance remains unknown or pending. Source or policy drift needs a current owner disposition and does not reset the existing review budget.

The `adoption` export reports the supplied registered population, including failures and holds. It distinguishes eligible opportunities (`E`), evidenced downstream use (`C`) and explicit accepted outcomes with the matching eliminated stage (`U`). Creating or re-emitting packets, applying a step, copying exports or changing IDs does not create use or acceptance credit. These are evidence counts, not performance or savings claims.
