# AI Feedback Workflow MVP Plan

## Objective
Build a Python-only MVP for a professional feedback workflow using Gradio, with local-first testing and Hugging Face deployment readiness.

## Core Workflow
1. Phase 1: Discovery
- Start with the user's initial issue statement and then move into an interactive,
  multi-turn back-and-forth.
- Use a 5-whys style guided intake to move from surface symptom to deeper cause.
- Model the assistant after an expert organizational psychologist: calm,
  fact-finding, emotionally regulating, and critically focused on better outcomes.
- Enforce strict safety and appropriateness checks before each model interaction.
- Require enough guided follow-up rounds before Phase 1 can be completed.
2. Phase 2: Rewrite
- Generate a professional rewrite only after the guided Phase 1 intake has been completed,
  summarized into a structured diagnosis, and explicitly confirmed by the user.

## Gate Model
1. Gate 0: Input Validity
- Input must be non-empty and meet minimum length.
2. Gate 0.5: Safety and Appropriateness
- Block workplace-inappropriate indecent content.
- Escalate potential criminal-offense concerns to authorities/compliance channels.
- Escalate self-harm sentiment to emergency/crisis support guidance.
3. Gate 1: Discovery Validity
- Discovery cannot complete until the minimum guided follow-up rounds are finished.
- The final discovery summary must include structured, actionable diagnosis fields.
4. Gate 2: Rewrite Validity
- Rewrite must be coherent and aligned to diagnosed issues.

## Non-Goals for MVP
- No data persistence.
- No authentication.
- No multi-user collaboration.
- No file upload.

## Implementation Structure
- app.py: Gradio UI and phase control.
- config.py: environment-driven settings.
- feedback/safety.py: content screening and escalation decisions.
- feedback/llm.py: Hugging Face inference wrapper.
- feedback/processor.py: discovery and rewrite orchestration.
- tests/: unit tests for gate and workflow behavior.

## Deployment Target
- Hugging Face Spaces with Gradio SDK.
- Environment secrets managed through Spaces settings.

## ToDos:
- [x] Break out separate markdown files for the system prompts of the two agents
- [x] Fix UI positioning of text boxes
- Hookup AI model backend using huggingface to test out real user experience
- Clean up UI. 
    - Remove the Phase 1 Status box.
    - Make send response button orange or more vibrant