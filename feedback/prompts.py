"""Prompt loading and rendering utilities.

This module intentionally keeps prompt handling lightweight for rapid iteration:
- Prompt files are loaded when available.
- Missing files/sections never crash startup.
- Each public builder returns a usable fallback prompt.
"""

from __future__ import annotations

from pathlib import Path
import re

from config import settings
from feedback.models import DiscoveryResult, DiscoverySession


PHASE_1_FILENAME = "phase1_organizational_psychologist.md"
PHASE_2_FILENAME = "phase2_professional_rewriter.md"


DEFAULT_PHASE_1_GUIDED_TEMPLATE = """You are a calm organizational feedback coach.
Ask exactly one focused follow-up question that helps uncover root causes.
Do not provide solutions yet.

Current round: {{current_round}} of at least {{min_rounds}}.
Conversation so far:
{{conversation}}
"""

DEFAULT_PHASE_1_SUMMARY_TEMPLATE = """Summarize the discovery conversation as strict JSON only.
Schema: {"summary": string, "root_causes": string[], "prioritized_issues": string[], "risk_flags": string[]}

Conversation:
{{conversation}}
"""

DEFAULT_PHASE_1_FALLBACK_QUESTIONS = [
    "Thank you for sharing that. What concrete behavior or moment made this issue feel important right now?",
    "Looking beneath the symptom, what pressures or assumptions do you think contributed most?",
    "What pattern seems to keep this issue repeating across interactions or handoffs?",
    "If this pattern stays unchanged, what risk or recurring impact concerns you most?",
]

DEFAULT_PHASE_2_REWRITE_TEMPLATE = """Rewrite the feedback into a professional, actionable SBI entry for a specific individual.
Use neutral tone, concrete behavior, clear impact, and next steps.
Target roughly 100-300 words.

Original feedback:
{{original_feedback}}

Diagnosed priorities:
{{diagnosed_priorities}}
"""


class PromptLibrary:
    """Load and render bot prompts with permissive fallbacks.

    Args:
        prompts_dir: Optional path to prompt markdown files. Defaults to
            settings.prompts_dir.
    """

    def __init__(self, prompts_dir: str | None = None) -> None:
        """Initialize the prompt library.

        Args:
            prompts_dir: Optional prompt directory override used by tests.
        """
        self._prompts_dir = Path(prompts_dir or settings.prompts_dir)
        self._cache: dict[str, str] = {}

    def _load_spec(self, filename: str) -> str:
        """Load prompt markdown from disk, returning empty text on failure.

        Args:
            filename: Prompt markdown file name.

        Returns:
            Prompt file content, or an empty string when unreadable/missing.
        """
        if filename in self._cache:
            return self._cache[filename]

        path = self._prompts_dir / filename
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            content = ""

        self._cache[filename] = content
        return content

    @staticmethod
    def _extract_section(markdown_text: str, heading: str) -> str | None:
        """Extract a level-2 markdown section by exact heading text.

        Args:
            markdown_text: Full markdown content.
            heading: Exact level-2 heading text.

        Returns:
            Section body when found, otherwise None.
        """
        pattern = rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
        match = re.search(pattern, markdown_text, flags=re.MULTILINE)
        if not match:
            return None
        return match.group(1).strip()

    @staticmethod
    def _render(template_text: str, replacements: dict[str, str]) -> str:
        """Render template placeholders in {{name}} format.

        Args:
            template_text: Template text containing placeholders.
            replacements: Mapping of placeholder key to replacement text.

        Returns:
            Rendered text with placeholder substitutions.
        """
        rendered = template_text
        for key, value in replacements.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        return rendered

    def _phase_1_spec(self) -> str:
        """Return the full Phase 1 prompt markdown."""
        return self._load_spec(PHASE_1_FILENAME)

    def _phase_2_spec(self) -> str:
        """Return the full Phase 2 prompt markdown."""
        return self._load_spec(PHASE_2_FILENAME)

    def _best_effort_template(self, spec: str, section_heading: str, default_template: str) -> str:
        """Choose a template section when available, otherwise use the built-in default.

        Only the named section is used from the prompt file. If it is absent or
        the file is missing, the built-in default is used. The full file is never
        used as a prompt to avoid sending large prose docs to the LLM.

        Args:
            spec: Full prompt markdown content.
            section_heading: Preferred section heading to extract.
            default_template: Known-safe built-in fallback template.

        Returns:
            Selected template text.
        """
        if spec:
            section = self._extract_section(spec, section_heading)
            if section:
                return section
        return default_template

    def get_phase_1_guided_turn_prompt(self, session: DiscoverySession) -> str:
        """Build a guided discovery follow-up prompt.

        Args:
            session: Current discovery session.

        Returns:
            Rendered prompt for one guided follow-up turn.
        """
        spec = self._phase_1_spec()
        template = self._best_effort_template(
            spec,
            "Guided Turn Prompt Template",
            DEFAULT_PHASE_1_GUIDED_TEMPLATE,
        )

        conversation = "\n".join(
            f"{message.role.upper()}: {message.content}" for message in session.messages
        )
        return self._render(
            template,
            {
                "current_round": str(session.user_reply_count + 1),
                "min_rounds": str(session.min_rounds_required),
                "conversation": conversation,
            },
        )

    def get_phase_1_summary_prompt(self, session: DiscoverySession) -> str:
        """Build a discovery summary prompt.

        Args:
            session: Completed discovery session.

        Returns:
            Rendered prompt requesting structured diagnosis output.
        """
        spec = self._phase_1_spec()
        template = self._best_effort_template(
            spec,
            "Discovery Summary Prompt Template",
            DEFAULT_PHASE_1_SUMMARY_TEMPLATE,
        )

        conversation = "\n".join(
            f"{message.role.upper()}: {message.content}" for message in session.messages
        )
        return self._render(template, {"conversation": conversation})

    def get_phase_1_fallback_questions(self) -> list[str]:
        """Return deterministic fallback questions for local mode.

        Returns:
            Ordered list of fallback questions.
        """
        spec = self._phase_1_spec()
        section = self._extract_section(spec, "Fallback Questions") if spec else None
        source_text = section if section else spec

        questions: list[str] = []
        for line in source_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                questions.append(stripped[2:].strip())
            elif stripped.startswith('> "') and stripped.endswith('"'):
                # Also accept block-quoted question lines used in prose prompt docs.
                questions.append(stripped[3:-1].strip())

        if questions:
            return questions
        return DEFAULT_PHASE_1_FALLBACK_QUESTIONS.copy()

    def get_phase_2_rewrite_prompt(self, user_text: str, diagnosis: DiscoveryResult) -> str:
        """Build a rewrite prompt from Phase 2 guidance.

        Args:
            user_text: Original user feedback text.
            diagnosis: Structured Phase 1 diagnosis.

        Returns:
            Rendered prompt for rewrite generation.
        """
        spec = self._phase_2_spec()
        template = self._best_effort_template(
            spec,
            "Rewrite Prompt Template",
            DEFAULT_PHASE_2_REWRITE_TEMPLATE,
        )

        diagnosed_priorities = "\n".join(
            f"- {item}" for item in diagnosis.prioritized_issues
        )
        return self._render(
            template,
            {
                "original_feedback": user_text,
                "diagnosed_priorities": diagnosed_priorities,
            },
        )


prompt_library = PromptLibrary()
