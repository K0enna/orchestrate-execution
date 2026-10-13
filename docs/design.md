# Design and provenance

The skill concentrates on the point where a coordinator assigns work and decides whether to accept it. Its core unit is a bounded outcome with one owner, current source, authority and an observable check. It keeps the direct path available because orchestration can add work even when a task needs only one edit.

The original instructional text was written for this public package from a personal coordination policy. Personal paths, account mappings, incident records and fixed model preferences were omitted. Version 0.2.0 adds optional hardcore and native ChatGPT handover workflows, with the original standard-library receipt and conversation-reservation helpers. The consuming project supplies its own destinations and grants. The Codex reference describes conditional runtime binding; the runtime supplies task execution and delivery.

## Decisions that affect behavior

| Decision | Consequence |
| --- | --- |
| Capability roles before model names | The user binds available models and effort to settled execution, coupled integration or a bounded specialist question. The package recommends no fixed model. |
| One original coordinator | Workers implement and check their assignment. Specialist and model-assisted review needs return to the original coordinator, preventing an accidental second delegation layer. |
| Ownership includes mutable sessions | Two files or worktrees do not make concurrent actions in the same account or browser profile independent. |
| Acceptance belongs to a candidate and scope | A passing fixture does not establish deployed runtime behavior; changed source requires an applicability decision. |
| Requested and observed settings stay distinct | A prompt, launch ID or saved preference cannot substitute for current configuration evidence. Required but missing evidence blocks dependent work. |
| Review budget follows the logical task | Renaming a branch or replacing a worker cannot restart repair and review loops. Existing controlling policies can set a different budget. |
| Completion events and supported lifecycle | A timeout does not imply failure. Ending a parent turn requires a verified supported return path, and cleanup follows coordinator acceptance. |

These are model instructions. They do not provide technical isolation, an ownership lock, authenticated receipts, crash recovery or distributed delivery guarantees. A runtime may enforce some properties independently; its guarantees must be established separately.

## Sources of inspiration

The release preparation included a documentary comparison of public projects on 12 October 2026. Their documented mechanisms informed the scope and evaluation questions below. Competitor source was not copied into this package, and these links do not claim endorsement or a measured advantage.

- [Superpowers](https://github.com/obra/superpowers), especially its [subagent development workflow](https://github.com/obra/superpowers/blob/bb92a77741419a4ab5f06e711a283343f1ada0c3/skills/subagent-driven-development/SKILL.md): composable instructions, worked workflows and bounded repair.
- [ECC](https://github.com/affaan-m/ECC): selective installation and explicit limits for runtime support.
- [GSD Core](https://github.com/open-gsd/gsd-core) and [GSD Pi](https://github.com/open-gsd/gsd-pi): fresh execution contexts and source-linked progress, authority and retry state. Such mechanisms are not unique to this policy.
- [BMAD](https://github.com/bmad-code-org/BMAD-METHOD): briefs whose process can be adapted to the task.
- [Symphony](https://github.com/openai/symphony): separation of an operating specification from its runtime implementation.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): an example of runtime checkpoints that instruction-level task records do not replace.

[SkillsBench v4](https://arxiv.org/abs/2602.12670v4) informed the use of frozen tasks and matched conditions for evaluating a skill. [Towards a Science of Scaling Agent Systems v3](https://arxiv.org/abs/2512.08296v3) informed keeping direct execution as a baseline and comparing outcomes across task structures. Neither paper measures this package. [Benchmark documentation](benchmarks.md) owns this repository's actual results and limitations.

The claimed contribution is a focused combination of coordination rules and examples. The package makes no claim of novelty, comparative quality, or current token or quota savings. Historical measurements have their own narrower scope in the benchmark report.

## Where this fits

For supervised Codex work, the useful distinction is the precision of the assignment and acceptance contract: current source, one writer, effective runtime settings, bounded review, and authority for the final action. These mechanisms overlap with the projects above; the survey does not establish uniqueness.

The main weaknesses are enforcement and evidence. Instructions cannot supply authenticated receipts, runtime checkpoints or crash recovery. The optional helpers validate local receipt claims and coordinate cooperating local chat senders; they do not provide transport guarantees or distributed locks. The current evaluation is small and model-visible, and the skill adds prompt overhead. Model binding and delivery capability checks remain tied to the user's runtime.
