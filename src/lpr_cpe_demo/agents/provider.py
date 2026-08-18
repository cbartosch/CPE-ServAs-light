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
class NullProvider:
    """Provides nothing. Every call raises, so every agent falls back.

    This is what a missing API key gives you, and the name says so. It was
    previously called `NullProvider`, which was actively misleading: `fake`
    suggests a stand-in that produces plausible output, and v1.2's
    `llm/service.py` has a fake that does exactly that. This one produces
    nothing. With no key the system runs entirely on the deterministic rules, and
    a name implying otherwise hides that.
    """

    name: str = "null"
    reason: str = "no API key configured, so no model is reachable"

    def complete(self, *, system: str, user: str,
                 max_tokens: int = 1200) -> Completion:
        raise ProviderError(self.reason)


@dataclass(slots=True)
class ScriptedProvider:
    """Returns a canned response. For tests and offline demonstrations.

    `responder` is REQUIRED. A scripted provider with no script is a
    `NullProvider`, and conflating the two is what made the old `NullProvider`
    confusing.
    """

    responder: Callable[[str], str]
    name: str = "scripted"

    def complete(self, *, system: str, user: str,
                 max_tokens: int = 1200) -> Completion:
        return Completion(self.responder(user), "scripted", 0, 1)


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
    """Real provider when a key is present, otherwise a `NullProvider`.

    A missing key degrades to the deterministic rules rather than a stack trace,
    which is also what happens in a container that cannot reach the internet. It
    does NOT degrade to a plausible-looking model answer: nothing invents a
    decision on the operator's behalf.
    """
    source = env if env is not None else os.environ
    key = source.get("ANTHROPIC_API_KEY", "").strip()
    # Two switches existed and disagreed. MODEL_PROVIDER already governed the RCA
    # assistant, and LLM_PROVIDER governed the agents, so MODEL_PROVIDER=fake with
    # a key present sent the assistant to the fake and the agents live. Either
    # switch set to fake now forces the fake, which is the safe direction: a demo
    # that meant to stay offline stays offline.
    forced_fake = "fake" in {
        source.get("LLM_PROVIDER", "").strip().lower(),
        source.get("MODEL_PROVIDER", "").strip().lower()}
    if not key:
        return fallback or NullProvider(
            reason="no ANTHROPIC_API_KEY is set, so no model is reachable")
    if forced_fake:
        return fallback or NullProvider(
            reason="MODEL_PROVIDER or LLM_PROVIDER is set to fake, so the model "
                   "is deliberately bypassed")
    return AnthropicProvider(
        api_key=key,
        endpoint=source.get("ANTHROPIC_ENDPOINT", DEFAULT_ENDPOINT),
        model=source.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        timeout=float(source.get("LLM_TIMEOUT", 20.0)),
        max_retries=int(source.get("LLM_MAX_RETRIES", 2)))
