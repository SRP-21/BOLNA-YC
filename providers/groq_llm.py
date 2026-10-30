"""
Groq LLM provider (OpenAI-compatible).
Supports tool calling with retry on invalid args.
Implements fallback chain: planner model -> fallback model.
"""
import json
import logging
import asyncio
from typing import Optional
from openai import AsyncOpenAI, RateLimitError
from providers.base import LLMProvider
from providers.usage import usage
from config import settings

logger = logging.getLogger(__name__)


class GroqLLM(LLMProvider):
    def __init__(self, retry_delay: float = 2.0):
        self.client = AsyncOpenAI(
            api_key=settings.groq_api_key or "gsk_dummy_placeholder",
            base_url=settings.groq_base_url,
        )
        self.primary_model = settings.llm_planner_model
        self.fallback_model = settings.llm_planner_fallback
        self.classifier_model = settings.llm_classifier_model
        self._active_model = self.primary_model
        self._fallback_reason = None
        self.retry_delay = retry_delay

    @property
    def active_model(self) -> str:
        return self._active_model

    @property
    def fallback_reason(self) -> Optional[str]:
        return self._fallback_reason

    async def chat(
        self, messages: list[dict], tools: Optional[list[dict]] = None,
        model_override: Optional[str] = None
    ) -> dict:
        if not usage.check_limit("groq_llm"):
            raise RuntimeError("Daily LLM token limit reached")

        model = model_override or self.primary_model
        models_to_try = [model]
        if model == self.primary_model:
            models_to_try.append(self.fallback_model)

        last_error = None
        for i, m in enumerate(models_to_try):
            try:
                result = await self._call_with_retry(m, messages, tools)
                if i > 0:
                    self._active_model = m
                    self._fallback_reason = f"Fell back from {models_to_try[0]}: {last_error}"
                    logger.warning(f"Using fallback model {m}: {self._fallback_reason}")
                else:
                    self._active_model = m
                    self._fallback_reason = None
                return result
            except RateLimitError as e:
                last_error = str(e)
                logger.warning(f"Rate limited on {m}: {e}")
                if i < len(models_to_try) - 1 and self.retry_delay > 0:
                    await asyncio.sleep(self.retry_delay)
                continue
            except Exception as e:
                last_error = str(e)
                logger.error(f"LLM error on {m}: {e}")
                if i < len(models_to_try) - 1:
                    continue
                raise

        raise RuntimeError(f"All LLM models failed. Last error: {last_error}")

    async def _call_with_retry(
        self, model: str, messages: list[dict],
        tools: Optional[list[dict]], max_retries: int = 1
    ) -> dict:
        """Call with one retry on invalid tool output (pydantic validation failure)."""
        for attempt in range(max_retries + 1):
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = await self.client.chat.completions.create(**kwargs)

            # Track token usage
            if getattr(response, "usage", None):
                usage.increment(
                    "groq_llm",
                    tokens=response.usage.total_tokens
                )

            choice = response.choices[0]
            result = {
                "content": choice.message.content,
                "tool_calls": None,
                "finish_reason": choice.finish_reason,
                "model": model,
            }

            if choice.message.tool_calls:
                result["tool_calls"] = []
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        if attempt < max_retries:
                            logger.warning(
                                f"Invalid tool args from {model}, retrying: "
                                f"{tc.function.arguments[:200]}"
                            )
                            messages = messages + [{
                                "role": "user",
                                "content": "Your last tool call had invalid JSON arguments. Please try again with valid JSON."
                            }]
                            break
                        args = {}
                    result["tool_calls"].append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })
                else:
                    return result
                continue

            return result

        raise RuntimeError(f"Failed to get valid response from {model} after retries")

    async def classify(self, messages: list[dict]) -> dict:
        """Use the cheap classifier model for simple tasks like outcome parsing."""
        return await self.chat(messages, model_override=self.classifier_model)
