---
description: Cut the line count of the current branch's diff vs its base (the PR's base branch, else main) WITHOUT cutting scope. Applies the obvious cuts straight away, proposes the contentious ones for approval, then commits. Targets real bloat — duplication, dead code, overengineering, no-signal and overlapping tests, verbose comments — never behavior.
arguments:
  - name: pr_number
    description: Optional PR number. If omitted, trims the current branch against its base (rubric §0).
    required: false
---

You are trimming a PR's diff. Goal: **fewer lines, identical scope and behavior**. This is NOT /simplify (quality) and NOT a review — the only metric is diff size, constrained by readability.

**Read `${CLAUDE_PLUGIN_ROOT}/skills/check-quality/bloat-rubric.md` first.** It says where the repo's own rules live (its instructions and the `.claude/lean-diff.md` overlay), and defines how to establish the base (§0), what may never be cut (§1), how to judge tests (§2) and overengineering (§3), the comment rules (§4), which cuts are applied without asking (§5) and how to verify (§6). It binds this command; the steps below say when to use each part.

## Hard rules

- **Never cut scope.** Every feature, fix, edge case, and behavior in the diff survives. If a line's removal changes behavior, it's out of bounds — don't cut it AND don't warn about it (scope commentary is explicitly not this command's job).
- **Condense idiomatically, never golf.** Test: if a reviewer parses the condensed form as fast as the long form, condense; if they'd pause, keep the long form. Nested/multi-clause comprehensions, dense chains doing several things, and removing clarifying names are golf.
- **Only touch files the branch already touches.** Reducing the diff by refactoring untouched files grows the diff.
- **Extend existing tests; never write a new one from scratch.** If a trim needs coverage kept or moved, add the assertion to the existing test that already exercises that call — in the branch's own test files, then the sibling test module. A new test is the last resort and must be justified ("no existing test covers X").
- **Don't ask about the obvious.** Rubric §5 lists what is applied without approval. Asking about an unused import or a restating comment wastes the user's time — the approval round is for real judgment calls only.
- Respect the repo's standards (CLAUDE.md / AGENTS.md): a cut never loosens typing or adds a lint suppression.

## Step 1 — Get the diff, and check the base is real

1. With a PR number: `gh pr view $ARGUMENTS --json headRefName,baseRefName`. If the current branch is not `headRefName`, **stop** and tell the user which branch to run it on — never check out another branch in this worktree. `baseRefName` is the PR's base for the next step.
2. Run rubric §0: resolve and fetch the base, compute `$BASE`, sanity-check the diff, record and snapshot `DIRTY`.
3. Record the baseline: total lines added/removed.

## Step 2 — Hunt for cuts

Read the full diff, then the touched files for context. Look for, in order of typical yield:

1. **Duplication introduced by the branch** — repeated blocks that should be a shared helper/component/fixture.
2. **Reinvented existing code — inventory first, then search three ways.** The highest-yield category, and invisible from the diff alone.

   **Pass 1 — inventory.** List *every* new symbol the branch introduces: utils, helpers, hooks, components, services, constants, types, test fixtures. An unlisted symbol is an unsearched symbol. This same list feeds the call-site counts in step 3.

   **Pass 2 — search each entry three ways.** A near-match under a different name still counts; stop at the first genuine hit.
   - **By name** — the symbol and obvious synonyms (`downloadX` / `saveX` / `exportX`).
   - **By intent** — the behavior, not the label (`debounce`, `formatCurrency`, `retry`, `apiRequest`), plus sibling directories (`utils`, `hooks`, `components`, `services`) and barrel exports.
   - **By body tokens** — grep distinctive identifiers from inside the new symbol's *implementation*: API calls, constants, regexes, DOM methods. A new blob-download helper is invisible to a search for "download" but obvious to a search for `createObjectURL`.

   Prefer wiring into the existing thing — but only on a genuine behavioral match. Close-but-not-identical goes under "considered but kept" with the difference.

   Frontend specifics: a raw `fetch` reinventing the repo's API client; a local modal/dialog/button where a shared one exists; a hand-rolled fetch-once cache where the repo's data-fetching layer already covers it.
3. **Overengineering** — apply rubric §3 to the Pass 1 inventory.
4. **Tests** — apply rubric §2 to every added/modified test.
5. **Dead weight** — unused imports/vars/props, commented-out code, unreachable branches, leftover debug logging.
6. **Comments** — rubric §4.
7. **Boilerplate** — config restating defaults, redundant type annotations where inference is obvious and repo style allows, prop drilling an existing pattern (context, selector) already solves.

Before recording any cut, check it against rubric §1. A mandated construct is not a cut.

## Step 3 — Apply the obvious bucket

Sort every cut by rubric §5. Apply the obvious bucket now, without asking. Do not commit yet.

## Step 4 — Propose the contentious bucket (STOP here)

If the contentious bucket is empty, skip straight to Step 5. Otherwise present:

```
## Trim — baseline: +N/-M lines

Already applied (obvious, -X lines):
- services/foo_service.py — 3 unused imports, single-caller `_build_payload` inlined (1 call site)
- tests/test_foo.py — deleted `test_serializer_requires_name` (serializer contract, no signal); `test_foo_status` (subset of `test_foo_full_response`)

## Proposed (needs your call)

1. [~25 lines] src/components/X.tsx — reuse existing <ConfirmDialog> instead of local modal
2. [~10 lines] services/foo_service.py — collapse `FooStrategy` base into its one subclass (crosses into core/)
...
Estimated total: ~75 lines (-X%)

Considered but kept:
- <thing> — <the file:test, caller or rubric §1 rule that makes the cut unsafe, read before writing this line>

New symbols checked:
- `buildCsv` — no equivalent (searched: csv, export, serialize rows, `\r\n`); 2 callers
- `downloadCsv` — REPLACED by `utils/downloadFile` (body-token hit: `createObjectURL`)
```

Every symbol from the Pass 1 inventory appears under "New symbols checked" with its verdict and call-site count, so the search is auditable instead of asserted. Every applied test deletion names its rubric §2 verdict (and the covering test, for overlap).

Each "considered but kept" entry names the thing that makes the cut unsafe — the test that would stop covering a rule, the caller that needs the abstraction — checked by reading it. A bare rationale ("needed for safety") is a guess; if you have not opened the other test, you do not know whether it already covers this.

Then **wait for approval** on the numbered items — all, by number ("1 and 3"), or none.

## Step 5 — Apply approved cuts and verify

Apply only the approved items. Then run rubric §6 on everything the diff touches. Fix lint failures within the cuts; back out a cut you can't make lint-clean.

## Step 6 — Commit

Commit without asking again — approval of the cut list is approval to land it. Never end with "say the word and I'll commit".

- **An edited file is in `DIRTY` (rubric §0.6) → don't commit.** The user's uncommitted work is mixed into it; leave the cuts in the working tree, report them and the snapshot path, and stop.
- Stage only the files this run edited, by explicit path — never `git add -A` or a bare directory.
- One new commit for both buckets: `refactor: trim <area> diff (-N lines)`. Never amend, never force-push.
- Push if the branch exists on the remote or has an open PR (CI then runs the tests); otherwise leave it local and say so.
- Report: baseline → new diff size, per-item actuals vs estimates, any cut backed out (with reason).
