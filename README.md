# Orchestrate Execution

An installable Codex skill for deciding when to work directly, how to assign bounded work, and what evidence is needed to accept the result.

**Initial public release · [MIT license](LICENSE).** The package is Codex-first, with examples and reproducible evaluations. See [release checks](docs/release-checks.md) for verification and compatibility limits.

For example, a one-function repair stays with its current owner. Two independent implementations can go to separate workers when each has an exact check and the coordinator has useful integration work. Both paths retain the same authority and acceptance boundaries.

## Install in one project

Copy only `skills/orchestrate-execution` into a new `.agents/skills/orchestrate-execution` directory in your project. Review the skill first. If that destination already exists, stop and compare it manually; these commands refuse to overwrite it. No package manager, script, account or service is required for the core skill. Codex must support local skill discovery; delegation additionally needs exposed worker tools.

From this repository, in PowerShell, replace the project path:

```powershell
$project = 'C:\path\to\your-project'
$destination = Join-Path $project '.agents\skills\orchestrate-execution'
if (-not (Test-Path -LiteralPath $project -PathType Container)) { throw 'Project does not exist' }
if (Test-Path -LiteralPath $destination) { throw 'Destination exists; compare manually' }
New-Item -ItemType Directory -Path $destination -ErrorAction Stop | Out-Null
Copy-Item -Path '.\skills\orchestrate-execution\*' -Destination $destination -Recurse -ErrorAction Stop
```

Or, in a POSIX shell, replace the project path:

```sh
project='/path/to/your-project'
destination="$project/.agents/skills/orchestrate-execution"
test -d "$project" || { echo 'Project does not exist' >&2; exit 1; }
test ! -e "$destination" || { echo 'Destination exists; compare manually' >&2; exit 1; }
mkdir -p "$project/.agents/skills"
mkdir "$destination" || exit 1
cp -R skills/orchestrate-execution/. "$destination/"
```

Start a Codex session in that project and confirm the skill appears in its available skills. If discovery does not refresh, start a new session. Installation alone does not change models, permissions or tool availability. To remove this installation, remove only the copied directory after checking that it contains no later changes you need.

## Use it

```text
Use $orchestrate-execution to implement the requested change.
Choose direct work or bounded delegation from the actual dependencies.
Keep one owner per subsystem and stop after local verification.
```

The [skill](skills/orchestrate-execution/SKILL.md) contains the operating rules. The [Codex binding](skills/orchestrate-execution/references/codex.md) explains how to interpret available runtime controls. [Worked examples](docs/examples.md) show assignments, blocked returns and stopping actions; [design notes](docs/design.md) explain the boundaries and sources of inspiration.

## Benefits and limits

The intended benefits come from keeping small work direct, resolving acceptance before dispatch, giving each resource one writer, reusing applicable proof, and retaining repair budgets across retries. These mechanisms may reduce avoidable coordination and repeated checks. They do not establish faster, cheaper or more accurate task completion on their own. See [benchmark scope and results](docs/benchmarks.md) for the evidence and its limits.

Historical tests informed the workflow. In one September 2026 same-model synthetic replay, an explicit boundary packet used **28.6% fewer total worker tokens** and **37.5% less recorded worker time**, with both versions passing 31 specified checks after the documented grader correction. A separate routing pair had a **94.2% lower historical rate-card estimate**, while taking 11.2% longer. These are small worker-only comparisons on historical models, not guaranteed savings from this release or measured account charges. The [benchmark report](docs/benchmarks.md) includes raw counts, failed checks, grading limits and fresh candidate evaluation.

Current checks are modest: one coding smoke test passed its supplied and independent checks. Two decision trials per arm handled all eleven unambiguous scenarios, with or without the skill; an ambiguous twelfth case was excluded after grading. Supplying the skill used 9.3% more tokens in that probe. The release makes no claim of a current comparative performance gain.

This is instruction-level coordination. It cannot enforce a sandbox, authenticate a worker, prove a reported test ran, select a model through prompt wording, or guarantee restart after the coordinator ends its turn. The coordinator still needs to inspect evidence. Missing tools lead to direct work where authorized or a specific limitation where the selected route is required.

The initial scope is Codex-first, with model-neutral capability roles. Personal model preferences, account setup, external research lanes, detached callback implementations and other runtime adapters are excluded. There is no daemon, scheduler, telemetry store or mandatory proprietary integration. The package does not authorize commits, publication, deployment, external messages or changes outside the user's task.
