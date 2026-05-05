"""Gradio application entry point.

The interface is desktop-first and split into two major regions:
    - Left 60%: guided chatbot conversation and discovery controls.
    - Right 40%: a vertical split between the user-owned Working Draft and a
        separate Composer Suggestion pane.

The Working Draft is always labeled the same way and remains entirely user-owned.
The first write into that pane is the user's initial issue statement. After the
minimum fact-finding threshold is reached, each user reply triggers two parallel
updates: the chatbot responds on the left and the Composer Suggestion refreshes on
the right. The Working Draft is never changed automatically.
"""

from __future__ import annotations

import gradio as gr

from config import settings
from feedback.processor import (
    complete_session,
    continue_session,
    generate_suggestion,
    start_session,
)


def _format_discovery(discovery: dict) -> str:
    """Render a diagnosis dict as human-readable Markdown.

    Args:
        discovery: Diagnosis dict with keys: summary, root_causes, prioritized_issues, risk_flags.

    Returns:
        Markdown string with summary, root causes, prioritized issues, and risk flags.
    """
    causes = "\n".join(f"- {item}" for item in discovery.get("root_causes", [])) or "- None"
    issues = "\n".join(f"- {item}" for item in discovery.get("prioritized_issues", [])) or "- None"
    risks = "\n".join(f"- {item}" for item in discovery.get("risk_flags", [])) or "- None"
    return (
        f"### Summary\n{discovery.get('summary', '')}\n\n"
        f"### Root Causes\n{causes}\n\n"
        f"### Prioritized Issues\n{issues}\n\n"
        f"### Risk Flags\n{risks}"
    )


def _composer_outputs(
    session: dict | None,
    working_draft: str,
) -> tuple[str, str]:
    """Generate composer-side outputs once the minimum reply threshold is reached.

    Args:
        session: Current discovery session dict, or None if not started.
        working_draft: User-owned Working Draft text.

    Returns:
        A tuple of (composer suggestion text, discovery summary markdown).
    """
    # Only generate suggestions after the minimum fact-finding threshold.
    if session is None or session["reply_count"] < settings.discovery_min_rounds:
        return "", ""

    suggestion = generate_suggestion(working_draft, session)
    diagnosis = complete_session(session)
    return suggestion, _format_discovery(diagnosis)


def handle_send_response(
    user_input: str,
    session_state: dict | None,
    working_draft: str,
):
    """Unified handler for both the initial complaint and every follow-up reply.

    When ``session_state`` is ``None`` this is the first submission, so it
    calls ``start_session`` and seeds the Working Draft. On every subsequent
    call it delegates to ``continue_session``.

    Args:
        user_input: Text the user just typed — either the opening complaint or
            an answer to the latest assistant question.
        session_state: Session dict from Gradio state, or None before discovery starts.
        working_draft: Current user-owned Working Draft text (used by the
            composer after the minimum-rounds threshold is reached).

    Returns:
        Component updates for chatbot, session state, send button, complete
        button, working draft, input box, composer suggestion, and discovery summary.
    """
    # --- First submission: start a new discovery session ---
    if session_state is None:
        session = start_session(user_input)
        return (
            session["messages"],
            session,
            gr.update(interactive=True),
            gr.update(interactive=False),
            user_input,   # seed the Working Draft with the opening complaint
            "",           # clear the input box
            "",
            "",
        )

    # --- Subsequent submissions: continue the existing session ---
    session = continue_session(session_state, user_input)
    can_complete = session["reply_count"] >= settings.discovery_min_rounds
    composer_suggestion, discovery_markdown = _composer_outputs(session, working_draft)
    return (
        session["messages"],
        session,
        gr.update(interactive=True),
        gr.update(interactive=can_complete),
        gr.update(),     # leave Working Draft untouched — it is user-owned
        "",              # clear the input box after each send
        composer_suggestion,
        discovery_markdown,
    )


def handle_complete_discovery(session_state: dict | None, working_draft: str):
    """Manually complete discovery and refresh the composer suggestion.

    Args:
        session_state: Session dict from Gradio state.
        working_draft: Current user-edited Working Draft text.

    Returns:
        Component updates for summary markdown, completion button,
        and composer suggestion.
    """
    if session_state is None:
        return "", gr.update(interactive=False), ""

    diagnosis = complete_session(session_state)
    suggestion = generate_suggestion(working_draft, session_state)
    return (
        _format_discovery(diagnosis),
        gr.update(interactive=True),
        suggestion,
    )


# ---------------------------------------------------------------------------
# UI Layout
# ---------------------------------------------------------------------------
# Built for computer use. The left side is conversation-heavy and the right side
# preserves a strict separation between user-authored draft text and AI-generated
# suggestion text.

with gr.Blocks(title="AI Feedback Workflow MVP") as demo:
    gr.Markdown("## AI Feedback Workflow MVP")
    gr.Markdown(
        "Use the chatbot on the left to uncover the deeper issue. "
        "Your Working Draft stays fully user-owned, while Composer Suggestion "
        "shows AI-generated rewrite ideas only after the minimum fact-finding threshold is reached."
    )

    # Session state shared across interaction handlers.
    discovery_session_state = gr.State(value=None)

    with gr.Row(equal_height=False):
        # Left 60%: chat and discovery controls.
        with gr.Column(scale=3):
            discovery_chat = gr.Chatbot(label="Guided Discovery", height=420)
            discovery_md = gr.Markdown(label="Discovery Summary")

            with gr.Row():
                phase_one_reply = gr.Textbox(
                    label="Your message",
                    lines=4,
                    placeholder="Describe your workplace issue, or answer the assistant's latest question.",
                    scale=4,
                )
                with gr.Column(scale=1):
                    continue_discovery_btn = gr.Button("Send", variant="primary", interactive=True)
                    complete_discovery_btn = gr.Button("Complete Discovery", interactive=False)

        # Right 40%: AI suggestion on top, user-owned draft below.
        with gr.Column(scale=2):
            composer_suggestion = gr.Textbox(
                label="Composer Suggestion",
                lines=14,
                interactive=False,
                placeholder="Composer suggestions will appear here after the minimum fact-finding turns are complete.",
            )
            working_draft = gr.Textbox(
                label="Working Draft",
                lines=14,
                placeholder="Your initial issue statement will appear here after you start discovery.",
            )

    # --- Event Wiring ---
    continue_discovery_btn.click(
        fn=handle_send_response,
        inputs=[phase_one_reply, discovery_session_state, working_draft],
        outputs=[
            discovery_chat,
            discovery_session_state,
            continue_discovery_btn,
            complete_discovery_btn,
            working_draft,
            phase_one_reply,
            composer_suggestion,
            discovery_md,
        ],
    )

    complete_discovery_btn.click(
        fn=handle_complete_discovery,
        inputs=[discovery_session_state, working_draft],
        outputs=[
            discovery_md,
            complete_discovery_btn,
            composer_suggestion,
        ],
    )


if __name__ == "__main__":
    demo.launch(theme=gr.themes.Glass())

