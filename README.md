---
title: AI Feedback Workflow MVP
colorFrom: blue
colorTo: yellow
sdk: gradio
sdk_version: 5.29.1
app_file: app.py
pinned: false
---

# AI Feedback Workflow MVP

This MVP provides a two-phase professional feedback workflow:
1. Phase 1: Discovery (root-cause diagnosis) with mandatory safety gating.
2. Phase 2: Rewrite (professional draft generation), available only after successful discovery and user confirmation.

## Safety Gate Behavior
- Blocks indecent or workplace-inappropriate content.
- Redirects potential criminal-offense concerns to authorities/compliance channels.
- Redirects self-harm related inputs to emergency/crisis resources.

## Local Setup
1. Create and activate a virtual environment.
2. Install dependencies.
3. Copy `.env.example` to `.env` and set `HF_API_TOKEN` if you want live HF inference.
4. Run the app locally.

## Commands
Install dependencies:

pip install -r requirements.txt

Run tests:

pytest -q

Run app:

python app.py

## Notes
- If HF API credentials are missing or inference fails, the app falls back to deterministic local logic so local testing remains possible.
- No persistence is implemented in this MVP. Session state remains in memory only.

## Prompt Specifications
- Bot behavior is externalized into markdown files so prompt tuning does not require code edits.
- Phase 1 prompt spec: `feedback/prompts/phase1_organizational_psychologist.md`
- Phase 2 prompt spec: `feedback/prompts/phase2_professional_rewriter.md`
- Runtime prompt loading is handled by `feedback/prompts.py`.

### Editing Workflow
1. Update rules, templates, and few-shot examples in the two markdown files.
2. Keep section headers unchanged because the loader extracts prompt templates by heading name.
3. Run `pytest -q` after edits to confirm prompt rendering and workflow behavior.

### Required Section Headers
- Phase 1 file must include:
	- `## Guided Turn Prompt Template`
	- `## Discovery Summary Prompt Template`
	- `## Fallback Questions`
- Phase 2 file must include:
	- `## Rewrite Prompt Template`
