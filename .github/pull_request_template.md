<!-- PR title follows conventional commits: type(scope): subject -->

## What

<!-- The change as one logical unit. An "and" in the description is a signal to split the PR. -->

## Why

<!-- Link to the issue, a PLAN.md phase, or an ADR. -->

Closes #

## How it was verified

<!-- Commands and their result; for UI changes — screenshots in both light and dark theme. -->

```bash
make test
make lint
```

## Checklist

- [ ] Self-review done: no debug code, stray files, or commented-out blocks
- [ ] Tests added or updated and green (`make test`), linters clean (`make lint`)
- [ ] Prompt / retrieval / chunking changes → `make eval` run, result stated above (thresholds in `evals/thresholds.yaml` not tuned to pass)
- [ ] A fixed decision changed → new or updated ADR in `docs/adr/`
- [ ] New endpoint → `require_role` + a row in the RBAC matrix + its test
- [ ] No secrets in the diff (`.env` is not committed; only secret references in code)
- [ ] Documentation updated if behaviour, interfaces, or commands changed
- [ ] Diff within ~400 lines of meaningful changes; generated files (migrations, lock files, fixtures) flagged
