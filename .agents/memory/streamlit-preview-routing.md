---
name: Streamlit preview routing
description: Replit artifact path routing requirements for Streamlit's browser connection.
---

For a Streamlit app behind a path-based Replit artifact, list `/_stcore/stream` explicitly in the artifact service's `paths` alongside `/`.

**Why:** The root HTTP route can return `200` while the browser stays on a loading skeleton if the proxy does not forward Streamlit's WebSocket upgrade.

**How to apply:** When the workflow is healthy but the preview never renders widgets, check the WebSocket handshake and artifact paths before changing Streamlit UI code.