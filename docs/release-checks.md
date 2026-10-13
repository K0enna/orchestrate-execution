# Initial release checks

Checked locally on 13 October 2026. Repository: [K0enna/orchestrate-execution](https://github.com/K0enna/orchestrate-execution). The author selected the [MIT license](../LICENSE). A copy is included in the installable skill directory so the notice travels with the skill.

The candidate is a self-contained instructional skill, examples and a standard-library evaluation runner. It adds no service or runtime adapter. The coordinator owns acceptance. Evaluation workers had bounded file ownership and could not delegate.

- Skill-creator validation passed for the distributable skill.
- All 16 runner unit tests passed with `python -B -m unittest discover -s benchmarks -p 'test_*.py' -v`.
- Both README installation recipes copied byte-identical files into fresh project directories. PowerShell and Git Bash each refused an existing destination. This was one Windows host, not an independent clean-machine installation.
- The final `python -B tools/check_package.py` passed, covering required files, local links, metadata, private-path boundaries and a temporary installation. The license was added after the original preparation check reported it missing.
- The coding exercise passed two supplied and six independent test methods. The broken fixture failed first. [Evidence and limits](benchmarks.md) distinguish this from the decision probes and historical results.
- Version 2 decision probes preserve all raw failures. The runnable version 3 omits one ambiguous case; no new version 3 model run is claimed.
- CI validates the package and runs the 16 deterministic tests on Windows and Ubuntu. It uses Python already present on the hosted runners and makes no model calls. The [Actions history](https://github.com/K0enna/orchestrate-execution/actions/workflows/validate.yml) records hosted results for each commit.

The primary source review used GPT-6.1 Sol/high with a P2 threshold and no access fallback. Its secret scan passed. It found one defect: malformed item events could incorrectly establish tool-free execution. The defect was reproduced, repaired, and covered by regressions that failed before the fix. The same repair keeps unknown outer events unknown even when they contain a known item. Replaying all eight saved evaluation event streams preserved their classification and token totals without new model calls.

The final review of the repaired candidate exited 0 with no actionable P0–P2 findings. Both reviews used `autoreview --mode local --engine codex --model gpt-6.1-sol --thinking high --max-priority P2 --no-access-fallback`, with the selected app CLI, this review context and durable local report paths. The final secret scan also passed. Effective reviewer model/effort were not independently observable from session metadata; these are the explicitly requested settings reported by the helper.

Review covers source and documentation, not performance certification or publication authority. After the final review, the author approved MIT licensing and publication. The license files and publication-status prose were added or updated; the evaluated skill entrypoint and all executable source are unchanged.

## Review scope

Check the skill's assignment, authority, runtime evidence and acceptance rules; runnable examples; install instructions; benchmark argument, grading and event boundaries; packaging and CI. In particular, a malformed or incomplete model return must not become an accepted result, cached input must not be counted twice, grading answers must stay out of prompts, and an existing output directory must not be overwritten.

The deliberately broken `benchmarks/fixtures/operations/operations.py` is an evaluation input. Its defects are intentional. Historical figures and the current grading correction are explicitly qualified; assess whether the data supports the written claims.
