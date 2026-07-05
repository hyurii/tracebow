#!/usr/bin/env python3
"""Fail CI if a Tracebow compose file references a forbidden LLM.

This guard enforces the policy in AI/model-provenance.md (note: AI/ is
git-ignored; the policy is also summarised in the project README's "Models"
section).

Usage:
    python scripts/check_model_provenance.py
    python scripts/check_model_provenance.py path/to/compose.yml

Exit code is non-zero if any denied model name appears in the scanned files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TARGETS = [
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose.dev.yml",
]

DENIED_MODELS: tuple[str, ...] = (
    "qwen",
    "deepseek",
    "yi-",
    "yi:",
    "yi_",
    "chatglm",
    "glm-",
    "glm:",
    "glm4",
    "baichuan",
    "minimax",
    "internlm",
)

ALLOWED_PROVIDERS_HINT = (
    "Allowed providers: Microsoft (phi*), Meta (llama*), Mistral AI "
    "(mistral*, codestral, mixtral), IBM (granite*), Google (gemma*, "
    "codegemma*). See AI/model-provenance.md."
)

MODEL_LINE_RE = re.compile(
    r"(?:ollama\s+(?:pull|run|create)\s+|OLLAMA_MODEL[A-Z_]*\s*[:=]\s*)"
    r"([\w\-:.]+)",
    re.IGNORECASE,
)


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return a list of (line_number, model_string, denied_token) for hits."""
    if not path.exists():
        return []
    hits: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        for match in MODEL_LINE_RE.finditer(line):
            model = match.group(1)
            lowered = model.lower()
            for denied in DENIED_MODELS:
                if denied in lowered:
                    hits.append((lineno, model, denied))
                    break
    return hits


def _display(path: Path) -> str:
    """Render a path as repo-relative when possible, else absolute."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str]) -> int:
    targets = (
        [Path(p).resolve() for p in argv[1:]] if len(argv) > 1 else DEFAULT_TARGETS
    )

    any_hits = False
    for target in targets:
        if not target.exists():
            print(f"[skip] {_display(target)} (not found)")
            continue
        hits = scan_file(target)
        if not hits:
            print(f"[ok]   {_display(target)}: no denied models referenced")
            continue
        any_hits = True
        print(f"[FAIL] {_display(target)}")
        for lineno, model, denied in hits:
            print(
                f"       line {lineno}: model {model!r} matches denied "
                f"family {denied!r}"
            )

    if any_hits:
        print()
        print("Tracebow forbids the LLM(s) above by policy.")
        print(ALLOWED_PROVIDERS_HINT)
        return 1

    print()
    print("Model provenance check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
