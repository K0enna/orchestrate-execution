"""Validate the distributable skill, dependencies, provenance and local links."""
import ast
import hashlib
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "orchestrate-execution"
SCRIPT_NAMES = (
    "routing_decisions.py", "decision_adviser.py", "compact_evidence.py",
    "test_routing_decisions.py", "test_decision_adviser.py", "test_compact_evidence.py",
    "detached_receipt.py", "test_detached_receipt.py",
    "workbench_claim.py", "test_workbench_claim.py",
)


def check_links(root):
    errors = []
    for source in root.rglob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", source.read_text(encoding="utf-8")):
            if re.match(r"^(https?://|mailto:|#)", target):
                continue
            path = unquote(target.split("#", 1)[0].strip("<>"))
            if path and not (source.parent / path).is_file():
                errors.append(f"{source.relative_to(root)}: missing {path}")
    return errors


def check_imports(root):
    errors = []
    local_modules = {source.stem for source in root.rglob("*.py")}
    standard_modules = sys.stdlib_module_names
    for source in root.rglob("*.py"):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, UnicodeError, SyntaxError) as error:
            errors.append(f"Cannot parse {source.relative_to(ROOT)}: {error}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module.split(".", 1)[0]]
            else:
                continue
            for module in modules:
                if module not in standard_modules and module not in local_modules:
                    errors.append(
                        f"Undeclared non-standard dependency {module!r} in {source.relative_to(ROOT)}"
                    )
    return errors


def check_provenance(root):
    errors = []
    provenance = ROOT / "docs" / "source-provenance.md"
    if not provenance.is_file():
        return ["Missing source provenance"]
    rows = re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$",
                      provenance.read_text(encoding="utf-8"), re.M)
    recorded = {}
    for relative, expected in rows:
        if relative in recorded:
            errors.append(f"Duplicate provenance path: {relative}")
            continue
        recorded[relative] = expected
        path = ROOT / relative
        try:
            path.resolve().relative_to(ROOT.resolve())
        except (OSError, ValueError):
            errors.append(f"Provenance path escapes package: {relative}")
            continue
        if not path.is_file():
            errors.append(f"Missing provenance file: {relative}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(f"Provenance hash mismatch: {relative}")
    expected_paths = {
        (root / "scripts" / name).relative_to(ROOT).as_posix()
        for name in SCRIPT_NAMES
    }
    if set(recorded) != expected_paths:
        errors.append("Provenance rows do not match the packaged helper source/test files")
    return errors


def main():
    errors = []
    required = [
        ROOT / "README.md", ROOT / "LICENSE", ROOT / "docs" / "benchmarks.md",
        ROOT / "CONTRIBUTING.md", ROOT / "docs" / "source-provenance.md",
        SKILL / "SKILL.md", SKILL / "agents" / "openai.yaml",
        SKILL / "references" / "codex.md",
        SKILL / "references" / "openai-routing.md",
        SKILL / "references" / "openai-routing-example.md",
        ROOT / "docs" / "modes.md", ROOT / "CHANGELOG.md",
        SKILL / "references" / "detached-mode.md",
        SKILL / "references" / "chatgpt-handover.md",
        *(SKILL / "scripts" / name for name in SCRIPT_NAMES),
    ]
    errors.extend(f"Missing required file: {p.relative_to(ROOT)}" for p in required if not p.is_file())
    core = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\n(.*?)\n---\n", core, re.S)
    if not frontmatter or not re.search(r"^name: orchestrate-execution$", frontmatter[1], re.M):
        errors.append("Skill name/frontmatter invalid")
    if not frontmatter or not re.search(r"^description: .+", frontmatter[1], re.M):
        errors.append("Skill description missing")
    metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    if "$orchestrate-execution" not in metadata:
        errors.append("UI prompt does not invoke this skill")
    if sys.version_info < (3, 11):
        errors.append("Packaged helpers require Python 3.11 or later")
    errors.extend(check_imports(SKILL))
    errors.extend(check_provenance(SKILL))
    errors.extend(check_links(ROOT))
    for p in SKILL.rglob("*"):
        if p.is_file() and p.suffix in {".md", ".yaml", ".py"}:
            text = p.read_text(encoding="utf-8")
            if re.search(r"[A-Za-z]:[/\\](Users|Codex)[/\\]|/home/[^/]+/|/Users/[^/]+/", text):
                errors.append(f"Machine-specific path in {p.relative_to(ROOT)}")
    with tempfile.TemporaryDirectory(prefix="orchestrate-install-") as temporary:
        destination = Path(temporary) / ".agents" / "skills" / "orchestrate-execution"
        shutil.copytree(SKILL, destination)
        errors.extend(f"Installed package: {error}" for error in check_links(destination))
        for source in SKILL.rglob("*"):
            if source.is_file() and source.read_bytes() != (destination / source.relative_to(SKILL)).read_bytes():
                errors.append("Installed bytes differ from source")
        try:
            shutil.copytree(SKILL, destination)
        except FileExistsError:
            pass
        else:
            errors.append("Existing installation was overwritten")
    if errors:
        print("\n".join(errors))
        return 1
    print("Package files, local links, metadata, Python dependencies, provenance, private-path boundary and temporary installation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

