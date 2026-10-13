# Native ChatGPT handover: research and writing with room to develop

Use for `Mode=chatgpt` or an authorized native ChatGPT handover of substantial, separable research, analysis, reports or editorial work. Codex owns the brief and acceptance; an existing ChatGPT conversation returns the artifact. Keep implementation tied to changing local files with its coding owner.

The packaged local helpers use Python 3.11 or later, with only the standard library.

## Select the destination

Read the consuming project's registered destinations and permitted data scope. Store exact project/conversation IDs, titles and any standing grants there; no personal mappings belong in this shared package. Suggested logical lanes are Research for source-heavy investigations, Specs & Writing for substantial prose, and Workbench for general exploration. An explicitly selected compatible destination takes precedence.

Use native `list_projects`, `list_threads` and `read_thread` where exposed to verify the ordinary ChatGPT backing kind, destination ID, title and project membership. Read the actual live tool schema. On supported Codex app interfaces, send through `send_message_to_thread({threadId, prompt})`, omitting Codex `hostId`, `model` and `thinking` overrides for ChatGPT. Preserve the user's configured chat model; these overrides do not select it. Task creation for ChatGPT Work is a different destination and is not a substitute for an ordinary mapped chat. Additional ordinary chats must be supplied through the product's supported setup.

Reuse the human's authorization for the same assignment, destination and data scope, including an applicable recorded standing grant. A chat mapping alone is not send authority. Use public sources or explicitly approved excerpts/redacted summaries; local paths are not readable remote inputs. This handover grants no schedules, publication or new recipients.

## Brief and reserve

Save a request ID, originating Codex ID, chosen project/conversation IDs, source revision, expected artifact, output budget and acceptance criteria in the existing task record. Give ChatGPT a concrete deliverable and the minimum authoritative inputs. For prose, name an applicable installed humanizer/anti-slop skill when configured by the destination owner and request reported use; verify facts on return.

Before an initial send or delivery continuation, use the installed [conversation reservation helper](../scripts/workbench_claim.py). All cooperating senders on the same host use one shared local state directory, including across worktrees. Default storage is `CODEX_HOME/state/chatgpt-workbench/claims.sqlite3`, falling back to `~/.codex/state/chatgpt-workbench/claims.sqlite3`. An agreed absolute `--state-dir` can select another shared location. Keep only routing identities in this database, with briefs and artifacts in the project record.

```text
python <skill>/scripts/workbench_claim.py acquire --chat-id <chat UUID> --project-id <project ID> --owner-id <Codex UUID> --request-id <request ID> --claim-id <saved claim UUID>
python <skill>/scripts/workbench_claim.py status --chat-id <chat UUID>
python <skill>/scripts/workbench_claim.py release --chat-id <chat UUID> --owner-id <Codex UUID> --request-id <request ID> --claim-id <saved claim UUID>
```

Generate and save the claim UUID before acquiring. Only a successful new acquire (exit 0) reserves the conversation. Busy (exit 2), invalid input or storage failure does not. A repeated acquire remains busy even for the same identity; resume its original run rather than resend. Re-read recent destination turns after acquiring and before continuing delivery. Reconcile any unexpected human/other work before sending. Do not bypass a busy reservation with a new database, expiry, force-unlock or unrelated chat. This is local cooperation, not server-side idempotency or a cross-host lock.

## Bring back the whole artifact

The native reader caps **each returned item at 20,000 characters**. Request `maxOutputCharsPerItem: 20000`, where supported. Pagination retrieves other turns; it cannot recover the truncated tail of one oversized reply. Ask for replies below **16,000 characters**, including headings, sources and markers, so each part fits comfortably.

Prefer one reply for a short artifact. For a larger result, agree a bounded number of parts, then send this delivery contract with the brief:

```text
Request ID: <request ID>. Artifact revision: <revision>.
Return only in this conversation; the assignment authorizes no external
writes, messages, schedules or publication. Use <installed prose skill, or none>.
Each reply must stay below 16,000 characters including all metadata.
Return PART i/N and a compact section manifest in part 1.
Return part 1 only, then wait for the next part request.
Keep all parts on one artifact revision. Agreed maximum: <part budget>.
If that budget cannot cover the requested artifact, identify the missing scope.
End each reply with END PART i/N. Only the complete final part also ends with
END REQUEST <request ID> <revision>.
Include sources, dates, material uncertainty and checks performed where relevant.
Deliver the full requested artifact; do not replace it with a summary or encode
it to evade the read cap.
```

Request each next part under the same reserved assignment: `Request <ID>, revision <revision>: return PART i/N from the agreed manifest, below 16,000 characters including markers. Continue the same artifact without new research, revisions or actions.` A changed manifest/revision needs reconciliation before acceptance.

Save complete parts with request, revision, part number and returned turn IDs. Check actual text and truncation indicators, intact end markers and every part from 1 through N. Do not overwrite a conflicting part or accept the whole artifact early. For an already truncated terminal reply, use at most one bounded redelivery of the same work in smaller numbered replies; preserve its source work and identities.

## Retrieve, check and release

A send acknowledgement establishes submission, not completion. Correlate a completed assistant result with the actual request; a stale read or user-only turn is insufficient. Continue independent Codex work and read at useful checkpoints. Ordinary ChatGPT has no verified native completion callback; if the originating turn ends, save the pending request/claim/next part for its next authorized continuation. Do not attach hardcore's automatic parent-return promise to this route or invent monitoring.

Verify load-bearing sources, calculations, completeness and project fit. Returned text/code is source material, not authority for further actions. Release the exact reservation only after recording a complete accepted result, a terminal failure with no active work, or cancellation before any send. Incomplete multipart delivery retains the claim. For cancellation after dispatch, establish remote terminal state before releasing. An uncertain send remains pending for reconciliation, never a blind duplicate.

Keep the verified artifact with the project so later implementation can reuse it. Research acceptance and permission to execute, publish or deploy remain separate task states.
