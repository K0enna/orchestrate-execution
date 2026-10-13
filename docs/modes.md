# Give each kind of work a place to succeed

A quick repair, a full implementation and a research report ask different things of an agent. Orchestrate Execution lets you choose how the work moves while keeping one coordinator responsible for the result.

| Your next job | Choose | What you gain |
| --- | --- | --- |
| A small fix or tightly connected change | `Mode=direct` | A short path from request to checked result. |
| Independent pieces, with useful coordination work alongside them | `Mode=native` | Focused workers move together while the coordinator integrates. |
| A substantial, agreed assignment that can run on its own | `Mode=hardcore` | The parent steps out and returns to handle the completed work. |
| Source-heavy research or substantial writing | `Mode=chatgpt` | A dedicated ChatGPT conversation develops an artifact you can bring back and reuse. |
| Let the skill choose from authorized routes | `Mode=auto` | Coordination sized to the actual task. |

Use these selections in your prompt. They are instructions to the skill, and you can describe the same choice in ordinary words.

## Hardcore mode: a clear job, a focused worker, a useful return

You have agreed what needs to be built. The inputs are ready, the files have an owner, and the check is clear. There is little value in keeping the coordinator occupied with “is it done yet?”

Hardcore mode gives that job its own worker chat. The coordinator prepares the assignment, confirms the worker is ready, saves what it will do next, and ends its turn. The worker completes the implementation and checks, saves the evidence, and sends one terminal result to the original chat. The coordinator resumes to inspect the result and finish acceptance.

The efficiency comes from that change in rhythm: **coordination happens when it can move the job forward**. The worker stays responsible through routine repairs. The coordinator returns for a completed result or a concrete blocker, with the context needed to act. Saved receipt checks keep a repeated completion message from triggering the same integration again.

Good fits include:

- **A feature with an agreed specification.** Implement a CSV export after settling its columns, encoding and acceptance tests.
- **A batch conversion.** Convert a defined set of files, save an output manifest and verify a representative sample.
- **A known repair.** Fix a reproduced bug within a bounded subsystem and return the focused test result.
- **Independent implementation lanes.** Give each lane its own outcome and writer, then accept their returns under one coordinator.

```text
Use $orchestrate-execution. Mode=hardcore.
Implement the agreed CSV export in the owned data module.
Preserve the existing import behavior and run the agreed checks.
Use a separate worker, end this turn once it is ready,
and resume here to verify the returned files and check evidence.
```

**Get ready once.** Use a Codex setup that can create a separate worker chat and deliver its terminal message to the original chat. Keep the same project, select the worker's available model and reasoning effort, and confirm access to its actual inputs. The packaged helpers use Python 3.11 or later. The skill handles the assignment and acceptance workflow; your runtime supplies the return delivery.

Read the [hardcore operating guide](../skills/orchestrate-execution/references/detached-mode.md) when dispatching. It includes the assignment, receipt and resumption steps.

## Native ChatGPT handover: more room for research and writing

Research often needs a different workspace from implementation. A competitor study grows through sources and comparisons. A product brief needs considered prose. A literature review may become a reference you return to across several coding tasks.

Native ChatGPT handover gives that work an existing conversation of its own. Codex sends a focused brief through the connected native chat tools, including the public sources or approved excerpts the assignment needs. ChatGPT develops the requested artifact there. Codex can work on independent local tasks, then retrieves the result, checks its sources and completeness, and uses it for the project's next step.

**Keep the coding task focused. Keep the research useful.** The brief carries the information needed for the deliverable, and the returned artifact gives the coordinator a concrete basis for decisions. Its source trail stays in the research conversation and the accepted result stays with the project. A shared local reservation helps cooperating tasks keep each conversation on one assignment at a time.

Good fits include:

- **Competitor and tool comparisons.** Return a dated, source-linked assessment of the options that matter to a specific decision.
- **Technical research.** Turn papers or official documentation into findings the implementation owner can check and apply.
- **Product specifications.** Develop an explicit brief before assigning settled implementation work.
- **Reports and launch writing.** Produce a complete draft with the destination's installed humanizer or anti-slop skill when available.

```text
Use $orchestrate-execution. Mode=chatgpt.
Send this public brief to our registered Research conversation.
Compare the three tools against our stated requirements.
Return sources, decisive trade-offs and a recommendation we can review.
Keep the full comparison with this project for the implementation handover.
```

**Get ready once.** Choose an existing ordinary ChatGPT conversation and register its verified project, title and ID in your project's instructions. Common lane names are Research, Specs & Writing, and Workbench. Record what the handover may send and preserve the model configured in that conversation. The packaged helpers use Python 3.11 or later. The [operating guide](../skills/orchestrate-execution/references/chatgpt-handover.md) explains discovery, briefing and retrieval.

### Bring back a long report without losing its ending

Native retrieval reads up to **20,000 characters from each returned item**. That is a delivery size, not a maximum report length. The skill requests replies below **16,000 characters**, leaving space for headings, sources and part markers.

A long report comes back as numbered chapters. The coordinator retrieves each part, keeps them on the same revision, and checks the full set before accepting the report. You get the complete artifact, with its ending and sources intact. Ordinary ChatGPT handovers are retrieved at useful checkpoints or on the task's next continuation; the automatic parent-return workflow belongs to hardcore mode.

## Use them together when the work calls for it

Research a choice in ChatGPT, accept the source-linked recommendation, then give the settled implementation to a hardcore worker. The original coordinator owns both handovers and verifies the final result. Each stage gets a clear job, and the work moves forward from accepted evidence.

[Get started](install.md) · [Worked examples](examples.md) · [Measured results](benchmarks.md) · [Product overview](../README.md)
