# lean-diff

Two commands that shrink the current branch's diff against its base without cutting
what the branch is for. Both apply the fixes no reviewer would argue with, ask about
the judgment calls, then commit once.

| Command | What it does |
|---|---|
| `/lean-diff:check-quality` | Four audits in parallel: files the change didn't need, tests with no signal or that overlap, comments over three lines, and overengineering counted by call sites (one caller, one implementation, a parameter every caller passes the same value). |
| `/lean-diff:trim [pr]` | Cuts line count only: duplication, code that reinvents an existing helper (searched by name, intent and body tokens), dead weight, then the same test, comment and overengineering rules. |

Both read one rubric, [`bloat-rubric.md`](skills/check-quality/bloat-rubric.md), so they
never disagree about what counts as bloat.

## Safety

- The base is fetched and checked first. A diff that pulls in other authors' commits
  stops the run instead of reverting their work.
- Uncommitted work is snapshotted before any edit, and a file that held it is never
  committed.
- Existing tests are only ever extended, never deleted or weakened.
- Only you start a run. Without someone to answer, it applies nothing and saves its plan.

## Your repo's rules

The rubric is generic. Your repo adds its own in two places, and they win:

1. `CLAUDE.md` / `AGENTS.md`: anything they mandate is never cut.
2. An optional overlay at `.claude/lean-diff.md`:

```markdown
## Never cut
- Every `track()` call and its event-name constant.
- `@deprecated` shims under `api/v1/`: removed only with the v1 sunset.

## Verify
- `npm run lint` for `web/`, `ruff check` for `server/`. Don't run tests: CI does.

## Scope
- One concern per PR: split related work out.

## Exempt comments
- Migration docstrings: the release tooling reads them.
```

Without a `## Verify` section, the lint commands come from your instructions, then your
tooling (`package.json`, pre-commit, `Makefile` / `justfile`). Tests run only when the
overlay or your instructions ask for them.

```
/plugin install lean-diff@atlabs-dev-skills
```
