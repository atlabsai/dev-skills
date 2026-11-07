# Bloat rubric — shared by `trim` and `check-quality`

Both tools read this file. Change a rule here, not in either tool, so they never
disagree about what counts as bloat or what may be cut without asking.

## Repo rules — read before anything else

The rules below are generic. Every repo adds its own, and the repo's always win:

- **Its instructions**: `CLAUDE.md` / `AGENTS.md` at the root and in the directories the
  diff touches, plus any file they point to as binding.
- **Its overlay**, `.claude/lean-diff.md`, if present. It may hold any of these sections:
  - `## Never cut` — repo-mandated constructs that look like bloat (extends §1).
  - `## Verify` — the lint/typecheck commands to run after edits, and whether to run tests.
  - `## Scope` — how the team sizes PRs (extends the scope audit).
  - `## Exempt comments` — comments or docstrings a check reads, exempt from §4.
  - `## Reuse` — shared helpers and directories to search before accepting a new one.

Where no overlay names them, take the lint commands from the repo's instructions, then
its tooling (`package.json` scripts, `pre-commit` config, `Makefile` / `justfile`).

## 0. Establish the true base

A stale base is the worst failure mode: the "diff" balloons with every PR merged since,
and the tool proposes reverting other people's merged work.

1. **Name the base branch** — the first that applies: a base the user named; the PR's
   `baseRefName` (`gh pr view --json baseRefName`, which works without a PR number on a
   branch with an open PR — this is what catches stacked PRs); the remote default
   (`git symbolic-ref --short refs/remotes/origin/HEAD`); `main`.
2. **Fetch it before using it** (`git fetch origin <branch> --quiet`) — never pick a
   candidate by whether a ref happens to exist locally. If the fetch fails, say so and
   stop — never audit against an unverifiable base.
3. `BASE=$(git merge-base "origin/<branch>" HEAD)`. Every later command uses `$BASE`.
4. **The diff under audit** = `git diff $BASE` (no `...HEAD`: uncommitted changes count)
   **plus** untracked files from `git ls-files --others --exclude-standard` that belong
   to the branch's work (`git diff` never shows them). Ignore unrelated untracked
   clutter — tooling checkouts, scratch files.
5. **Sanity-check** `git log --format='%h %an %s' $BASE..HEAD` and `git diff --stat $BASE`.
   STOP and show the user if you see commits by other authors, merge commits from the
   base, or a file count far beyond what the branch name and commits could plausibly
   touch.
6. **Pre-existing uncommitted work.** Record `DIRTY` = files differing from HEAD (staged
   or not) plus untracked files, and snapshot them before any edit:
   ```bash
   { git diff --name-only --diff-filter=d -z HEAD; git ls-files -o --exclude-standard -z; } \
     | sort -zu | xargs -0 -r tar -czf <scratchpad>/pre-<tool>.tgz
   ```
   A tool commits only files it edited, and **never commits if any of them is in
   `DIRTY`** — that would land the user's unreviewed work. Never `git stash
   push/store/pop` (the stash stack is shared across worktrees), never create backup
   branches.

## 1. Never cut — mandated code that looks like bloat

These look unused, redundant or over-documented, and are required. Do not flag them.
The overlay's `## Never cut` list and anything the repo's instructions mandate are
protected too.

- **Generated files** — migrations, snapshot/golden files, lockfiles, generated types.
  Never hand-edit; they change only by regenerating.
- **Analytics and tracking calls**, with their event-name constants and shared props.
- **Anything a check reads** — a docstring, comment, marker or registry entry that a
  test, lint rule or CI job parses. Removing it fails CI.
- **Declared known-failure markers** (xfail, skip-with-ticket, known-bug entries) —
  removed only by the change that fixes the bug.
- **Lint and framework workarounds the repo documents** — fields declared only so a
  validator or decorator doesn't warn, wrappers that guard a known runtime crash.

## 2. Test signal — the one question

For every test the branch adds or modifies, answer in one line:
**"Which concrete bug makes this test fail, that no other test would catch?"**

- **No answer → no-signal → delete.** Shapes:
  - Tautological: asserts a mock returns what the test just told it to return, or that
    a mock was called with arguments the test itself passed straight through.
  - Library/framework contract: an ORM field default, a serializer rejecting a missing
    required field, a component rendering a prop it was given, a typed dict having its
    keys.
  - Constant/config echo: `assert SETTING == 5` where the code reads `SETTING`.
  - Trivially-correct code: no branch, no loop, no error path, no boundary (a
    pass-through, a one-line arithmetic, a rename).
  - Cannot fail: no assertion, or only asserts on fixture data.
- **Answer exists, but another test already catches it → overlap → delete the weaker
  one.** Name the covering test, by reading it. Shapes:
  - Subset: test B's setup+call match test A's, and B's assertions are a subset of A's.
  - Two layers, one rule: a unit table for a predicate AND an end-to-end test whose
    assertions can only pass when that rule holds → keep the outer, drop the inner rows.
  - Same path, different names: same branch of the code under test, same assertion
    shape.
