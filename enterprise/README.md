# Enterprise

This directory holds MLPal's **commercial** add-ons. It is **not** covered by the
Apache-2.0 license that governs the rest of this repository — see
[`LICENSE`](./LICENSE).

The open-source gateway is fully functional on its own. Enterprise features plug
in through the same **seams** the core already defines (`src/.../seams/`,
`src/.../api/mounting.py`) — the composition root selects a managed
implementation when one is present, and falls back to the open-source default
otherwise. `core` never imports from `enterprise/`.

Planned/managed capabilities that live here (or in the managed deployment):

- Managed **billing / wallet** backend (`MLPAL_BILLING_BACKEND=managed`)
- Managed **auth** (Cognito JWT) backend (`MLPAL_AUTH_BACKEND=managed`)
- Bedrock-mantle Anthropic passthrough and other managed integrations
- SSO, audit, and advanced governance

Interested in the managed offering or a commercial license? **sales@mlpal.ai**.
