"""Pluggable LLM provider registry.

Each provider implements the LLMProvider interface.
Register new providers with @register_llm_provider("name").

Providers can support vision (images) via call_with_images().
"""
from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Type

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    @abstractmethod
    def call(self, prompt: str) -> str:
        """Send text prompt to LLM and return the raw response text."""
        ...

    def supports_vision(self) -> bool:
        """Whether this provider supports image inputs."""
        return False

    def call_with_images(self, prompt: str, image_paths: List[str]) -> str:
        """Send prompt with images to a vision-capable LLM.

        Override in providers that support vision.
        Default falls back to text-only call.
        """
        return self.call(prompt)


# ── Registry ──────────────────────────────────────────────────────────────

_PROVIDER_REGISTRY: Dict[str, Type[LLMProvider]] = {}


def register_llm_provider(name: str):
    """Decorator to register an LLM provider."""
    def wrapper(cls: Type[LLMProvider]) -> Type[LLMProvider]:
        _PROVIDER_REGISTRY[name] = cls
        return cls
    return wrapper


def get_llm_provider(name: str, api_key: str, model: str, base_url: str = "") -> LLMProvider:
    """Get an LLM provider instance by name."""
    cls = _PROVIDER_REGISTRY.get(name)
    if not cls:
        available = ", ".join(_PROVIDER_REGISTRY.keys())
        raise ValueError(f"Unknown LLM provider: '{name}'. Available: {available}")
    return cls(api_key=api_key, model=model, base_url=base_url)


def list_llm_providers() -> list:
    return list(_PROVIDER_REGISTRY.keys())


def _encode_image(path: str) -> str:
    """Read image file and return base64 string."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _image_media_type(path: str) -> str:
    """Guess media type from file extension."""
    ext = path.rsplit(".", 1)[-1].lower()
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "tiff": "image/tiff",
        "tif": "image/tiff", "bmp": "image/bmp",
        "webp": "image/webp", "gif": "image/gif",
    }.get(ext, "image/png")


# ── Built-in providers ────────────────────────────────────────────────────


@register_llm_provider("openai")
class OpenAIProvider(LLMProvider):
    """OpenAI and any OpenAI-compatible API (Azure, Ollama, vLLM, etc.)."""

    def call(self, prompt: str) -> str:
        from openai import OpenAI

        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url

        client = OpenAI(**kwargs)
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content
        if not text:
            raise RuntimeError("LLM returned empty response")
        return text.strip()

    def supports_vision(self) -> bool:
        # GPT-4o, GPT-4-turbo, GPT-4o-mini all support vision
        return True

    def call_with_images(self, prompt: str, image_paths: List[str]) -> str:
        from openai import OpenAI

        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url

        client = OpenAI(**kwargs)

        content = [{"type": "text", "text": prompt}]
        for path in image_paths:
            b64 = _encode_image(path)
            media = _image_media_type(path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media};base64,{b64}", "detail": "high"},
            })

        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=4096,
            temperature=0,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content
        if not text:
            raise RuntimeError("LLM returned empty response for image input")
        return text.strip()


@register_llm_provider("anthropic")
class AnthropicProvider(LLMProvider):
    """Anthropic Claude API."""

    def call(self, prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    def supports_vision(self) -> bool:
        return True

    def call_with_images(self, prompt: str, image_paths: List[str]) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        content = []
        for path in image_paths:
            b64 = _encode_image(path)
            media = _image_media_type(path)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": b64},
            })
        content.append({"type": "text", "text": prompt})

        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text.strip()


@register_llm_provider("google")
class GoogleProvider(LLMProvider):
    """Google Gemini API (OpenAI-compatible endpoint)."""

    def call(self, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url or "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        response = client.chat.completions.create(
            model=self.model or "gemini-2.0-flash",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0,
        )
        return response.choices[0].message.content.strip()

    def supports_vision(self) -> bool:
        return True

    def call_with_images(self, prompt: str, image_paths: List[str]) -> str:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url or "https://generativelanguage.googleapis.com/v1beta/openai/",
        )

        content = [{"type": "text", "text": prompt}]
        for path in image_paths:
            b64 = _encode_image(path)
            media = _image_media_type(path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media};base64,{b64}"},
            })

        response = client.chat.completions.create(
            model=self.model or "gemini-2.0-flash",
            messages=[{"role": "user", "content": content}],
            max_tokens=4096,
            temperature=0,
        )
        return response.choices[0].message.content.strip()


@register_llm_provider("ollama")
class OllamaProvider(LLMProvider):
    """Local Ollama server (OpenAI-compatible)."""

    def call(self, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key or "ollama",
            base_url=self.base_url or "http://localhost:11434/v1",
        )
        response = client.chat.completions.create(
            model=self.model or "llama3",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0,
        )
        return response.choices[0].message.content.strip()
