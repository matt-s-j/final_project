"""Prompt loading and rendering utilities.

This module externalizes bot behavior into markdown files so prompt updates can
happen without editing orchestration code. It loads one markdown file per bot,
extracts the relevant sections, and renders placeholders with runtime context.
"""

from __future__ import annotations

from pathlib import Path
import re

from config import settings
from feedback.models import DiscoveryResult, DiscoverySession


PHASE_1_FILENAME = "phase1_organizational_psychologist.md"
PHASE_2_FILENAME = "phase2_professional_rewriter.md"


FALLBACK_PHASE_1_SPEC = """# Phase 1 Bot: Organizational Psychologist

## Guided Turn Prompt Template
You are an expert organizational psychologist facilitating a workplace feedback intake.
Your role is part fact-finder, part therapist, and part calm but critical guide.
Use a 5-whys style approach to move from symptoms to deeper causes.
Ask exactly one concise follow-up question.
Do not summarize yet.
Do not give advice yet.
Keep the tone grounded, emotionally regulating, and analytically sharp.

Current round: {{current_round}} of at least {{min_rounds}}.
Conversation so far:
{{conversation}}

## Discovery Summary Prompt Template
You are an expert organizational psychologist summarizing a guided workplace intake.
Return ONLY valid JSON with this schema:
{"summary": string, "root_causes": string[], "prioritized_issues": string[], "risk_flags": string[]}
The summary must reflect a 5-whys style root-cause analysis based on the conversation.
Keep language professional, calm, and grounded in facts.

Conversation:
{{conversation}}

## Fallback Questions
- Thank you for laying that out. Let's slow this down and get specific. What concrete behavior, event, or exchange made this issue feel important right now?
- Why do you think that happened? Look beneath the immediate symptom and name the pressures, assumptions, or habits that may have driven it.
- Why do you think those underlying conditions existed? Consider incentives, role confusion, communication gaps, or broader team dynamics.
- If that deeper pattern stays unchanged, what is the real organizational risk or repeated outcome you are most concerned about?
"""


FALLBACK_PHASE_2_SPEC = """# Phase 2 Bot: Professional Rewriter

## Rewrite Prompt Template
Rewrite the feedback into a professional, actionable message.
Use neutral tone and clear next steps.
Keep under 180 words.

Original feedback:
{{original_feedback}}

Diagnosed priorities:
{{diagnosed_priorities}}
"""


class PromptLibrary:
    """Load and render bot prompts from markdown files.

    The loader caches prompt specs in memory after first read. If files are
    missing or malformed, the library falls back to embedded defaults.

    Args:
        prompts_dir: Optional path to prompt markdown files. Defaults to
            ``settings.prompts_dir``.
    """

    def __init__(self, prompts_dir: str | None = None) -> None:
        self._prompts_dir = Path(prompts_dir or settings.prompts_dir)
        self._cache: dict[str, str] = {}

    def _load_spec(self, filename: str, fallback_content: str) -> str:
        """Load one markdown prompt spec with resilient fallback behavior.

        Args:
            filename: Prompt markdown file name.
            fallback_content: Embedded fallback content used if file loading fails.

        Returns:
            Prompt spec markdown content.
        """
        if filename in self._cache:
            return self._cache[filename]

        path = self._prompts_dir / filename
        try:
            content = path.read_text(encoding="utf-8")
            # Empty prompt files should not replace a known-safe fallback.
            if not content.strip():
                content = fallback_content
        except OSError:
            content = fallback_content

        self._cache[filename] = content
        return content

    @staticmethod
    def _extract_section(markdown_text: str, heading: str) -> str | None:
        """Extract a level-2 markdown section body by its heading text.

        Args:
            markdown_text: Full markdown content.
            heading: Exact level-2 heading text to extract.

        Returns:
            Section body or ``None`` if heading was not found.
        """
        pattern = rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
        match = re.search(pattern, markdown_text, flags=re.MULTILINE)
        if not match:
            return None
        return match.group(1).strip()

    @staticmethod
    def _render(template_text: str, replacements: dict[str, str]) -> str:
        """Render template placeholders in ``{{name}}`` format.

        Args:
            template_text: Template containing placeholders.
            replacements: Mapping of placeholder key to replacement text.

        Returns:
            Rendered prompt text.
        """
        rendered = template_text
        for key, value in replacements.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        return rendered

    def _phase_1_spec(self) -> str:
        """Return the full Phase 1 prompt specification markdown."""
        return self._load_spec(PHASE_1_FILENAME, FALLBACK_PHASE_1_SPEC)

    def _phase_2_spec(self) -> str:
        """Return the full Phase 2 prompt specification markdown."""
        return self._load_spec(PHASE_2_FILENAME, FALLBACK_PHASE_2_SPEC)

    def get_phase_1_guided_turn_prompt(self, session: DiscoverySession) -> str:
        """Build the guided discovery turn prompt from markdown spec.

        Args:
            session: Current discovery session.

        Returns:
            Rendered prompt for one guided follow-up turn.
        """
        spec = self._phase_1_spec()
        fallback_spec = FALLBACK_PHASE_1_SPEC
        template = self._extract_section(spec, "Guided Turn Prompt Template")
        if not template:
            template = self._extract_section(fallback_spec, "Guided Turn Prompt Template") or ""

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
        """Build the discovery summary prompt from markdown spec.

        Args:
            session: Completed discovery session.

        Returns:
            Rendered prompt requesting structured JSON diagnosis.
        """
        spec = self._phase_1_spec()
        fallback_spec = FALLBACK_PHASE_1_SPEC
        template = self._extract_section(spec, "Discovery Summary Prompt Template")
        if not template:
            template = self._extract_section(fallback_spec, "Discovery Summary Prompt Template") or ""

        conversation = "\n".join(
            f"{message.role.upper()}: {message.content}" for message in session.messages
        )
        return self._render(template, {"conversation": conversation})

    def get_phase_1_fallback_questions(self) -> list[str]:
        """Return deterministic fallback questions from the Phase 1 prompt spec.

        Returns:
            Ordered list of fallback questions for local mode.
        """
        spec = self._phase_1_spec()
        fallback_spec = FALLBACK_PHASE_1_SPEC
        section = self._extract_section(spec, "Fallback Questions")
        if not section:
            section = self._extract_section(fallback_spec, "Fallback Questions") or ""

        questions = []
        for line in section.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                questions.append(stripped[2:].strip())

        if questions:
            return questions

        # Defensive fallback in case a malformed prompt file removes list markers.
        return [
            "Thank you for laying that out. What concrete behavior made this issue feel important now?"
        ]

    def get_phase_2_rewrite_prompt(self, user_text: str, diagnosis: DiscoveryResult) -> str:
        """Build the rewrite prompt from markdown spec.

        Args:
            user_text: Original user feedback text.
            diagnosis: Structured Phase 1 diagnosis.

        Returns:
            Rendered prompt for rewrite generation.
        """
        spec = self._phase_2_spec()
        fallback_spec = FALLBACK_PHASE_2_SPEC
        template = self._extract_section(spec, "Rewrite Prompt Template")
        if not template:
            template = self._extract_section(fallback_spec, "Rewrite Prompt Template") or ""

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
