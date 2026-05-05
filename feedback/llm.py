"""Hugging Face Inference API client.

Thin wrapper around InferenceClient.chat_completion. Three methods, no fallbacks.
Errors propagate naturally to the caller.
"""

import json

from huggingface_hub import InferenceClient

from config import settings


class HFInferenceClient:
    """Client for Hugging Face Inference API.

    Args:
        token: HF API bearer token. Defaults to settings.hf_api_token.
        timeout_seconds: HTTP timeout in seconds. Defaults to settings.hf_timeout_seconds.
    """

    def __init__(self, token: str | None = None, timeout_seconds: int | None = None) -> None:
        """Initialize the inference client.

        Args:
            token: HF API bearer token, defaults to settings.hf_api_token.
            timeout_seconds: HTTP timeout, defaults to settings.hf_timeout_seconds.
        """
        self._token = token if token is not None else settings.hf_api_token
        self._timeout = timeout_seconds if timeout_seconds is not None else settings.hf_timeout_seconds
        self._client = InferenceClient(
            token=self._token,
            timeout=self._timeout,
        )

    def ask_question(self, system_prompt: str, messages: list[dict]) -> str:
        """Ask the next guided discovery question given the conversation so far.

        Args:
            system_prompt: Full Phase 1 system prompt text.
            messages: Conversation history as a list of {"role", "content"} dicts.

        Returns:
            The assistant's next follow-up question as a plain string.
        """
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = self._client.chat_completion(
            messages=full_messages,
            model=settings.hf_model_discovery,
            max_tokens=300,
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()

    def summarize_discovery(self, system_prompt: str, messages: list[dict]) -> dict:
        """Summarize the discovery conversation into a structured diagnosis dict.

        Appends a final instruction to return strict JSON before sending.

        Args:
            system_prompt: Full Phase 1 system prompt text.
            messages: Conversation history as a list of {"role", "content"} dicts.

        Returns:
            Parsed dict with keys: summary, root_causes, prioritized_issues, risk_flags.
        """
        # Append explicit JSON instruction so the model returns the structured output.
        summary_instruction = (
            "Now summarize the discovery conversation as strict JSON only. "
            'Schema: {"summary": string, "root_causes": string[], "prioritized_issues": string[], "risk_flags": string[]}'
        )
        full_messages = (
            [{"role": "system", "content": system_prompt}]
            + messages
            + [{"role": "user", "content": summary_instruction}]
        )
        response = self._client.chat_completion(
            messages=full_messages,
            model=settings.hf_model_discovery,
            max_tokens=600,
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if the model wraps the JSON.
        import re
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        return json.loads(match.group(0))

    def generate_rewrite(self, system_prompt: str, original_text: str, diagnosis: dict) -> str:
        """Generate a professional SBI rewrite from the original text and diagnosis.

        Args:
            system_prompt: Full Phase 2 system prompt text.
            original_text: The user's original feedback statement.
            diagnosis: Structured diagnosis dict from summarize_discovery.

        Returns:
            The rewritten feedback as a plain string.
        """
        user_content = (
            f"Original feedback:\n{original_text}\n\n"
            f"Diagnosis:\n{json.dumps(diagnosis, indent=2)}"
        )
        response = self._client.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            model=settings.hf_model_rewrite,
            max_tokens=400,
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()

