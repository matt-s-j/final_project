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


def handle_start_discovery(user_text: str):
    """Start the guided discovery flow and seed the Working Draft.

    Args:
        user_text: Initial issue statement from the user.

    Returns:
        Component updates for status, chatbot, session state, controls, and
        right-side panel content.
    """
    result = start_discovery_session(user_text)

    if not result.ok:
        return (
            result.user_message,
            [],
            None,
            gr.update(interactive=False),
            gr.update(interactive=False),
            "",
            "",
            "",
            None,
            "",
        )

    assert result.session is not None
    return (
        result.user_message,
        _format_chat_messages(result.session),
        result.session.model_dump(),
        gr.update(interactive=True),
        gr.update(interactive=False),
        user_text,
        "",
        "",
        None,
        "",
    )


def handle_continue_discovery(
    user_reply: str,
    session_state: dict | None,
    working_draft: str,
):
    """Continue chat and refresh composer outputs in parallel after threshold.

    Args:
        user_reply: Latest user answer to the assistant.
        session_state: Serialized discovery session from Gradio state.
        working_draft: Current user-edited Working Draft text.

    Returns:
        Component updates for status, chat, session, buttons, response box,
        composer suggestion, discovery summary, and serialized discovery state.
    """
    session = DiscoverySession(**session_state) if session_state else None
    result = continue_discovery_session(session, user_reply)
    updated_session = result.session if result.session is not None else session
    can_complete = (
        updated_session is not None
        and updated_session.user_reply_count >= updated_session.min_rounds_required
    )
    composer_suggestion, discovery_markdown, discovery_state = _composer_outputs(
        updated_session,
        working_draft,
    )
    return (
        result.user_message,
        _format_chat_messages(updated_session),
        updated_session.model_dump() if updated_session is not None else None,
        gr.update(interactive=True),
        gr.update(interactive=can_complete),
        "",
        composer_suggestion,
        discovery_markdown,
        discovery_state,
    )


def handle_complete_discovery(session_state: dict | None, working_draft: str):
    """Manually complete discovery and refresh the composer suggestion.

    Args:
        session_state: Serialized discovery session from Gradio state.
        working_draft: Current user-edited Working Draft text.

    Returns:
        Component updates for status, summary, completion control, composer
        suggestion, and serialized discovery state.
    """
    session = DiscoverySession(**session_state) if session_state else None
    result = complete_discovery_session(session)
    if not result.ok or result.discovery is None:
        return result.user_message, "", gr.update(interactive=False), "", None

    composer_suggestion, discovery_markdown, discovery_state = _composer_outputs(
        session,
        working_draft,
    )
    return (
        result.user_message,
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
            user_text = gr.Textbox(
                label="Initial Issue Statement",
                lines=8,
                placeholder="Describe the workplace issue or feedback problem you want to unpack.",
            )
            start_discovery_btn = gr.Button("Start Guided Discovery", variant="primary")
            status_box = gr.Textbox(label="Phase 1 Status", interactive=False)
            discovery_chat = gr.Chatbot(label="Guided Discovery", height=420)
            discovery_md = gr.Markdown(label="Discovery Summary")

            with gr.Row():
                phase_one_reply = gr.Textbox(
                    label="Phase 1 Response",
                    lines=4,
                    placeholder="Answer the assistant's latest question here.",
                    scale=4,
                )
                with gr.Column(scale=1):
                    continue_discovery_btn = gr.Button("Send Response", interactive=False)
                    complete_discovery_btn = gr.Button("Complete Discovery", interactive=False)

        # Right 40%: user-owned draft plus AI-only suggestion pane.
        with gr.Column(scale=2):
            working_draft = gr.Textbox(
                label="Working Draft",
                lines=14,
                placeholder="Your initial issue statement will appear here after you start discovery.",
            )
            composer_suggestion = gr.Textbox(
                label="Composer Suggestion",
                lines=14,
                interactive=False,
                placeholder="Composer suggestions will appear here after the minimum fact-finding turns are complete.",
            )

    # --- Event Wiring ---
    start_discovery_btn.click(
        fn=handle_start_discovery,
        inputs=[user_text],
        outputs=[
            status_box,
            discovery_chat,
            discovery_session_state,
            continue_discovery_btn,
            complete_discovery_btn,
            working_draft,
            composer_suggestion,
            discovery_md,
            discovery_state,
            phase_one_reply,
        ],
    )

    continue_discovery_btn.click(
        fn=handle_continue_discovery,
        inputs=[phase_one_reply, discovery_session_state, working_draft],
        outputs=[
            status_box,
            discovery_chat,
            discovery_session_state,
            continue_discovery_btn,
            complete_discovery_btn,
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
            status_box,
            discovery_md,
            complete_discovery_btn,
            composer_suggestion,
            discovery_state,
        ],
    )


if __name__ == "__main__":
    demo.launch(share=True)
