"""Hugging Face Inference API client.

This module provides a thin wrapper around the HF Inference API using the
official huggingface_hub library. It normalizes errors so that the processor
layer can decide whether to fall back to local rules.
"""

from __future__ import annotations

import json
import re
from typing import Any

from huggingface_hub import InferenceClient

from config import settings


class LLMError(RuntimeError):
    """Raised when inference fails or returns invalid output.

    Callers should catch this and apply the appropriate fallback strategy
    rather than letting it propagate to the UI.
    """


class HFInferenceClient:
    """Client for Hugging Face Inference API using the official hub library.

    Wraps text generation calls (discovery and rewrite) with shared error
    handling and response parsing. Both calls use the same auth token but
    can target different model IDs.

    Args:
        token: HF API bearer token. Falls back to ``settings.hf_api_token``
            if not provided.
        timeout_seconds: HTTP timeout in seconds. Falls back to
            ``settings.hf_timeout_seconds`` if not provided.
    """

    def __init__(self, token: str | None = None, timeout_seconds: int | None = None) -> None:
        """Initialize the inference client.
        
        Args:
            token: HF API bearer token, defaults to settings.hf_api_token.
            timeout_seconds: HTTP timeout, defaults to settings.hf_timeout_seconds.
        """
        self._token = token if token is not None else settings.hf_api_token
        self._timeout = (
            timeout_seconds if timeout_seconds is not None else settings.hf_timeout_seconds
        )
        # Primary path: force the official HF Inference provider to avoid
        # provider auto-selection bugs and task/provider mismatches.
        self._client = InferenceClient(
            model=None,
            provider="hf-inference",
            token=self._token,
            timeout=self._timeout,
        )
        # Secondary path: auto provider selection can still be useful for
        # models exposed only through conversational APIs.
        self._fallback_client = InferenceClient(
            model=None,
            provider="auto",
            token=self._token,
            timeout=self._timeout,
        )

    def _call_model(self, model_id: str, prompt: str, max_tokens: int = 400) -> str:
        """Call the HF Inference API for text generation.

        Args:
            model_id: The HF model repository ID (e.g. ``mistralai/Mistral-7B-Instruct-v0.1``).
            prompt: The full prompt string to send.
            max_tokens: Maximum number of new tokens the model should generate.

        Returns:
            The raw generated text string from the model.

        Raises:
            LLMError: If the token is missing, the request fails, or response is invalid.
        """
        if not self._token:
            raise LLMError("Missing HF_API_TOKEN. Configure .env before model inference.")

        print(f"[DEBUG] HF request: model={model_id}, token_len={len(self._token) if self._token else 0}, timeout={self._timeout}s")
        
        try:
            response = self._client.text_generation(
                prompt,
                model=model_id,
                max_new_tokens=max_tokens,
                temperature=0.2,
                return_full_text=False,
            )
            text = str(response).strip()
            if not text:
                raise ValueError("Empty response from text_generation.")
            print(f"[DEBUG] HF response: text_generation ok, chars={len(text)}")
            return text
        except Exception as text_gen_error:
            print(
                "[DEBUG] HF text_generation exception: "
                f"{type(text_gen_error).__name__}: {text_gen_error}"
            )

            # Some providers/models expose only conversational APIs. Retry once
            # with chat_completion so we can still use those routes.
            try:
                completion = self._fallback_client.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    model=model_id,
                    max_tokens=max_tokens,
                    temperature=0.2,
                )
                message = completion.choices[0].message
                text = (message.content or "").strip()
                if not text:
                    raise ValueError("Empty response from chat_completion.")
                print(f"[DEBUG] HF response: chat_completion ok, chars={len(text)}")
                return text
            except Exception as chat_error:
                print(
                    "[DEBUG] HF chat_completion exception: "
                    f"{type(chat_error).__name__}: {chat_error}"
                )
                raise LLMError(
                    "HF inference failed on both text_generation and chat_completion: "
                    f"text_generation={type(text_gen_error).__name__}: {text_gen_error}; "
                    f"chat_completion={type(chat_error).__name__}: {chat_error}"
                ) from chat_error

    @staticmethod
    def extract_json(raw_text: str) -> dict[str, Any]:
        """Extract and parse the first JSON object found in ``raw_text``.

        LLMs often wrap JSON in prose or code fences; this method locates
        the first ``{...}`` block and parses it, ignoring surrounding text.

        Args:
            raw_text: Raw string output from the model.

        Returns:
            A parsed dictionary representing the JSON object.

        Raises:
            LLMError: If no JSON object is present or the JSON is malformed.
        """
        # Use DOTALL so '.' matches newlines inside multi-line JSON objects.
        match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
        if not match:
            raise LLMError("No JSON object found in discovery model output.")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError("Invalid JSON in discovery model output.") from exc

    def run_discovery(self, prompt: str) -> dict[str, Any]:
        """Run the Phase 1 discovery prompt and return a validated dict.

        Calls the discovery model and then extracts the expected JSON
        structure from the raw text response.

        Args:
            prompt: Fully-assembled discovery prompt string.

        Returns:
            A dictionary whose keys should match the DiscoveryResult schema.

        Raises:
            LLMError: Propagated from ``_call_model`` or ``extract_json``.
        """
        raw = self._call_model(settings.hf_model_discovery, prompt, max_tokens=500)
        return self.extract_json(raw)

    def run_guided_discovery_turn(self, prompt: str) -> str:
        """Run a Phase 1 guided follow-up turn and return the assistant's question.

        Args:
            prompt: Fully-assembled prompt containing the current conversation state.

        Returns:
            The assistant's next follow-up question as plain text.

        Raises:
            LLMError: Propagated from ``_call_model``.
        """
        return self._call_model(settings.hf_model_discovery, prompt, max_tokens=220).strip()

    def run_rewrite(self, prompt: str) -> str:
        """Run the Phase 2 rewrite prompt and return the generated text.

        Args:
            prompt: Fully-assembled rewrite prompt string, including the
                original feedback and the diagnosed priorities.

        Returns:
            The rewritten feedback string, stripped of leading/trailing whitespace.

        Raises:
            LLMError: Propagated from ``_call_model``.
        """
        return self._call_model(settings.hf_model_rewrite, prompt, max_tokens=350).strip()
