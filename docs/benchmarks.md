# Benchmarks and evidence

This package publishes historical measurements and a current, reproducible decision probe. The numbers answer different questions. The historical records informed the personal workflow; they do not measure the causal effect of this public release. Fresh candidate results are reported separately.

## Historical same-model packet replay

On 9 September 2026, two fresh workers used **gpt-5.6-sol/high** on the same four-mechanism synthetic bundle. The candidate received an explicit input-boundary matrix and focused-test direction in addition to the same facts and examples.

| Worker measure | Ordinary packet | Boundary packet |
|---|---:|---:|
| Accepted specified checks | 31/31 | 31/31 |
| Accumulated input tokens, including cached | 303,371 | 217,681 |
| Cached input subset | 289,536 | 208,256 |
| Output tokens, including reasoning | 10,131 | 6,088 |
| Total input + output | 313,502 | 223,769 |
| Responses | 8 | 6 |
| Recorded worker seconds | 392.451 | 245.452 |

The boundary packet used **28.6% fewer total tokens**, **39.9% fewer output tokens**, and **37.5% less recorded worker time**. There was one bundled trial per arm; four mechanisms are not four independent trials.

The original grader had 32 assertions. The ordinary packet passed 32 and the boundary packet passed 31. One assertion required case-insensitive claims even though the task specified case-insensitive actors. It was excluded symmetrically after grading, leaving 31/31 for both. The raw scores remain in the data. Neither candidate was repaired after grading. This retrospective adjudication and the lack of repetition limit the comparison.

## Historical routing comparison

On 12 September 2026, a narrow synthetic implementation pair used byte-identical fixtures. Model and effort changed together.

| Worker measure | gpt-5.6-sol/medium | gpt-5.6-luna/xhigh |
|---|---:|---:|
| Total tokens | 250,387 | 244,191 |
| Recorded worker seconds | 69.476 | 77.267 |
| Responses / tool calls | 7 / 6 | 7 / 6 |
| Verified repairs | 0 | 0 |
| Historical Standard-credit estimate | 6.910780 | 0.397874 |

Both passed five supplied test methods and 187 supplemental assertions on small functions and decision boundaries. The supplemental grader was written after the first return; grading was not blind. These are assertions, not 187 independent tasks.

The cheaper route had a **94.2% lower historical rate-card estimate**, **2.5% fewer total tokens**, and **11.2% longer recorded time**. It used more output and uncached input, so a 94.2% token-saving claim would be false. The estimate applies the study's dated rates separately to uncached input, cached input and output. It is not a current price, measured bill or observed plan deduction.

[Sanitized historical data](../benchmarks/results/historical.json) retains the counts, rates, raw and adjudicated grades, and limitations. Total tokens equal input plus output; cached input and reasoning are subsets, not additional tokens. Both comparisons exclude coordinator work, separate reviews and tool charges. Original transcripts remain private. Readers can recalculate these aggregates but cannot reproduce the historical runs from this repository.

## Current decision probe

The evaluated version 2 had twelve scenarios and a frozen answer key. They cover direct and delegated work, ownership conflicts, observed settings, stale proof, valid acceptance, exhausted review budgets, existing authority, unavailable routes and untrusted source instructions. The [runnable version 3 cases](../benchmarks/cases.json) retain eleven of them; one ambiguous case was removed after the evaluation, as disclosed below. The [response schema](../benchmarks/response.schema.json) is unchanged.

Each run submits one bundled response, with or without the exact skill entrypoint. The model sees the cases and available actions, never the expected grading fields. One bundle is one trial, not twelve independent trials. The runner preserves every attempted result and refuses to overwrite an output directory. Structured actions and acceptance fields are graded deterministically; reasons need human inspection. This is a decision probe, not an executed multi-agent workflow or production success rate.

Python 3.11+ and an authenticated Codex CLI are required only for evaluation. First inspect a dry run:

~~~sh
python -B benchmarks/run.py --model YOUR_MODEL --effort YOUR_EFFORT --output .eval-runs/baseline-dry
~~~

To execute, provide the absolute path to the intended CLI and add --execute. This consumes model usage. Use identical model, effort and cases for each arm, fresh output directories, and alternate order on repetitions:

