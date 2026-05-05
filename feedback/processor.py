"""Workflow orchestration for the two-phase feedback pipeline.

This module is the core of the application. It coordinates:
    - Gate 0: input length validation.
    - Gate 0.5: safety and appropriateness screening.
    - Phase 1 (Discovery): guided multi-turn intake using a 5-whys style approach.
    - Gate 1: completion gate requiring enough guided follow-up context.
    - Phase 1 summary: structured diagnosis synthesized from the completed intake.
    - Phase 2 (Rewrite): professional rewrite generation with local fallback.

Both public functions return a ``WorkflowResult`` so that the Gradio UI
handlers only need to check ``.ok`` and read the relevant output field.
"""

from __future__ import annotations

from typing import Any

from config import settings
from feedback.llm import HFInferenceClient, LLMError
from feedback.models import (
    ConversationMessage,
    DiscoveryResult,
    DiscoverySession,
    SafetyDecision,
    WorkflowResult,
)
from feedback.prompts import prompt_library
from feedback.safety import screen_content


def _local_discovery_fallback(text: str) -> DiscoveryResult:
    """Generate a rule-based discovery result when LLM inference is unavailable.

    This fallback applies a small set of heuristics to produce a basic but
    still useful diagnosis. It runs when:
      - The HF API token is missing (local development without credentials).
      - The API call times out or returns an error.
      - The model response does not contain valid structured JSON.

    Args:
        text: The raw user-submitted feedback text.

    Returns:
        A DiscoveryResult populated from local heuristic rules.
    """
    lowered = text.lower()
    root_causes: list[str] = []
    prioritized: list[str] = []

    # Absolute language ("always", "never") weakens professional feedback.
    if "always" in lowered or "never" in lowered:
        root_causes.append("Overgeneralized language may reduce credibility.")
        prioritized.append("Replace absolute terms with specific examples.")

    # Very short feedback is usually too vague to be acted upon.
    if len(text.split()) < 30:
        root_causes.append("Feedback may be too brief to be actionable.")
        prioritized.append("Add concrete examples and expected outcomes.")

    # Default issue if no specific heuristic triggered.
    if not root_causes:
        root_causes.append("Tone and structure can be improved for clarity.")
        prioritized.append("Use a behavior-impact-next-step format.")

    return DiscoveryResult(
        summary="Initial diagnosis generated using local fallback rules.",
        root_causes=root_causes,
        prioritized_issues=prioritized,
        risk_flags=[],
    )


def _local_guided_question(session: DiscoverySession) -> str:
    """Return a deterministic follow-up question for the guided intake.

    The fallback mirrors an expert organizational psychologist using a calm,
    fact-finding 5-whys style progression. It asks one focused question at a time.

    Args:
        session: The current guided discovery session.

    Returns:
        A single follow-up question for the next guided turn.
    """
    templates = prompt_library.get_phase_1_fallback_questions()
    index = min(session.user_reply_count, len(templates) - 1)
    return templates[index]


def _build_guided_discovery_turn_prompt(session: DiscoverySession) -> str:
    """Assemble the prompt for the next guided Phase 1 follow-up question.

    The assistant persona is intentionally constrained: an expert organizational
    psychologist who is calm, probing, factual, and oriented toward root causes.

    Args:
        session: The current guided discovery session.

    Returns:
        A prompt that instructs the model to ask exactly one focused next question.
    """
    return prompt_library.get_phase_1_guided_turn_prompt(session)


def _build_discovery_summary_prompt(session: DiscoverySession) -> str:
    """Assemble the structured summary prompt for the completed Phase 1 intake.

    Args:
        session: Completed guided discovery session.

    Returns:
        A prompt requesting JSON aligned with the DiscoveryResult schema.
    """
    return prompt_library.get_phase_1_summary_prompt(session)


