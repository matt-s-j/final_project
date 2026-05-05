"""Workflow orchestration for the two-phase feedback pipeline.

Four simple functions covering the core loop:
  1. start_session     — create a session and ask the first discovery question.
  2. continue_session  — add a user reply and ask the next question.
  3. complete_session  — summarize the conversation into a structured diagnosis.
  4. generate_suggestion — produce a Phase 2 professional rewrite suggestion.

Sessions are plain dicts so they serialize cleanly into Gradio gr.State.
"""

from __future__ import annotations

from feedback.llm import HFInferenceClient
from feedback.prompts import get_phase1_prompt, get_phase2_prompt


def start_session(
    user_text: str,
    client: HFInferenceClient | None = None,
) -> dict:
    """Start a new guided discovery session with the user's opening statement.

    Calls the Phase 1 model to ask the first follow-up question, then returns
    the initial session dict containing the conversation so far.

    Args:
        user_text: The user's initial workplace feedback statement.
        client: Optional inference client (used in tests to avoid real API calls).

    Returns:
        A session dict with keys: original, messages, reply_count.
    """
    inference_client = client if client is not None else HFInferenceClient()
    system = get_phase1_prompt()
    messages = [{"role": "user", "content": user_text}]
    question = inference_client.ask_question(system, messages)
    messages.append({"role": "assistant", "content": question})
    return {
        "original": user_text,
        "messages": messages,
        "reply_count": 0,
    }


def continue_session(
    session: dict,
    user_reply: str,
    client: HFInferenceClient | None = None,
) -> dict:
    """Add a user reply to the session and ask the next follow-up question.

    Args:
        session: Existing session dict from start_session or a prior call.
        user_reply: The user's latest answer to the assistant's question.
        client: Optional inference client (used in tests to avoid real API calls).

    Returns:
        Updated session dict with the new reply and next assistant question appended.
    """
    inference_client = client if client is not None else HFInferenceClient()
    system = get_phase1_prompt()
    session["messages"].append({"role": "user", "content": user_reply})
    session["reply_count"] += 1
    question = inference_client.ask_question(system, session["messages"])
    session["messages"].append({"role": "assistant", "content": question})
    return session


def complete_session(
    session: dict,
    client: HFInferenceClient | None = None,
) -> dict:
    """Summarize the discovery conversation into a structured diagnosis.

    Calls the Phase 1 model with a JSON-output instruction appended to the
    conversation and returns the parsed diagnosis dict.

    Args:
        session: Completed session dict from start_session / continue_session.
        client: Optional inference client (used in tests to avoid real API calls).

    Returns:
        Diagnosis dict with keys: summary, root_causes, prioritized_issues, risk_flags.
    """
    inference_client = client if client is not None else HFInferenceClient()
    system = get_phase1_prompt()
    return inference_client.summarize_discovery(system, session["messages"])


def generate_suggestion(
    working_draft: str,
    session: dict,
    client: HFInferenceClient | None = None,
) -> str:
    """Generate a Phase 2 professional rewrite suggestion.

    Runs complete_session internally to get the diagnosis, then calls the
    Phase 2 model with the working draft and diagnosis as context.

    Args:
        working_draft: Current user-owned Working Draft text. Falls back to
            session["original"] when empty.
        session: Session dict from start_session / continue_session.
        client: Optional inference client (used in tests to avoid real API calls).

    Returns:
        The rewritten professional feedback as a plain string.
    """
    inference_client = client if client is not None else HFInferenceClient()
    diagnosis = complete_session(session, client=inference_client)
    system = get_phase2_prompt()
    base_text = working_draft.strip() or session["original"]
    return inference_client.generate_rewrite(system, base_text, diagnosis)

