"""Prompt loading utilities.

Loads the Phase 1 and Phase 2 system prompts from their markdown files.
Files are read fresh on every call — no caching, no parsing, no fallbacks.
If a file is missing, a FileNotFoundError will raise loudly.
"""

from pathlib import Path

from config import settings


def get_phase1_prompt() -> str:
    """Load and return the full Phase 1 organizational psychologist system prompt.

    Returns:
        Full markdown content of the Phase 1 prompt file.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = Path(settings.prompts_dir) / "phase1_organizational_psychologist.md"
    return path.read_text(encoding="utf-8")


def get_phase2_prompt() -> str:
    """Load and return the full Phase 2 professional rewriter system prompt.

    Returns:
        Full markdown content of the Phase 2 prompt file.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = Path(settings.prompts_dir) / "phase2_professional_rewriter.md"
    return path.read_text(encoding="utf-8")
