# Release checks

## Native cwd identity compatibility repair

Checked locally on 23 October 2026 with Python 3.12.10 on Windows. Readiness now compares the caller's cwd with the raw session and latest-turn cwd values by existing directory identity. Tests exercised a real Windows 8.3 alias returned by `GetShortPathNameW`, case aliases, both metadata fields, native and app readiness, and the dispatch and prepare-dispatch CLI paths. They also cover different and missing directories, non-directories, denied lookup, malformed and unsupported URI/remote/device inputs before lookup, literal percent and hash filenames, traversal to another directory, and unchanged source and runtime guards.

- `python -B -m unittest discover -s skills/orchestrate-execution/scripts -p test_routing_decisions.py -v` ran 74 tests; all passed.
- `python -B -m unittest discover -s skills/orchestrate-execution/scripts -p test_compact_evidence.py -v` ran 7 tests; all passed. The compact projector is unchanged; its test now expects the canonical resolved source path it returns.
- The unaffected adviser suite ran 12 tests; all passed. The receipt suite ran 29 tests: 28 passed and the existing symlink test was skipped because this Windows host denied symlink creation (error 1314). The workbench suite ran 6 tests and the benchmark suite ran 16; all passed.
- `python -B tools/check_package.py` passed, including package files, local links, metadata, imports, provenance hashes, private-path checks and a temporary installation that refused to overwrite an existing destination.
- `git -c core.whitespace=cr-at-eol diff --check` passed.

The canonical installed skill was not changed. Tests made no live provider calls. No hosted CI result or release is claimed; the original coordinator owns review and release acceptance.

## v0.3.0 typed-routing source verification

Checked locally on 23 October 2026 with Python 3.12.10 from the working tree based on `6ef6ca3fccbbf322181f4ae7772fb8b64c870843`. The original coordinator retains the final exact-candidate review and release acceptance.

- The new CLI regression failed on the pre-repair bytes only for `accepted: true` with an empty eliminated-stage list. Its first probe also exposed a fixture error because the generated step has no `boundary` field; the fixture was corrected, and the corrected pre-repair run reproduced the intended failure. The repaired regression passed with matching-stage success and false/unknown empty-stage controls.
- `python -B -m unittest discover -s skills/orchestrate-execution/scripts -p test_routing_decisions.py -v` ran 69 tests; all passed, with no failures, errors or skips.
- `python -B tools/check_package.py` passed for the repaired package, including package files, Markdown links, metadata, standard-library imports, provenance hashes, private-path checks and a temporary installation that refused to overwrite an existing destination.
- `git diff --check` passed.
- The routing helper and its regression are same-author distribution derivatives for the narrow acceptance-evidence repair. The other eight packaged helper hashes remain unchanged. Canonical installed files were not modified.
- Tests made no live provider calls. This local verification does not report a hosted CI result or claim publication.

### Earlier v0.3.0 candidate verification (23 October 2026; before the acceptance-evidence repair)

This records the prior candidate-base checks. Their counts and hashes describe the pre-repair bytes, not the repaired source.

- `python -B tools/check_package.py` passed. It checked required package files, Markdown links, skill metadata, standard-library imports, source hashes, machine-specific paths and a byte-identical temporary installation that refused to overwrite an existing destination.
- The skill-creator `quick_validate.py` metadata check passed.
- `python -B -m unittest discover -s skills/orchestrate-execution/scripts -p 'test_*.py' -v` ran 122 tests: 121 passed and one symlink test was skipped because this Windows host denied symlink creation (error 1314). No tests failed.
- `python -B -m unittest discover -s benchmarks -p 'test_*.py' -v` ran 16 tests; all passed.
- All five production helpers accepted `--help`. The adviser test redirects the OpenAI hostname to a local test server and rejects non-local DNS; tests ran with provider credential variables removed and made no provider calls.
- All ten packaged helper and test files matched the source-inventory SHA-256 values and the provenance table at that time. The package contained no task-specific paths or run IDs.
- Bare `git diff --check` passed after normalizing `README.md` and `docs/install.md` to UTF-8 LF. The install guide decoded to the same text; the README also included the separately requested file-first handoff guidance update.

Local helper and benchmark checks ran only on Windows. The existing CI matrix is configured for Windows and Ubuntu; no hosted CI result was produced in that earlier run. Historical benchmark figures remain unchanged, and the packaging update made no performance or savings claim.

## v0.2.0 optional modes

The installable folder now contains both mode guides and their standard-library helpers. The public text is adapted from the personal workflow; project/chat identities, machine paths, fixed model preferences and permission overrides are omitted. The four helper/test files preserve the original source bytes.

Checked locally on 13 October 2026:

- Skill-creator validation and `python -B tools/check_package.py` passed, including new mode files, local links, private-path checks and a byte-identical temporary installation.
- `python -B -m unittest discover -s skills/orchestrate-execution/scripts -p 'test_*.py' -v` ran 32 tests: 31 passed and one symlink escape test was skipped because this Windows host denied symlink creation. Receipt validation, concurrent claims, duplicate/stale/canceled returns, reservation contention, exact-owner release and malformed/corrupt input cases passed.
- Both helper `--help` commands exited 0. All 16 existing benchmark-runner tests passed. CI includes both suites on Windows and Ubuntu.

These are local helper and packaging checks, not a fresh live handover or a new savings benchmark. The two operating guides require the consuming runtime's exposed launch/send/read controls and current delivery readiness. [Mode benefits and use cases](modes.md) explain how to choose the workflow; [benchmark evidence](benchmarks.md) keeps its existing scope.

One primary source review used GPT-6.1 Sol/high, P2 and no access fallback. It found one mismatch: the initial prose claimed Python 3.10 support, while the reservation helper uses SQLite result-code constants introduced in Python 3.11. The documented minimum was corrected consistently to Python 3.11, including the installable mode guides; helper source and behavior are unchanged. No additional actionable findings were reported. This was one prose remediation batch, so no further model review was needed.

## Initial public package

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
