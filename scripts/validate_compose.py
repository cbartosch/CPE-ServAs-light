from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

ROOT = Path(__file__).resolve().parents[1]
compose_path = ROOT / "docker-compose.yml"
text = compose_path.read_text(encoding="utf-8")


def assert_no_duplicate_keys(node: Node, path: str = "root") -> None:
    """Reject duplicate literal keys while allowing YAML merge keys (``<<``)."""
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key_node, value_node in node.value:
            if isinstance(key_node, ScalarNode) and key_node.value != "<<":
                marker = (key_node.tag, key_node.value)
                if marker in seen:
                    raise SystemExit(f"Duplicate YAML key {key_node.value!r} at {path}")
                seen.add(marker)
                child_path = f"{path}.{key_node.value}"
            else:
                child_path = path
            assert_no_duplicate_keys(value_node, child_path)
    elif isinstance(node, SequenceNode):
        for index, child in enumerate(node.value):
            assert_no_duplicate_keys(child, f"{path}[{index}]")


root_node = yaml.compose(text)
if root_node is None:
    raise SystemExit("docker-compose.yml is empty")
assert_no_duplicate_keys(root_node)
payload: dict[str, Any] = yaml.safe_load(text)
services = payload.get("services", {})
required = {"postgres", "mcp-sim", "api", "ui", "test"}
missing = required - set(services)
if missing:
    raise SystemExit(f"Missing services: {sorted(missing)}")
for name in ("postgres", "mcp-sim", "api", "ui"):
    if "healthcheck" not in services[name]:
        raise SystemExit(f"Service {name} has no healthcheck")
if services["api"].get("depends_on", {}).get("mcp-sim", {}).get("condition") != "service_healthy":
    raise SystemExit("API must wait for the MCP simulator healthcheck")
if services["ui"].get("depends_on", {}).get("api", {}).get("condition") != "service_healthy":
    raise SystemExit("UI must wait for the API healthcheck")
if services["mcp-sim"].get("volumes") != ["mcp-data:/app/data"]:
    raise SystemExit("MCP simulator must persist its effect store in mcp-data")

if services["api"].get("build", {}).get("dockerfile") != "docker/app.Dockerfile":
    raise SystemExit("API must use the app-specific Dockerfile")
if services["mcp-sim"].get("build", {}).get("dockerfile") != "docker/mcp.Dockerfile":
    raise SystemExit("MCP simulator must use the smaller MCP-specific Dockerfile")
for service_name in ("api", "mcp-sim", "ui", "test"):
    build_args = services[service_name].get("build", {}).get("args", {})
    if "PIP_INDEX_URL" not in build_args:
        raise SystemExit(f"{service_name} build must accept PIP_INDEX_URL")
print("docker-compose.yml structural validation: PASS")
