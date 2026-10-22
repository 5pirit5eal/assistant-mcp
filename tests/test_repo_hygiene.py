"""Repo hygiene: no committed secrets, and doc cross-references stay valid."""

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".vibe" / "skills"
SKIP_DIRS = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}
)
MAX_FILE_BYTES = 1_000_000
SECRET_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("AWS access key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
]
HARDCODED_SECRET = re.compile(
    r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
    r"\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"
)
BACKTICKED = re.compile(r"`([^`\n]+)`")
PATH_LIKE = re.compile(r"[A-Za-z0-9_./-]+")
SKILL_REFERENCE = re.compile(r"\bopenspec-[a-z0-9]+(?:-[a-z0-9]+)*\b")


def _repo_files() -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        files.extend(Path(dirpath, name) for name in sorted(filenames))
    return files


def _read_text(path: Path) -> str | None:
    if path.stat().st_size > MAX_FILE_BYTES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        return None


def test_no_secrets_or_env_files_committed() -> None:
    findings = []
    for path in _repo_files():
        relative = path.relative_to(REPO_ROOT)
        if path.name == ".env" or path.name.startswith(".env."):
            findings.append(f"{relative}: dotenv file committed")
            continue
        text = _read_text(path)
        if text is None:
            continue
        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(f"{relative}: {label}: {match.group(0)[:16]}...")
        for match in HARDCODED_SECRET.finditer(text):
            findings.append(f"{relative}: hardcoded secret: {match.group(0)[:48]}...")
    assert not findings, "secrets must stay out of the repo:\n" + "\n".join(findings)


def test_agents_md_path_references_exist() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    candidates = [
        token
        for token in BACKTICKED.findall(text)
        if PATH_LIKE.fullmatch(token) and ("/" in token or token.startswith("."))
    ]
    assert candidates, "no path references found in AGENTS.md; extraction is broken"
    missing = [token for token in candidates if not (REPO_ROOT / token).exists()]
    assert not missing, f"AGENTS.md references missing paths: {missing}"


def test_skill_cross_references_exist() -> None:
    findings = []
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        for reference in SKILL_REFERENCE.findall(text):
            if not (SKILLS_DIR / reference / "SKILL.md").exists():
                findings.append(f"{skill_md.parent.name}: unknown skill {reference!r}")
    assert not findings, "broken skill cross-references:\n" + "\n".join(findings)