~~~sh
python -B benchmarks/run.py --codex /absolute/path/to/codex --model YOUR_MODEL --effort YOUR_EFFORT --output .eval-runs/baseline-1 --execute
python -B benchmarks/run.py --codex /absolute/path/to/codex --model YOUR_MODEL --effort YOUR_EFFORT --skill skills/orchestrate-execution/SKILL.md --output .eval-runs/candidate-1 --execute
~~~

Windows accepts an absolute codex.exe path with the same arguments. Raw output directories can contain local paths, thread identifiers and native authentication configuration identifiers; keep them private. Publish a selected aggregate, not the raw folder. The runner reads only allowlisted authentication settings from the user's normal configuration; it never reads authentication tokens.

The runner requests disabled user/project instructions and automatic skill instructions, read-only execution, and no tools. It rejects any tool activity reported in the event stream. The installed CLI still scanned global skill metadata; whether that metadata entered the model context was not established. The baseline therefore means **no supplied skill body under the same CLI setup**, not a proven clean Codex environment. These controls do not make the read-only sandbox a host-wide privacy boundary; use only synthetic public cases. Requested model and effort remain distinct from observed metadata. The CLI meter reports input, cached-input and output; it does not report account charges.

On 13 October 2026, both arms used requested and observed **gpt-6.1-sol/medium**, CLI `0.162.0-alpha.17.2`, with two bundled trials per arm in baseline/candidate/candidate/baseline order. Matching local session metadata confirmed model, effort, read-only sandbox and approval policy. All four processes exited 0 with no tool events. The public skill body was identical in both candidate runs.

| Version 2 measure | No supplied skill body | Public skill body |
|---|---:|---:|
| Original exact-match score, each run | 11/12 | 11/12 |
| Unambiguous subset, each run, selected retrospectively | 11/11 | 11/11 |
| Mean total tokens | 18,226 | 19,927 |
| Mean elapsed seconds | 20.500 | 28.672 |

The candidate used **9.3% more tokens** and took **39.9% longer** in this small probe. Both arms already handled the unambiguous scenarios correctly. These results do not demonstrate a quality gain or token saving from the public skill, and they do not measure actual multi-agent completion. The tasks and answer key were authored with knowledge of the skill; they are not a blind or held-out evaluation.

The excluded case said the authorized local publication candidate was complete, but its answer key required `accept_return: false`. That contradicted the prompt's definition of closing the authorized assignment. Either `prepare_only` or `accept_return` was also a reasonable action label. Every response explicitly preserved the user's separate publication decision. We excluded the entire case symmetrically from the interpreted score and kept all original failures. Version 3 removes only that case; its eleven remaining scenarios are unchanged. No fresh version 3 run is claimed.

An earlier version 1 pair scored 12/12 without the skill and 11/12 with it. The candidate selected the correct authorized push action but interpreted acceptance as accepting the returned source, rather than closing the still-unfinished push assignment. Version 2 clarified that definition before the matched runs. Neither correction changed the skill to fit the grader. [Sanitized decisions and measurements](../benchmarks/results/decisions.json), [version 1 cases](../benchmarks/results/decision-cases-v1.json) and [version 2 cases](../benchmarks/results/decision-cases-v2.json) preserve those attempts and their limitations.

## Actual coding smoke test

The [deliberately broken operations fixture](../benchmarks/fixtures/operations/TASK.md) asks for two small Python repairs. Copy that fixture to a disposable workspace, give a fresh agent the task and installed skill, and allow writes only to operations.py. The visible test command is in the task. After the return, independently run:

~~~sh
python -B benchmarks/check_operations.py /path/to/disposable/operations.py
~~~

The [independent checks](../benchmarks/check_operations.py) cover the stated boundaries, mutation and identity behavior. They failed on the original fixture before the forward run, with eight assertion failures and one error across six test methods. A single **gpt-6-luna/max** worker then repaired only `operations.py`, passed the two supplied test methods, and passed all six independent methods with exit 0. The task and supplied test file hashes remained unchanged. Requested and observed worker settings matched.

[Smoke-test data](../benchmarks/results/forward-smoke.json) records source hashes, scope and terminal results. A passing candidate demonstrates this bounded exercise only; it is not a comparative speed or cost experiment. The worker also received coordinator instructions, so the result cannot be attributed to the skill alone. No production multi-agent workflow, independent clean-machine installation or other runtime adapter was tested.

