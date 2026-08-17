"""Simulated MCP server: typed read tools and approval-gated demo actions.

Added in 1.6.1. Without this file `lpr_cpe_demo.mcp_server` was an implicit
namespace package (PEP 420). That resolved correctly in practice, but namespace
packages are searched across every sys.path entry rather than bound to one
directory, which makes import behaviour depend on path ordering. Every sibling
subpackage declares itself explicitly, so this one now does too.
"""
