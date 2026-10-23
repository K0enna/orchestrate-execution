# Codex runtime binding

Read this when delegating in Codex or after a material runtime change. These are interface semantics to check against the live schema, not a claim that every Codex surface exposes the same tools. The core also works with direct execution alone.

## Native children

Where `collaboration.spawn_agent` is exposed, use its actual model and effort fields to select the route explicitly. On interfaces that provide `model`, `reasoning_effort` and `fork_turns`, a fresh-context launch uses `fork_turns: "none"` with a complete bounded packet. Full-history inheritance can prevent overrides; inspect the schema before mixing them. Check custom role settings for pins that override the requested route.

The optional [OpenAI decision helper](openai-routing.md) has its own fixed typed route table. It selects a recommendation; the coordinator still uses the runtime's actual launch controls and readiness evidence.

Use launch or current-session evidence for effective configuration, parent identity and workspace. A tool may return only a task name; that is an identifier, not configuration proof. Use an exposed read-only evidence source if available. Otherwise record the missing fields, and do not proceed when the task requires their verification. Avoid private transcript dumps, internal database edits and unsupported control interfaces.

Native final-result delivery and mailbox/event waits support an active coordinator where documented by the runtime. Respect current timeout limits. They do not by themselves establish that ending the parent turn will restart it later. Keep the coordinator active for ordinary native coordination unless the supported lifecycle establishes otherwise.

## Optional app workers

For `Mode=hardcore` / `Mode=detached`, use the complete [detached workflow](detached-mode.md): save the parent continuation, establish a separate worker and supported terminal callback, end the parent turn, and claim the receipt on return. The bundled helper handles local receipt validation and duplicate handling; the runtime supplies task execution and delivery.

Use an app task only when creating that task is authorized and provides a placement or lifecycle benefit. Resolve the intended project and workspace through supported discovery. Set actual exposed configuration fields; instructions inside the prompt do not configure a task. Verify required visibility, project placement, access and return delivery once before substantive unattended work. If the interface lacks a required control or proof field, report the limitation rather than substituting an unrelated project or hidden worker.

Task archival, interruption and workspace cleanup are separate operations. Use only exposed authorized controls after preserving acceptance evidence. A final answer alone does not establish that background commands have stopped.

## Access and messaging

Record the required permission context from the user's selected policy; this package supplies no universal sandbox or approval setting. Inspect observed access separately from model choice. A successful read proves that read, not general write privileges or launch inheritance. Never relax access controls to satisfy an assignment.

Cross-task messages and external handovers need user authorization for the recipient and data scope. Native child completion is distinct from sending a new message to another task. For `Mode=chatgpt`, use [native ChatGPT handover](chatgpt-handover.md) with a registered ordinary ChatGPT destination and exposed send/read tools. The consuming project owns its destination mappings and grants. The package's local helpers do not configure accounts or transport.
