"""state_canon — a canon layer for agents, exposed over MCP.

Core abstraction (see INTERFACE.md):
  StateProvider   — read-only interface over YOUR canonical state store
  Reconciler      — model≡reality: declared vs observed → typed drift
  DigestAssembler — the compact onboard digest (front-load path)
  server          — minimal MCP stdio server (lazy query path)

Stdlib only. No dependencies.
"""
__version__ = "0.9.1"
