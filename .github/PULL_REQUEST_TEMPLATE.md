## What & why

<!-- What does this change and why? Link any issue. -->

## Checklist

- [ ] Tests added/updated (unit for logic, and any regression for a bug fixed)
- [ ] `uv run ruff check .` passes
- [ ] `uv run python -m pytest tests/unit/ -q` passes
- [ ] No secrets / `.env` / real provider keys committed
- [ ] `core` does not import from `enterprise/`
- [ ] Signed off (`git commit -s`)
