"""Model provider: real Anthropic API calls, with a deterministic fake fallback.

Uses `urllib` rather than the `anthropic` package, for the same reason the OSRM
client does: it stays standard library, so the seam is testable against a canned
response in an environment that has no network and cannot install anything.

`opener` is injectable, which is how every failure path here is exercised: HTTP
error, timeout, malformed JSON, a response that is valid JSON but not the schema,
and a refusal. A provider seam that has only been tested on the happy path is a
provider seam that has not been tested.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

DEFAULT_ENDPOINT = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_VERSION = "2023-06-01"


class ProviderError(RuntimeError):
    """The provider could not return a usable response."""


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    source: str            # "anthropic" | "fake"
    latency_ms: int
    attempts: int


class Provider(Protocol):
    name: str

    def complete(self, *, system: str, user: str, max_tokens: int = 1200) -> Completion: ...


@dataclass(slots=True)
class FakeProvider:
    """Returns a scripted response. The fallback, and the default.

    `responder` receives the user prompt and returns the JSON string the agent
    would have received, so a test can drive any branch without a network.
    """

    responder: Callable[[str], str] | None = None
    name: str = "fake"

    def complete(self, *, system: str, user: str,
                 max_tokens: int = 1200) -> Completion:
        if self.responder is None:
            raise ProviderError("fake provider has no responder configured")
        return Completion(self.responder(user), "fake", 0, 1)


@dataclass(slots=True)
class AnthropicProvider:
    """Real API calls.

    Retries only on transport and 5xx, never on a 4xx: a malformed request or a
    bad key will fail identically on every attempt, and retrying it wastes the
    latency budget of an incident that is already open.
    """

    api_key: str
    endpoint: str = DEFAULT_ENDPOINT
    model: str = DEFAULT_MODEL
    version: str = DEFAULT_VERSION
    timeout: float = 20.0
    max_retries: int = 2
    opener: Any | None = None
    name: str = "anthropic"
    calls: int = field(default=0, repr=False)

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint, data=body, method="POST",
            headers={"content-type": "application/json",
                     "x-api-key": self.api_key,
                     "anthropic-version": self.version})
        opener = self.opener or urllib.request.urlopen
        with opener(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def complete(self, *, system: str, user: str,
                 max_tokens: int = 1200) -> Completion:
        payload = {"model": self.model, "max_tokens": max_tokens,
                   "system": system,
                   "messages": [{"role": "user", "content": user}]}
        started = time.monotonic()
        last: Exception | None = None

        for attempt in range(1, self.max_retries + 2):
            self.calls += 1
            try:
                data = self._request(payload)
            except urllib.error.HTTPError as exc:
                last = exc
                if 400 <= exc.code < 500:
                    raise ProviderError(
                        f"provider rejected the request with {exc.code}; not "
                        f"retrying because it will fail identically") from exc
                if attempt > self.max_retries:
                    break
                continue
            except (urllib.error.URLError, TimeoutError, OSError,
                    json.JSONDecodeError) as exc:
                last = exc
                if attempt > self.max_retries:
                    break
                continue

            text = _extract_text(data)
            if not text:
                last = ProviderError("provider returned no text block")
                if attempt > self.max_retries:
                    break
                continue
            return Completion(text, "anthropic",
                              int((time.monotonic() - started) * 1000), attempt)

        raise ProviderError(f"provider failed after {self.max_retries + 1} "
                            f"attempt(s): {last}")


def _extract_text(data: dict[str, Any]) -> str:
    """Join every text block. Never index content[0]: a response may lead with a
    thinking or tool_use block, and position is not a contract."""
    blocks = data.get("content") or []
    return "\n".join(b.get("text", "") for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text").strip()


def provider_from_env(env: dict[str, str] | None = None,
                      fallback: Provider | None = None) -> Provider:
    """Real provider when a key is present, otherwise the fake.

    Default is the fake. A missing key must degrade to a working demo rather than
    a stack trace, which is also what happens in a container that cannot reach the
    internet.
    """
    source = env if env is not None else os.environ
    key = source.get("ANTHROPIC_API_KEY", "").strip()
    if not key or source.get("LLM_PROVIDER", "").strip().lower() == "fake":
        return fallback or FakeProvider()
    return AnthropicProvider(
        api_key=key,
        endpoint=source.get("ANTHROPIC_ENDPOINT", DEFAULT_ENDPOINT),
        model=source.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        timeout=float(source.get("LLM_TIMEOUT", 20.0)),
        max_retries=int(source.get("LLM_MAX_RETRIES", 2)))
