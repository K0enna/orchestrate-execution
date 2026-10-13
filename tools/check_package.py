"""Validate the distributable skill and its local links using the standard library."""
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "orchestrate-execution"


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


def main():
    errors = []
    required = [
        ROOT / "README.md", ROOT / "LICENSE", ROOT / "docs" / "benchmarks.md",
        SKILL / "SKILL.md", SKILL / "agents" / "openai.yaml",
        SKILL / "references" / "codex.md",
        ROOT / "docs" / "modes.md", ROOT / "CHANGELOG.md",
        SKILL / "references" / "detached-mode.md",
        SKILL / "references" / "chatgpt-handover.md",
        SKILL / "scripts" / "detached_receipt.py",
        SKILL / "scripts" / "workbench_claim.py",
        SKILL / "scripts" / "test_detached_receipt.py",
        SKILL / "scripts" / "test_workbench_claim.py",
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
    print("Package files, local links, metadata, private-path boundary and temporary installation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

