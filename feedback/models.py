"""Shared data models for the feedback workflow.

All models use Pydantic so that data coming back from the LLM (which is
just raw text/JSON) is validated and typed before the rest of the app
touches it. This is the single source of truth for every data shape
passed between modules.
"""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class SafetyDecision(str, Enum):
    """Possible outcomes of the Gate 0.5 safety screening check.

    Values:
        allow: Content is workplace-appropriate; processing can continue.
        block_inappropriate: Content contains indecent or unsuitable language.
        escalate_criminal: Content suggests a potential criminal-offense concern.
        escalate_self_harm: Content contains self-harm or crisis-related language.
    """

    allow = "allow"
    block_inappropriate = "block_inappropriate"
    escalate_criminal = "escalate_criminal"
    escalate_self_harm = "escalate_self_harm"


class SafetyCheckResult(BaseModel):
    """Result returned by the content safety screener.

    Attributes:
        decision: The gate outcome that determines whether processing continues.
        reasons: Internal tags explaining why the decision was made (used for debugging).
        user_message: Human-readable message displayed directly in the UI.
    """

    decision: SafetyDecision
    # Internal labels used for logging/debugging, not shown to the user.
    reasons: List[str] = Field(default_factory=list)
    user_message: str


class DiscoveryResult(BaseModel):
    """Structured output from Phase 1 (Discovery) model inference.

    This is either populated from a valid LLM JSON response or produced
    by the local fallback rules in processor.py when inference fails.

    Attributes:
        summary: A brief narrative of the overall feedback diagnosis.
        root_causes: List of underlying reasons the feedback has quality issues.
        prioritized_issues: Ordered list of specific improvements to address.
        risk_flags: Any tone, legal, or sensitivity concerns detected in the text.
    """

    summary: str
    root_causes: List[str] = Field(default_factory=list)
    prioritized_issues: List[str] = Field(default_factory=list)
    # Flags for anything sensitive, risky, or requiring extra attention.
    risk_flags: List[str] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    """One message in the guided Phase 1 conversation.

    Attributes:
        role: Conversation speaker role. Expected values are ``user`` or ``assistant``.
        content: Plain-text content shown in the Gradio chatbot UI.
    """

    role: str
    content: str


class DiscoverySession(BaseModel):
    """State carried across the multi-turn guided discovery phase.

    Attributes:
        original_input: The user's initial problem statement.
        messages: Ordered conversation history between the user and the Phase 1 guide.
        user_reply_count: Number of follow-up answers the user has provided after the
            initial problem statement.
        min_rounds_required: Number of follow-up answers required before discovery can
            be completed and summarized into a DiscoveryResult.
    """

    original_input: str
    messages: List[ConversationMessage] = Field(default_factory=list)
    user_reply_count: int = 0
    min_rounds_required: int = 3


class WorkflowResult(BaseModel):
    """Unified result envelope returned by every processor function.

    Using a single result type for both phases keeps the Gradio handler
    code simple: it only checks `ok` and then reads the relevant field.

    Attributes:
        ok: True when the phase completed successfully and the gate passed.
        gate: Identifier of the gate that was evaluated (used for debugging).
        user_message: Human-readable status or error message for the UI.
        session: Populated during the interactive Phase 1 flow; None otherwise.
        discovery: Populated on successful completion of Phase 1; None otherwise.
        rewrite: Populated on successful completion of Phase 2; None otherwise.
    """

    ok: bool
    # Name of the gate that produced this result, e.g. "gate_0_5_safety".
    gate: str
    user_message: str
    session: DiscoverySession | None = None
    discovery: DiscoveryResult | None = None
    rewrite: str | None = None
