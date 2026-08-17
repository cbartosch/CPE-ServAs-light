from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TypedDict
import re


ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;]+)$")


def expected_pins(*files: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for filename in files:
        for raw in (ROOT / filename).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = PIN_RE.fullmatch(line)
            if match is None:
                raise SystemExit(f"Dependency is not exactly pinned in {filename}: {line}")
            result[match.group(1).lower().replace("_", "-")] = match.group(2)
    return result


def installed_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError as exc:
        raise SystemExit(f"Required package is not installed: {name}") from exc


print("Framework compatibility check")
for package, expected in expected_pins("requirements-app.txt", "requirements-dev.txt").items():
    actual = installed_version(package)
    print(f"- {package}: {actual} (expected {expected})")
    if actual != expected:
        raise SystemExit(f"Pinned-version mismatch for {package}: expected {expected}, got {actual}")

import streamlit as st
from langchain_anthropic import ChatAnthropic  # noqa: F401
from langchain_openai import ChatOpenAI  # noqa: F401
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver  # noqa: F401
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt  # noqa: F401
import mcp  # noqa: F401

for attribute in ("Page", "navigation", "fragment", "dialog", "dataframe"):
    if not hasattr(st, attribute):
        raise SystemExit(f"Streamlit is missing required API: st.{attribute}")


class SmokeState(TypedDict):
    count: int


def increment(state: SmokeState) -> SmokeState:
    return {"count": state["count"] + 1}


builder = StateGraph(SmokeState)
builder.add_node("increment", increment)
builder.add_edge(START, "increment")
builder.add_edge("increment", END)
graph = builder.compile(checkpointer=InMemorySaver())
result = graph.invoke(
    {"count": 0},
    config={"configurable": {"thread_id": "framework-smoke"}},
)
if result["count"] != 1:
    raise SystemExit("LangGraph smoke graph returned an unexpected result")
print("Framework compatibility check: PASS")
