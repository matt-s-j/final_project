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

from feedback.models import DiscoveryResult, DiscoverySession
from feedback.processor import (
    complete_discovery_session,
    continue_discovery_session,
    generate_composer_suggestion,
    start_discovery_session,
)


def _format_discovery(discovery: DiscoveryResult) -> str:
    """Render a DiscoveryResult as human-readable Markdown.

    Args:
        discovery: Completed discovery summary.

    Returns:
        Markdown with summary, root causes, prioritized issues, and risk flags.
    """
    causes = "\n".join(f"- {item}" for item in discovery.root_causes) or "- None"
    issues = "\n".join(f"- {item}" for item in discovery.prioritized_issues) or "- None"
    risks = "\n".join(f"- {item}" for item in discovery.risk_flags) or "- None"
    return (
        f"### Summary\n{discovery.summary}\n\n"
        f"### Root Causes\n{causes}\n\n"
        f"### Prioritized Issues\n{issues}\n\n"
        f"### Risk Flags\n{risks}"
    )


def _format_chat_messages(session: DiscoverySession | None) -> list[dict[str, str]]:
    """Convert session messages into Gradio Chatbot message dictionaries.

    Args:
        session: Discovery session containing ordered conversation messages.

    Returns:
        A list of message dictionaries with ``role`` and ``content`` keys.
    """
    if session is None:
        return []
    return [message.model_dump() for message in session.messages]


def _composer_outputs(
    session: DiscoverySession | None,
    working_draft: str,
) -> tuple[str, str, dict | None]:
    """Generate composer-side outputs when the threshold allows it.

    Args:
        session: Current discovery session.
        working_draft: User-owned Working Draft text.

    Returns:
        A tuple of:
          - composer suggestion text
          - discovery summary markdown
          - serialized discovery state
    """
    if session is None or session.user_reply_count < session.min_rounds_required:
        return "", "", None

    composer_result = generate_composer_suggestion(working_draft, session)
    if not composer_result.ok or composer_result.discovery is None:
        return "", "", None

    return (
        composer_result.rewrite or "",
        _format_discovery(composer_result.discovery),
        composer_result.discovery.model_dump(),
    )


def handle_send_response(
    user_input: str,
    session_state: dict | None,
    working_draft: str,
):
    """Unified handler for both the initial complaint and every follow-up reply.

    When ``session_state`` is ``None`` this is the first submission, so it
    calls ``start_discovery_session`` and seeds the Working Draft.  On every
    subsequent call it delegates to ``continue_discovery_session``.

    Args:
        user_input: Text the user just typed — either the opening complaint or
            an answer to the latest assistant question.
        session_state: Serialized ``DiscoverySession`` from Gradio state, or
            ``None`` before discovery has started.
        working_draft: Current user-owned Working Draft text (used by the
            composer after the minimum-rounds threshold is reached).

    Returns:
        Component updates for chatbot, session state, send button, complete
        button, working draft, input box, composer suggestion, discovery
        summary markdown, and serialized discovery state.
    """
    # --- First submission: start a new discovery session ---
    if session_state is None:
        result = start_discovery_session(user_input)
        if not result.ok:
            # Show the error as an assistant message so the user sees feedback
            # without a dedicated status box.
            error_chat = [{"role": "assistant", "content": f"⚠️ {result.user_message}"}]
            return (
                error_chat,
                None,
                gr.update(interactive=True),
                gr.update(interactive=False),
                gr.update(),
                gr.update(),
                "",
                "",
                None,
            )
        assert result.session is not None
        return (
            _format_chat_messages(result.session),
            result.session.model_dump(),
            gr.update(interactive=True),
            gr.update(interactive=False),
            user_input,   # seed the Working Draft with the opening complaint
            "",           # clear the input box
            "",
            "",
            None,
        )

    # --- Subsequent submissions: continue the existing session ---
    session = DiscoverySession(**session_state)
    result = continue_discovery_session(session, user_input)
    updated_session = result.session if result.session is not None else session
    can_complete = (
        updated_session is not None
        and updated_session.user_reply_count >= updated_session.min_rounds_required
    )
    composer_suggestion, discovery_markdown, new_discovery_state = _composer_outputs(
        updated_session,
        working_draft,
    )
    return (
        _format_chat_messages(updated_session),
        updated_session.model_dump() if updated_session is not None else None,
        gr.update(interactive=True),
        gr.update(interactive=can_complete),
        gr.update(),     # leave Working Draft untouched — it is user-owned
        "",              # clear the input box after each send
        composer_suggestion,
        discovery_markdown,
        new_discovery_state,
    )


def handle_complete_discovery(session_state: dict | None, working_draft: str):
    """Manually complete discovery and refresh the composer suggestion.

    Args:
        session_state: Serialized discovery session from Gradio state.
        working_draft: Current user-edited Working Draft text.

    Returns:
        Component updates for summary, completion control, composer suggestion,
        and serialized discovery state.
    """
    session = DiscoverySession(**session_state) if session_state else None
    result = complete_discovery_session(session)
    if not result.ok or result.discovery is None:
        return "", gr.update(interactive=False), "", None

    composer_suggestion, discovery_markdown, discovery_state = _composer_outputs(
        session,
        working_draft,
    )
    return (
        discovery_markdown or _format_discovery(result.discovery),
        gr.update(interactive=True),
        composer_suggestion,
        discovery_state or result.discovery.model_dump(),
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
    discovery_state = gr.State(value=None)

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
            discovery_state,
        ],
    )

    complete_discovery_btn.click(
        fn=handle_complete_discovery,
        inputs=[discovery_session_state, working_draft],
        outputs=[
            discovery_md,
            complete_discovery_btn,
            composer_suggestion,
            discovery_state,
        ],
    )


if __name__ == "__main__":
    demo.launch(theme=gr.themes.Glass())
