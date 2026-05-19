## Summary

<!-- One or two sentences. What changed and why. Link the issue if there is one. -->

## Type of change

- [ ] Bug fix
- [ ] Feature
- [ ] Refactor (no behavior change)
- [ ] Docs
- [ ] Test
- [ ] Build / CI / tooling

## Tests run

<!-- Paste the commands you ran locally and the result. -->

- [ ] `cd backend && uv run pytest -n auto`
- [ ] `cd frontend && npx vitest run`
- [ ] `cd frontend && npm run typecheck && npm run lint && npm run build`
- [ ] `pre-commit run --all-files`

## Risk and rollback

<!-- What could go wrong? How would you revert? -->

- Risk:
- Rollback:

## Screenshots

<!-- Only if UI changed. Remove this section otherwise. -->

## Checklist

- [ ] Scope is small and focused.
- [ ] Tests cover the change (both happy and negative paths where relevant).
- [ ] Docs / READMEs / env examples updated if behavior or commands changed.
- [ ] Migrations included if SQLAlchemy models changed.
- [ ] Backend API and frontend types updated together.
- [ ] No secrets, credentials, or PII in code, tests, or fixtures.
- [ ] Commit messages are imperative and free of AI-tool attribution.
