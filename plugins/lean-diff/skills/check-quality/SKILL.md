---
name: check-quality
description: Shrink a bloated code diff down to the minimal, reviewable change. Use this skill whenever the user runs /lean-diff:check-quality, asks to "clean up", "slim down", "shrink", or "minimize" a diff or PR, complains that Claude changed too many files, wrote too many tests, overengineered, or left long comments. Never invoke it on your own: after finishing a multi-file change, before committing, suggest running /lean-diff:check-quality in one line and let the developer decide. Runs four parallel audits (change scope, test bloat, comment length, overengineering & quality) on the branch's diff against the fetched remote base, applies the obvious fixes, asks only about the contentious ones, then commits.
---

# Check Quality

A PR should read as one idea. Every extra file touched, every redundant test, every
five-line comment, every single-use abstraction dilutes that idea and costs reviewer
attention. This skill audits the current branch's diff with four parallel agents,
applies the obvious fixes, asks about the rest, and commits the smallest change that
still fully accomplishes the intent.

**Read `bloat-rubric.md` (next to this file) before Step 1** and pass its path to every
agent. It says where the repo's own rules live (its instructions and the
`.claude/lean-diff.md` overlay), and defines how to establish the base (§0), what may
never be cut (§1), test signal (§2), overengineering (§3), comment rules (§4), the
obvious-vs-contentious split (§5) and how to verify (§6). `/lean-diff:trim` uses the
same rubric; change rules there, not here.

Four hard rules frame everything below:

- **The intended change is sacred.** Everything else is a candidate for removal.
- **Obvious fixes are applied without asking; contentious ones never are.** Rubric §5
  draws the line. Asking about an unused import or a no-signal test wastes the user's
  time; reverting a file on a guess destroys work.
- **Nothing is applied until the base is validated (Step 0).** A wrong base turns
  every "fix" into a revert of someone else's merged work.
- **Only the user starts this skill.** Claude suggests it before a commit; it never
  runs it unasked. An unattended run applies nothing.

## Step 0 — Establish the TRUE base and write the brief

1. **Run rubric §0** — resolve and fetch the base, compute `$BASE`, sanity-check the
   diff, record and snapshot `DIRTY`. If the sanity check looks inflated, STOP and do not
   audit. If the diff is empty, say so and stop.
2. **Unattended?** If no one can answer (non-interactive run), note it — Step 2 then
   applies nothing.
3. **Published?** (`git rev-parse --abbrev-ref @{u}` resolves, or `origin/<branch>`
   exists, or `gh pr view` finds a PR.) Note it — a push re-runs CI. Record
   `PRE_SHA=$(git rev-parse HEAD)` as the rollback point.
4. **Write a short change brief** — the shared context every agent receives. Draw it
   from the conversation, the branch name, the commit messages, and any linked PR/issue:
   - **Intent** — one or two sentences on what this branch is *for*.
   - **In scope** — the areas the intent touches. Related work in the same layer counts
     as in scope unless the overlay's `## Scope` says otherwise.
   - **Out of scope** — anything the user said to leave alone, plus deferred follow-ups.

   If the intent is genuinely unknown, write **"Intent: unknown"** rather than guessing.

## Step 1 — Four audits in parallel (analysis only)

Spawn all four agents **in a single message** so they run concurrently. They analyze
only — no edits. Give every agent: the change brief, `$BASE`, the commit list, the
rubric path, and instructions to read the diff themselves (`git diff $BASE`) plus
surrounding code for context.

Every finding records:
- the **exact current text of the lines it targets** (file, line numbers, verbatim) —
  the staleness check in Step 2 applies a fix only if these still match;
- its **bucket** (`obvious` | `contentious`) per rubric §5, with the evidence that puts
  it there (call-site count, covering test name, rubric row);
- confirmation it is not a rubric §1 construct.

### Agent 1 — Scope auditor (unnecessary file changes)

Classify every changed file and hunk against the brief:

- **Essential** — traces to the intent, or is a direct consequence of it (a call-site
  updated for a changed signature, an import the new code needs).
- **Related** — not strictly required, but the same area and layer as the intent. Keep,
  unless the overlay's `## Scope` asks for single-purpose PRs (then: `split-out`).
- **Incidental** — no line back to the intent: formatting/whitespace/import-order churn
  the repo formatter would not reintroduce, drive-by renames in untouched code,
  README/config edits nobody asked for, files on the out-of-scope list.
- **Wrong layer** — product-behavior changes mixed into a test-only/infra branch, or
  vice versa. Don't revert: propose splitting it into its own PR (contentious).

Return `{file, hunk-or-whole-file, verdict, reason, action, bucket, target-lines}` where
action is `revert-file`, `revert-hunk` or `split-out`. Pure churn is obvious; any revert
of real logic is contentious. When unsure whether something is essential, keep it.
If the brief says **"Intent: unknown"**, every scope finding is contentious — a revert
resting on a guessed intent is never applied without the user.

### Agent 2 — Test auditor (signal, overlap, consolidation)

Under audit: tests this branch added or modified. Also read the pre-existing tests
around them (same file, sibling files for the same module) — overlap can only be seen
by comparison.

