# Contributing to MLPal Gateway

Thanks for your interest! MLPal Gateway is early-stage and we welcome issues,
discussion, and PRs.

## Open-core boundary

- Everything **outside** `enterprise/` is Apache-2.0 and open to contributions.
- The **`enterprise/`** directory is commercial (see `enterprise/LICENSE`). PRs
  that add features there won't be accepted from outside contributors; propose
  them as an issue instead.

## Development

```bash
uv sync --all-extras
uv run python -m pytest tests/unit/ -v      # unit tests
uv run ruff check .                          # lint
docker compose up                            # full local box (gateway + console)
```

Console (admin UI):

```bash
cd console && npm install && npm test && npm run build
```

## Guidelines

- Keep the correct path the easy path; prefer clarity over cleverness.
- Add tests for new behavior and for any bug you fix — code isn't done without them.
- Never commit secrets. Never add a real provider key or `.env`.
- Keep `core` free of imports from `enterprise/` — the open-source build must
  stand alone.
- Conventional-ish commit messages are appreciated (`feat:`, `fix:`, `docs:`…).

## DCO

By contributing, you certify that you wrote the code or have the right to submit
it under the Apache-2.0 license (Developer Certificate of Origin). Sign off your
commits with `git commit -s`.
