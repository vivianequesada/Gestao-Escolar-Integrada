---
name: Python Gmail connector
description: Using a connected Gmail mailbox from a Python Streamlit app in this workspace.
---

The documented Python `replit-connectors` package was unavailable in this workspace's Python package registry; the installed `@replit/connectors-sdk` JavaScript package can provide Gmail access from application code.

**Why:** `uv add replit-connectors` failed package resolution, while the Replit JavaScript SDK was already installed and exposes the connector proxy.

**How to apply:** Use the JavaScript connector SDK from app-side code when a Python app needs Gmail. Pass only the message payload to the helper and do not handle OAuth tokens directly or call the connector from the CodeExecution sandbox.