def _build_rewrite_prompt(user_text: str, diagnosis: DiscoveryResult) -> str:
    """Assemble the Phase 2 rewrite prompt sent to the LLM.

    The prompt passes both the original text and the prioritized issues from
    Phase 1 so the model can target the right improvements.

    Args:
        user_text: Stripped original feedback text.
        diagnosis: Structured output from the completed Phase 1 discovery.

    Returns:
        A complete prompt string ready to send to the inference API.
    """
    return prompt_library.get_phase_2_rewrite_prompt(user_text, diagnosis)


def _count_remaining_rounds(session: DiscoverySession) -> int:
    """Return how many more guided follow-up answers are needed before completion.

    Args:
        session: The current guided discovery session.

    Returns:
        Non-negative integer count of unanswered minimum rounds.
    """
    return max(session.min_rounds_required - session.user_reply_count, 0)


def start_discovery_session(
    user_text: str,
    client: HFInferenceClient | None = None,
) -> WorkflowResult:
    """Start the guided Phase 1 discovery conversation.

    Gate order:
      1. Gate 0 — reject an initial statement that is too short.
      2. Gate 0.5 — screen the initial statement for unsafe content.
      3. Guided intake start — create a session and ask the first probing question.

    Args:
        user_text: Initial problem statement submitted by the user.
        client: Optional inference client for testing or dependency injection.

    Returns:
        A WorkflowResult containing a populated DiscoverySession when successful.
    """
    text = user_text.strip()
    if len(text) < settings.min_input_length:
        return WorkflowResult(
            ok=False,
            gate="gate_0_input_validity",
            user_message=(
                f"Please provide at least {settings.min_input_length} characters before starting discovery."
            ),
        )

    safety = screen_content(text)
    if safety.decision != SafetyDecision.allow:
        return WorkflowResult(
            ok=False,
            gate="gate_0_5_safety",
            user_message=safety.user_message,
        )

    session = DiscoverySession(
        original_input=text,
        messages=[ConversationMessage(role="user", content=text)],
        min_rounds_required=settings.discovery_min_rounds,
    )

    inference_client = client if client is not None else HFInferenceClient()
    try:
        assistant_question = inference_client.run_guided_discovery_turn(
            _build_guided_discovery_turn_prompt(session)
        )
    except LLMError:
        assistant_question = _local_guided_question(session)

    session.messages.append(ConversationMessage(role="assistant", content=assistant_question))
    rounds_remaining = _count_remaining_rounds(session)
    return WorkflowResult(
        ok=True,
        gate="phase_1_guided_discovery_started",
        user_message=(
            "Phase 1 started. Answer the follow-up question so we can keep digging beneath the initial symptom. "
            f"Minimum guided answers remaining before completion: {rounds_remaining}."
        ),
        session=session,
    )


def continue_discovery_session(
    session: DiscoverySession | None,
    user_reply: str,
    client: HFInferenceClient | None = None,
) -> WorkflowResult:
    """Continue the guided Phase 1 conversation with one user reply.

    Every reply is safety-screened before it is added to the session. Once the
    required number of guided answers has been collected, the function stops
    asking new questions and tells the UI that completion can proceed.

    Args:
        session: Existing discovery session returned by ``start_discovery_session``.
        user_reply: Latest answer from the user.
        client: Optional inference client for testing or dependency injection.

    Returns:
        A WorkflowResult containing the updated session when successful.
    """
    if session is None:
        return WorkflowResult(
            ok=False,
            gate="phase_1_session_required",
            user_message="Start Phase 1 before sending follow-up responses.",
        )

    reply = user_reply.strip()
    if len(reply) < 8:
        return WorkflowResult(
            ok=False,
            gate="gate_0_follow_up_validity",
            user_message="Please answer with a bit more detail so the analysis can go deeper.",
            session=session,
        )

    safety = screen_content(reply)
    if safety.decision != SafetyDecision.allow:
        return WorkflowResult(
            ok=False,
            gate="gate_0_5_safety",
            user_message=safety.user_message,
            session=session,
        )

    session.messages.append(ConversationMessage(role="user", content=reply))
    session.user_reply_count += 1

    rounds_remaining = _count_remaining_rounds(session)
    if rounds_remaining == 0 and session.user_reply_count == session.min_rounds_required:
        session.messages.append(
            ConversationMessage(
                role="assistant",
                content=(
                    "Thank you, this context is very helpful. I have started drafting a suggested "
                    "feedback version on the right while we keep this conversation going. "
                    "You can continue answering questions, and you can complete discovery whenever "
                    "you want the formal summary."
                ),
            )
        )
        return WorkflowResult(
            ok=True,
            gate="gate_1_ready_for_completion",
            user_message=(
                "Phase 1 has enough context. Composer suggestions are now available, "
                "and you can complete discovery whenever you want the structured diagnosis."
            ),
            session=session,
        )

    inference_client = client if client is not None else HFInferenceClient()
    try:
        assistant_question = inference_client.run_guided_discovery_turn(
            _build_guided_discovery_turn_prompt(session)
        )
    except LLMError:
        assistant_question = _local_guided_question(session)

    session.messages.append(ConversationMessage(role="assistant", content=assistant_question))
    return WorkflowResult(
        ok=True,
        gate="phase_1_guided_discovery_active",
        user_message=(
            "Phase 1 is active. Keep following the thread beneath the symptom. "
            f"Minimum guided answers remaining before completion: {rounds_remaining}."
            if rounds_remaining > 0
            else "Phase 1 is active beyond the minimum threshold. Chat and composer can now progress in parallel."
        ),
        session=session,
    )


