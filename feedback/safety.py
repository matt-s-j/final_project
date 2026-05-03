"""Content safety screening (Gate 0.5).

This module runs before any model inference to protect the workflow from
three categories of unsafe content:

1. Workplace-inappropriate language (indecent or hostile phrasing).
2. Possible criminal-offense concerns that should be routed to authorities.
3. Self-harm or crisis-related language that requires immediate support resources.

All checks use regex pattern matching against the raw input text. This is
intentionally simple and deterministic for an MVP; a future version could
replace or supplement this with a dedicated moderation model.
"""

from __future__ import annotations

import re
from typing import Iterable

from feedback.models import SafetyCheckResult, SafetyDecision


# --- Pattern Banks -----------------------------------------------------------
# Each group of patterns is checked independently so that the failure reason
# can be reported precisely and the correct escalation path is followed.

# Profane or hostile language that is not suitable for a professional setting.
# \w* after root words catches inflected forms (e.g. "fucking", "shitty").
INAPPROPRIATE_PATTERNS: tuple[str, ...] = (
    r"\b(fuck\w*|shit\w*|bitch\w*|asshole\w*)\b",
    r"\b(kill you|beat you up|shoot you)\b",
)

# Explicit sexual content that has no place in a workplace feedback tool.
SEXUAL_CONTENT_PATTERNS: tuple[str, ...] = (
    r"\b(sex|porn|nude|explicit)\b",
)

# Keywords that may indicate a criminal matter requiring legal/compliance action
# rather than an AI-assisted rewrite.
CRIMINAL_CONCERN_PATTERNS: tuple[str, ...] = (
    r"\b(stole|steal|theft|embezzle|embezzlement|fraud|bribe|assault|illegal)\b",
    r"\b(report to police|file charges|criminal)\b",
)

# Language associated with self-harm or mental health crises.
# If detected, the workflow stops and directs the user to emergency resources.
SELF_HARM_PATTERNS: tuple[str, ...] = (
    r"\b(kill myself|suicide|self harm|hurt myself|end my life|want to die)\b",
)


def _has_match(patterns: Iterable[str], text: str) -> bool:
    """Return True if any pattern in `patterns` matches anywhere in `text`.

    The search is case-insensitive. Matching stops at the first hit to
    keep screening fast.

    Args:
        patterns: An iterable of regex pattern strings to test.
        text: The input string to search.

    Returns:
        True if at least one pattern matches; False otherwise.
    """
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def screen_content(text: str) -> SafetyCheckResult:
    """Screen `text` for unsafe content and return a routing decision.

    Checks are applied in priority order:
      1. Self-harm — highest priority; triggers crisis resource guidance.
      2. Criminal concern — routes user to authorities/compliance channels.
      3. Workplace-inappropriate / sexual content — asks user to revise.

    If none of the above are detected, the function returns an ``allow``
    decision and processing continues normally.

    Args:
        text: Raw user-submitted feedback text (will be stripped before matching).

    Returns:
        A SafetyCheckResult containing the routing decision, internal reason
        tags, and a user-facing message for the UI.
    """
    # Strip leading/trailing whitespace so patterns match correctly at word
    # boundaries even if the user added extra spacing.
    normalized = text.strip()

    # --- Check 1: Self-harm signals ---
    # Checked first because this is the highest-severity condition.
    if _has_match(SELF_HARM_PATTERNS, normalized):
        return SafetyCheckResult(
            decision=SafetyDecision.escalate_self_harm,
            reasons=["self_harm_signal"],
            user_message=(
                "This appears to include self-harm related content. "
                "This app cannot process this request. If you are in immediate danger, "
                "contact emergency services now. If you are in the U.S. or Canada, call or text 988."
            ),
        )

    # --- Check 2: Possible criminal-offense concern ---
    if _has_match(CRIMINAL_CONCERN_PATTERNS, normalized):
        return SafetyCheckResult(
            decision=SafetyDecision.escalate_criminal,
            reasons=["possible_criminal_offense"],
            user_message=(
                "This appears to describe a potential criminal matter. "
                "Please contact appropriate authorities or your organization's legal/compliance team."
            ),
        )

    # --- Check 3: Indecent or sexually explicit language ---
    if _has_match(INAPPROPRIATE_PATTERNS, normalized) or _has_match(
        SEXUAL_CONTENT_PATTERNS, normalized
    ):
        return SafetyCheckResult(
            decision=SafetyDecision.block_inappropriate,
            reasons=["workplace_inappropriate_content"],
            user_message=(
                "Your input appears unsuitable for a workplace feedback workflow. "
                "Please revise using professional, workplace-appropriate language and resubmit."
            ),
        )

    # All checks passed; allow the input to proceed to Phase 1 discovery.
    return SafetyCheckResult(
        decision=SafetyDecision.allow,
        reasons=[],
        user_message="Safety check passed.",
    )