- **Answer exists and is unique → keep**, then compress:
  - Only inputs differ → parametrize (`pytest.mark.parametrize` / `it.each`).
  - Only assertions differ (same setup, same call) → merge into one test with grouped
    assertions. Merge *into* an existing test that already has the setup.
  - Same setup, different trigger (a click, a key, an event) → one `it.each` /
    `parametrize` whose rows pass the trigger as a function. Unique signal per row is
    not a reason to keep separate tests; it is what the rows are for.
  - Edge-case padding: keep one case per distinct branch/boundary, drop the rest.
- **Unique signal ≠ its own test.** For every kept test, name the existing test with the
  closest setup. If small additions to that setup (an extra field or fixture value)
  plus extra assertions cover the same check, and every existing assertion still holds,
  merge it into that test. A test that stays separate says why that test can't absorb it.
- **Duplicated helpers inside test files** (two harnesses doing one job) → merge
  candidate: one shared helper.

Pre-existing tests (on the base) are never deleted and never weakened — they may only
absorb a new test's assertions, plus purely additive setup that keeps their own
assertions passing.

## 3. Overengineering — count, don't eyeball

Inventory every symbol, parameter, class and file the branch introduces. For each,
**grep its call sites** and record the count and the distinct argument values.

| Signal (measured) | Verdict |
|---|---|
| Function/hook/component with **one caller** and no reuse in sight, body < ~15 lines | Inline it |
| Wrapper whose body only forwards to another call (maybe renaming args) | Inline it |
| Parameter/prop/option where **every caller passes the same value** (or none passes it) | Drop it, hardcode the value |
| Interface/Protocol/ABC/base class with **one implementation** | Collapse into the implementation |
| Factory/registry/strategy map with **one entry** | Call the thing directly |
| Config object, typed dict or dataclass built at **one site** to pass ≤3 values | Pass the values |
| `try/except` that re-raises, or logs then re-raises, unchanged | Delete the try |
| Defensive check for a state the types or the caller already rule out | Delete the check |
| Backward-compat shim / fallback for code introduced **in this same branch** | Delete the shim |
| Feature flag, setting or env var nobody asked for | Delete, hardcode |
| `useMemo`/`useCallback`/`React.memo` on a cheap value with no memoized consumer | Delete the memo |
| Custom hook wrapping a single `useState`/`useSelector` with no logic | Inline it |
| New file holding one small symbol used from one place | Move it into its caller's file |
| Thin call chain A→B→C where B and C are single-caller hops | Flatten |

A symbol with a test seam (it is the thing a test targets) or an existing-pattern match
(the codebase uses the same layering everywhere — e.g. a service layer) is not
overengineering; record it under "considered but kept" with the seam or pattern named.

## 4. Comments

- Delete comments that restate the code, and changelog-style comments ("added X",
  "now handles Y", "fix for PROJ-123").
- No comment or docstring longer than **3 lines** — compress with bullets/arrows, keep
  the content. Exempt: what a check reads (§1) and the overlay's `## Exempt comments`.
- A short **why** comment (constraint, gotcha, non-obvious invariant) sits next to the
  line it explains, inside the function body if that's where the line is. Move it into
  the docstring only when it describes the whole function.
- Docstrings on self-explanatory private helpers → delete.

## 5. Obvious vs contentious

**Obvious — apply without asking.** A reasonable reviewer would not argue, and behavior
is provably identical:

- Unused imports/vars/props/args/constants/types; commented-out code; debug logging.
- Every comment fix under §4.
- Tests §2 classifies as no-signal, or overlap **with the covering test named**; new
  tests whose only difference is input → parametrized; new tests whose only difference
  is assertions → merged, including into an existing test by **adding** assertions.
- Purely additive changes to an existing test's setup (an extra field or fixture value)
  that leave every existing assertion passing, when they let a new test be folded in.
  Changing or removing existing setup stays contentious (below).
- Overengineering rows from §3 where the call-site count proves it (one caller, one
  implementation, every caller passing the same value) and the edit is local.
- Idiomatic condensation a reviewer parses as fast as the original: comprehension over
  a 3-line build loop, ternary over a trivial if/else assignment, early return over one
  level of nesting.
- Formatting/import-order churn in a file the intent doesn't otherwise touch → revert,
  unless the repo formatter would put it straight back.

**Contentious — propose and wait.** Judgment, taste, or risk:

- Rewiring to an existing helper/component the branch duplicated (behavior match must
  be checked line by line).
- Reverting a whole file or a hunk with real logic in it on scope grounds.
- Inlining/removing an abstraction that has >1 caller or crosses a module boundary.
- A test whose signal is real but small (catches a bug only a contrived edit causes).
- Anything that removes or rewrites an existing test's setup or assertions (adding
  assertions, or purely additive setup, is obvious, above), or that you are not certain
  is behavior-identical.

When unsure which bucket, it's contentious — but "unsure" means a concrete doubt you
can state, not reflexive caution. If you can't name the risk, it's obvious.

## 6. Verify

Run the lint/typecheck commands the overlay's `## Verify` names (else the repo's, per
"Repo rules") on everything the diff touches. A lint failure means a fix went too far:
back out that specific fix (not the whole file — it may hold the user's uncommitted
work) and re-lint. Run tests only if the overlay or the repo's instructions ask for it;
otherwise leave them to CI and say so.