def generate_composer_suggestion(
    working_draft: str,
    session: DiscoverySession | None,
    client: HFInferenceClient | None = None,
) -> WorkflowResult:
    """Generate a composer-only suggestion using the current Working Draft as input.

    The Working Draft remains entirely user-owned. This function never mutates the
    draft; it only produces a separate suggestion pane output. Composer suggestions
    become available only after the minimum guided fact-finding threshold is met.

    Args:
        working_draft: Current user-edited Working Draft text.
        session: Guided discovery session carrying the conversation history.
        client: Optional inference client for testing or dependency injection.

    Returns:
        A WorkflowResult with ``rewrite`` populated when a suggestion is available.
    """
    if session is None:
        return WorkflowResult(
            ok=False,
            gate="phase_1_session_required",
            user_message="Start Phase 1 before requesting composer suggestions.",
        )

    rounds_remaining = _count_remaining_rounds(session)
    if rounds_remaining > 0:
        return WorkflowResult(
            ok=False,
            gate="gate_1_completion_required",
            user_message=(
                "Composer suggestions are locked until the minimum fact-finding turns are complete. "
                f"Remaining guided answers needed: {rounds_remaining}."
            ),
            session=session,
        )

    base_text = working_draft.strip() or session.original_input
    discovery_result = complete_discovery_session(session, client=client)
    if not discovery_result.ok or discovery_result.discovery is None:
        return discovery_result

    inference_client = client if client is not None else HFInferenceClient()
    prompt = _build_rewrite_prompt(base_text, discovery_result.discovery)

    try:
        suggestion = inference_client.run_rewrite(prompt)
        if not suggestion:
            raise LLMError("Empty composer suggestion response.")
    except LLMError:
        suggestion = (
            "Suggested rewrite (local fallback):\n"
            "Thank you for the work so far. Based on the context gathered, the main opportunity is to "
            "make the message more specific, more neutral in tone, and clearer about the next step you "
            "want from the other person. Use the Working Draft as your base, then tighten the language "
            "around observed behavior, impact, and expected change."
        )

    return WorkflowResult(
        ok=True,
        gate="composer_suggestion_ready",
        user_message="Composer suggestion updated.",
        session=session,
        discovery=discovery_result.discovery,
        rewrite=suggestion,
    )