Apply rubric §2 to every test under audit; record each test's signal answer and verdict:

- `delete` — no-signal (name the §2 shape), or overlap (name the covering test, which
  you have read).
- `merge-into-one` — new tests differing only in inputs (parametrize) or only in
  assertions (one test, grouped assertions). Sketch the merged test.
- `merge-into-existing` — a new test repeating an existing test's setup to add a check:
  extend the existing test, drop the new one. Record target-lines for both.
- `keep` — unique signal. List these too, with their answer, so the reasoning is
  auditable. Every `keep` names the existing test with the closest setup and why that
  test can't absorb it (rubric §2: unique signal ≠ its own test). Also flag duplicated
  helpers inside test files as merge candidates.

Pre-existing tests are only ever extended — never deleted, never weakened. Coverage of
the actual change must not drop; only redundancy goes.

Return `{file, test-name(s), signal-answer, verdict, covering-test, closest-existing-test,
why-not-merged, bucket, target-lines}`.

### Agent 3 — Comment auditor

Apply rubric §4: delete restating and changelog-style comments, compress anything over
3 lines (§4 exemptions aside), keep short why-comments next to the line
they explain, drop docstrings on self-explanatory private helpers.

Return `{file, line, original-comment, rewritten-comment-or-delete, bucket, target-lines}`
— the rewrite ready to paste. All comment fixes are obvious.

### Agent 4 — Overengineering & quality auditor

Review **only code this branch added or modified**.

**Overengineering first** — apply rubric §3 to every new symbol, parameter, class and
file. Report the counts in every finding ("`_build_payload`: 1 caller", "`retries`
param: all 3 callers pass 3").
A finding without a count is a guess — don't report it.

**Then readability.** A human reading the diff top-to-bottom should understand it in one
pass:
- **Inconsistent logic** — the same problem solved two ways in the diff, or a pattern
  that clashes with the surrounding codebase.
- **Functions doing more than one thing** — if describing it honestly needs "and", trim
  it back to its one job.
- **Hard-to-read constructs** — dense one-liners, clever tricks, deeply nested
  conditionals, unclear names.
- **React ref guards suppressing StrictMode double-invocation in `useEffect`** — the
  effect isn't idempotent or lacks cleanup; restructure it. A ref guard is acceptable
  only with a comment justifying why no other structure works.

Every fix must keep the diff small — sketch the **minimal** rewrite. A genuinely large
fix (architectural) is an observation for a follow-up, not a fix item.

Return `{file, function-or-hunk, issue, evidence, suggested-fix, bucket, target-lines}`.

## Step 2 — Apply the obvious bucket, then ask about the rest

**Unattended run:** apply nothing. Save the full plan (obvious and contentious) to a file
in the scratchpad, report where it is, and stop.

1. **Apply every obvious finding** in order: scope reverts → overengineering/quality →
   tests → comments. Scope first so later steps don't polish code about to disappear;
   code before tests so tests are adjusted against its final shape.
2. **Staleness check on every item**: re-read the file and compare against the recorded
   target lines. If they no longer match, skip the item and note it.
3. **Present the plan**:

```
## Check quality — base origin/main @ abc1234 | PR #142 open (push will re-run CI)
Diff: +420/-30 → +310/-30 after obvious fixes

Applied (obvious):
  T1. deleted test_create_requires_name — serializer contract, no signal
  T2. deleted test_status_field — subset of test_full_response (same setup+call)
  O1. inlined _build_payload into create() — 1 caller
  O2. dropped `retries` param — all 3 callers pass 3
  C1. jobs.py:12 7-line docstring -> 2 lines
  S1. reverted import reordering in utils/format.ts

Needs your call:
  1. revert services/legacy.py hunk L40-72 — rename + logic change not in the brief
  2. split src/... change into its own PR — product behavior in a test-infra branch
  3. reuse existing <ConfirmDialog> over local modal — behavior differs: no Enter-confirm
```

Ask which numbered items to apply: all, a subset, or none. If nothing is contentious,
skip the question and go to Step 3.

Apply approved items in the same order. Their recorded target lines predate the obvious
pass: if they no longer match, **re-locate** the item only where its recorded text
appears verbatim, exactly once, in the current file. Otherwise skip it and list it as
"approved, not applied" with the reason — never apply a fix to a guessed location.

## Step 3 — Verify

Run rubric §6 on everything the diff touches.
Confirm the intent from the brief still holds — the feature/fix the branch exists for is
intact.

## Step 4 — Commit and report

Commit without asking again — approval of the plan is approval to land it — unless a
file this run edited is in `DIRTY` (rubric §0.6): the user's uncommitted work is mixed
into it and committing would land it unreviewed. Then leave the edits in the working
tree, say so, give the snapshot path, and stop.

When committing:

- Stage only the files this run edited, by explicit path — never `git add -A` or a
  bare directory.
- One new commit: `refactor: tighten <area> diff (-N lines)`. Never amend, never
  force-push.
- Push if the branch is published (Step 0); otherwise leave it local and say so.
- Report: before/after diffstat, every applied item, every skipped item, and the
  rollback point (`git revert <commit>`, `PRE_SHA`, or the §0.6 snapshot tarball).
