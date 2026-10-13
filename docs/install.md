# Install Orchestrate Execution

Start with a local copy of the [repository](https://github.com/K0enna/orchestrate-execution):

```sh
git clone https://github.com/K0enna/orchestrate-execution.git
cd orchestrate-execution
```

## Add it to a project

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

## Give it a real task

```text
Use $orchestrate-execution to add CSV export to this app.
Keep the work focused, choose direct work or bounded delegation,
and verify the result before returning it.
```

Adapt the request to your project. The [examples](examples.md) cover small fixes, parallel assignments and accepting finished work. [Back to the product overview](../README.md).