def complete_discovery_session(
    session: DiscoverySession | None,
    client: HFInferenceClient | None = None,
) -> WorkflowResult:
    """Complete Phase 1 by synthesizing the guided intake into a DiscoveryResult.

    Gate order:
      1. Session required — Phase 1 must have been started.
      2. Gate 1 — require enough guided answers before summary generation.
      3. Summary synthesis — attempt LLM JSON synthesis; fall back to local rules.

    Args:
        session: Guided discovery session carrying the conversation history.
        client: Optional inference client for testing or dependency injection.

    Returns:
        A WorkflowResult with a populated DiscoveryResult on success.
    """
    if session is None:
        return WorkflowResult(
            ok=False,
            gate="phase_1_session_required",
            user_message="Start and complete the guided Phase 1 intake before moving on.",
        )

    rounds_remaining = _count_remaining_rounds(session)
    if rounds_remaining > 0:
        return WorkflowResult(
            ok=False,
            gate="gate_1_completion_required",
            user_message=(
                "Phase 1 is not complete yet. "
                f"Please answer {rounds_remaining} more guided question(s) before completion."
            ),
            session=session,
        )

    inference_client = client if client is not None else HFInferenceClient()
    combined_text = "\n".join(
        message.content for message in session.messages if message.role == "user"
    )
    try:
        payload: dict[str, Any] = inference_client.run_discovery(
            _build_discovery_summary_prompt(session)
        )
        discovery = DiscoveryResult(**payload)
        if not discovery.root_causes or not discovery.prioritized_issues:
            raise ValueError("Discovery output missing required diagnosis details.")
    except (LLMError, ValueError, TypeError):
        discovery = _local_discovery_fallback(combined_text)

    return WorkflowResult(
        ok=True,
        gate="gate_1_discovery_validity",
        user_message="Discovery complete. Review diagnosis and confirm before rewrite.",
        session=session,
        discovery=discovery,
    )


def run_rewrite_flow(
    user_text: str,
    discovery: DiscoveryResult | None,
    confirmed: bool,
    client: HFInferenceClient | None = None,
) -> WorkflowResult:
    """Run Phase 2: generate a professional rewrite using the Phase 1 diagnosis.

    Gate order:
      1. Gate 1 check — require a completed discovery result.
      2. Confirmation gate — require explicit user sign-off on the diagnosis.
      3. Phase 2 inference — attempt LLM rewrite; fall back to a canned example on failure.

    Args:
        user_text: The original feedback text (same input used in Phase 1).
        discovery: The DiscoveryResult from a successful Phase 1 run.
            Passing ``None`` will block the rewrite at the gate check.
        confirmed: Whether the user has checked the confirmation checkbox in the UI.
        client: Optional HFInferenceClient for testing. Defaults to the
            standard client when ``None``.

    Returns:
        A WorkflowResult with ``ok=True`` and a populated ``rewrite`` field on
        success, or ``ok=False`` with a user-facing error message on gate failure.
    """
    # Gate 1 check: cannot rewrite without a completed discovery result.
    if discovery is None:
        return WorkflowResult(
            ok=False,
            gate="gate_1_discovery_validity",
            user_message="Run discovery first before requesting rewrite.",
        )

    # Confirmation gate: user must explicitly acknowledge the diagnosis.
    if not confirmed:
        return WorkflowResult(
            ok=False,
            gate="gate_confirmation",
            user_message="Please confirm the diagnosis before rewrite.",
        )

    inference_client = client if client is not None else HFInferenceClient()
    prompt = _build_rewrite_prompt(user_text.strip(), discovery)

    try:
        rewrite = inference_client.run_rewrite(prompt)
        if not rewrite:
            raise LLMError("Empty rewrite response.")
    except LLMError:
        # Inference failed; provide a generic but professionally structured example.
        rewrite = (
            "Suggested rewrite (local fallback):\n"
            "Thank you for your effort on this work. I noticed a few areas where we can improve "
            "clarity and execution. Specifically, aligning deliverable expectations earlier and "
            "sharing progress updates more consistently would reduce rework. For next steps, "
            "let's agree on milestones and a weekly check-in cadence."
        )

    return WorkflowResult(
        ok=True,
        gate="gate_2_rewrite_validity",
        user_message="Rewrite complete.",
        discovery=discovery,
        rewrite=rewrite,
    )
