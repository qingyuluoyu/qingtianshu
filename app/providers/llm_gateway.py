from __future__ import annotations

from typing import Any

import requests

from app.config import Settings


class LLMGatewayError(RuntimeError):
    """Raised when the OpenAI-compatible research gateway fails."""


class LLMGatewayClient:
    """Minimal OpenAI-compatible chat client for TokenDance / Anthropic-style gateways."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_gateway_enabled and self.settings.llm_gateway_api_key)

    def complete(
        self,
        *,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_seconds: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if not self.enabled:
            raise LLMGatewayError("LLM gateway is not enabled or missing API key")

        base = self.settings.llm_gateway_base_url.rstrip("/")
        # Claude Code commonly receives the gateway root while this client uses
        # the OpenAI-compatible chat endpoint exposed under /v1.
        if base.endswith("/gateway"):
            base = f"{base}/v1"
        url = f"{base}/chat/completions"
        selected_model = (model or self.settings.llm_gateway_model).strip()
        payload = {
            "model": selected_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是清数智算金融研究助手。只能基于用户给出的证据与技能约束作答；"
                        "不得编造价格、目标价、买卖指令或胜率；区分事实、推断、缺口与边界；"
                        "使用简洁中文。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": int(max_tokens or self.settings.llm_gateway_max_tokens),
        }
        if "deepseek" in selected_model.casefold():
            payload["thinking"] = {
                "type": (
                    "enabled"
                    if self.settings.llm_gateway_thinking_enabled
                    else "disabled"
                )
            }
        headers = {
            "Authorization": f"Bearer {self.settings.llm_gateway_api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout_seconds or self.settings.llm_gateway_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise LLMGatewayError(f"gateway request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:400]
            raise LLMGatewayError(f"gateway HTTP {response.status_code}: {detail}")

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMGatewayError("gateway returned non-JSON body") from exc

        answer = self._extract_answer(data)
        if not answer.strip():
            choices = data.get("choices") or []
            first = choices[0] if choices and isinstance(choices[0], dict) else {}
            finish_reason = first.get("finish_reason")
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            if finish_reason == "length" and message.get("reasoning_content"):
                raise LLMGatewayError(
                    "gateway reasoning exhausted max_tokens before the final answer"
                )
            raise LLMGatewayError("gateway returned empty assistant content")

        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        normalized = {
            "provider": "llm_gateway",
            "model": selected_model,
            "gateway_base_url": base,
            "raw_usage": usage,
            "response_id": data.get("id"),
        }
        return answer.strip(), normalized

    @staticmethod
    def _extract_answer(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
            joined = "".join(parts).strip()
            if joined:
                return joined
        return str(first.get("text") or "").strip()
