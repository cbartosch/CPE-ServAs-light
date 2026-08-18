"""Decision agents.

The operator chose that agents decide and that policy and the gates are the only
guard, inverting what came before: the deterministic classifier used to decide and
the model could only lower confidence or force a gate.

The rules did not go away. Every `AgentDecision` carries the deterministic answer
as its baseline, so a disagreement still gates; as its fallback, so an unreachable
provider or an unparsable response cannot stall an incident; and as its floor, so
on an incident where the agent fails the outcome is exactly what it would have been
before.

Declared explicitly rather than left as a PEP 420 namespace package, which is the
gap `test_every_package_directory_has_an_init` was written for in v1.6.1 after
`mcp_server` was found missing one.
"""

from __future__ import annotations

__all__ = ["provider", "base", "decisions", "guards", "status"]
