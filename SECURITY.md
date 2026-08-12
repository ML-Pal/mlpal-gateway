# Security Policy

## Reporting a Vulnerability

Please do **not** open a public issue for security vulnerabilities.

Email **contact@mlpal.ai** with a description of the issue, steps to reproduce,
and any relevant logs or proof-of-concept. We aim to acknowledge reports within
3 business days and will keep you updated on remediation.

## Scope

This repository is the self-hostable MLPal Gateway. When reporting, please note:

- Never include real API keys, credentials, or customer data in a report.
- The gateway is designed to run with an operator's own provider keys and an
  admin-scoped API key; treat those as secrets in your own deployment.

## Handling secrets in this repo

This is an open-source repository. Do not commit `.env` files, provider API
keys, or any credential. The seed flow prints a one-time bootstrap admin key to
the container logs — rotate it for anything beyond local use.
