"""Application configuration.

All settings are read from environment variables at startup so the same
codebase can run locally (using a .env file) and on Hugging Face Spaces
(using the Spaces Secrets panel) without any code changes.

Copy .env.example to .env and fill in values before running locally.
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv


# Load environment variables from .env (if present). This is a no-op when
# the variables are already set in the process environment (e.g. on HF Spaces).
load_dotenv()


def _resolve_prompts_dir() -> str:
    """Resolve prompt directory to an absolute path.

    Returns:
        Absolute path to the prompt directory, honoring PROMPTS_DIR when set.
    """
    project_root = Path(__file__).resolve().parent
    configured_value = os.getenv("PROMPTS_DIR", "feedback/prompts")
    configured_path = Path(configured_value).expanduser()
    if not configured_path.is_absolute():
        configured_path = project_root / configured_path
    return str(configured_path.resolve())


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings resolved once at import time.

    Attributes:
        hf_api_token: Bearer token for the Hugging Face Inference API.
        hf_model_discovery: Model ID used for the Phase 1 discovery call.
        hf_model_rewrite: Model ID used for the Phase 2 rewrite call.
        hf_timeout_seconds: HTTP request timeout applied to every inference call.
        min_input_length: Minimum character count required before processing begins (Gate 0).
        discovery_min_rounds: Minimum number of guided follow-up answers required
            before Phase 1 can be completed and summarized.
        prompts_dir: Filesystem path for external markdown prompt specifications.
    """

    # Authentication token for the HF Inference API. Required for live inference.
    hf_api_token: str = os.getenv("HF_API_TOKEN", "")

    # Model used in the discovery phase. Can be swapped via env var for A/B testing.
    hf_model_discovery: str = os.getenv(
        "HF_MODEL_DISCOVERY", "meta-llama/Llama-3.1-8B-Instruct"
    )

    # Model used in the rewrite phase. Can differ from the discovery model.
    hf_model_rewrite: str = os.getenv(
        "HF_MODEL_REWRITE", "meta-llama/Llama-3.1-8B-Instruct"
    )

    # Seconds to wait for a response before raising a timeout error.
    hf_timeout_seconds: int = int(os.getenv("HF_TIMEOUT_SECONDS", "25"))

    # Inputs shorter than this are rejected at Gate 0 before any API call.
    min_input_length: int = int(os.getenv("MIN_INPUT_LENGTH", "20"))

    # Minimum number of follow-up answers required for the guided 5-whys intake.
    discovery_min_rounds: int = int(os.getenv("DISCOVERY_MIN_ROUNDS", "3"))

    # Directory containing markdown prompt specs for both bots.
    prompts_dir: str = _resolve_prompts_dir()


# Module-level singleton — import `settings` directly rather than re-instantiating.
settings = Settings()
