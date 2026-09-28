---
description: Multi-agent PR review — 6 reviewers + impact analyst in parallel, then a validator that re-reads the code behind every finding. Reviews the current branch, or a PR by number.
argument-hint: "[pr-number] [--post]"
allowed-tools: Bash(git:*), Bash(gh:*), Bash(python3:*), Bash(mkdir:*), Bash(date:*), Agent, Read, Write, Glob
---

You are the orchestrator of the pr-review pipeline. Run every step below in this turn. Launch every agent with `run_in_background: false` and wait for its result before moving on — never end your turn while a stage is still running. (In a headless `claude -p` session nothing resumes you once you stop, so a backgrounded stage means no review at all.)

Arguments: `$ARGUMENTS` — an optional PR number, and an optional `--post` flag.

Keep every shell command a single plain command: no `$(...)`, no `VAR=value` prefixes, no `&&` chains. Write paths out literally. This keeps each command matchable by the user's permission rules, so the review doesn't stop to ask for approval.

## Step 1 — Set up the run directory

Run `date +%s`. Its output is the run id, `<id>` below. The run directory is `.pr-review/<id>` at the repository root; all paths below are relative to the repository root.

```bash
mkdir -p .pr-review/<id>/pr-context .pr-review/<id>/reviews
```

Write `.pr-review/.gitignore` containing the single line `*` (this makes the whole directory ignore itself, so nothing here is ever committed).

**With a PR number:** run `gh pr view <n> --json headRefOid,baseRefName,title,body` and compare `headRefOid` with `git rev-parse HEAD`. If they differ, stop and tell the user to run `gh pr checkout <n>` first — reviewers read files from disk, so reviewing a PR from another checkout would validate against the wrong code. Then:

```bash
gh pr diff <n>
```

Write its output to `.pr-review/<id>/pr-context/diff.txt`.

**Without a PR number:** find the base with `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` (use `main` if that fails), run `git fetch origin <base> --quiet`, then write the output of `git diff origin/<base>...HEAD` to `.pr-review/<id>/pr-context/diff.txt` and read `git log --format=%s origin/<base>..HEAD` for the commit subjects. Uncommitted changes are not reviewed; mention it if `git status --porcelain` is non-empty.

For very large diffs, redirect instead of writing through the Write tool: `git diff origin/<base>...HEAD --output=.pr-review/<id>/pr-context/diff.txt`.

Write `.pr-review/<id>/pr-context/meta.json` as `{"title": ..., "body": ..., "started_at": <id>}` — the PR title and body, or for a branch review the branch name and the commit subjects. `started_at` is the run id as a number.

If the diff is empty, stop and say so.

**Pre-change files and parity shards.** Reviewers have Read but not git, so the behavior-parity reviewer needs the old versions on disk. `<base>` is the PR's `baseRefName`, or the default branch for a branch review. Run `git merge-base origin/<base> HEAD`, and call its output `<sha>`. Then run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/snapshot_base.py --base <sha> --out .pr-review/<id>/pr-context/base
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/plan_parity_shards.py --base <sha> --out .pr-review/<id>/pr-context/parity-shards
```

The second command prints a shard count N. `0` means a normal-sized PR: run one parity reviewer. Otherwise, run N parity reviewers in Step 2, one per shard.

## Step 2 — Reviewers and impact analyst, in parallel

Glob `.github/pr-review/reviewer-*.md` for custom reviewers the team added. A custom reviewer's name is its file name without `.md`.

Launch ALL of these in a single message so they run concurrently:

| Name | subagent_type |
|---|---|
| bugs | `pr-review:reviewer-bugs` |
| arch | `pr-review:reviewer-arch` |
| quality | `pr-review:reviewer-quality` |
| simplify | `pr-review:reviewer-simplify` |
| prod | `pr-review:reviewer-prod` |
| parity (or parity_1 … parity_N when sharded) | `pr-review:reviewer-parity` |
| (impact) | `pr-review:impact-analyst` |
| each custom reviewer | `general-purpose`, told first to read its spec file and follow it exactly |

Prompt for each:

> The PR diff is at `.pr-review/<id>/pr-context/diff.txt` (read it with the Read tool, paging with offset/limit if it is large). Title and body are in `.pr-review/<id>/pr-context/meta.json`. BASE_DIR, the pre-change version of every file the PR modifies, deletes or renames (listed in its INDEX.txt), is `.pr-review/<id>/pr-context/base`. The working directory is the checked-out PR head. Do your review as your instructions describe and return exactly the output they specify, nothing else.

For parity shard k, add to its prompt: "SHARD: you are parity shard k. Your shard diff is `.pr-review/<id>/pr-context/parity-shards/k.diff`; review only the behaviors in it. The file list is in `SHARDS.txt` beside it."

As each returns, write its output verbatim with the Write tool: a reviewer's to `.pr-review/<id>/reviews/<name>.txt`, the impact analyst's JSON object to `.pr-review/<id>/impact.json`. If a reviewer errored, write nothing for it — the formatter reports it as failed.

## Step 3 — Validate

Launch `pr-review:validator` with:

> Reviewer outputs to validate are the files in `.pr-review/<id>/reviews/`, one per reviewer, named after it. The diff is at `.pr-review/<id>/pr-context/diff.txt`. BASE_DIR (pre-change copies of modified files, for checking behavior-parity findings) is `.pr-review/<id>/pr-context/base`. The working directory is the checked-out PR head. Follow your instructions and return the DISMISSED/MERGED lines followed by the JSON array.

Write the JSON array alone to `.pr-review/<id>/validated.json`. Keep its DISMISSED/MERGED lines for Step 4.

## Step 4 — Format and show

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/format_review.py --run-dir .pr-review/<id> --reviewers "<names of every reviewer you launched, space-separated — not the impact analyst>"
```

For a PR review, add `--pr <n> --repo <owner/repo> --branch <head branch>` so file references become GitHub links.

The script prints the review and writes it to `.pr-review/<id>/comment.md`. **Your final message is the script's output exactly as printed** — do not rewrite, summarise, reorder, or add commentary around it. Put the validator's DISMISSED/MERGED lines before it, under a line reading `Validator:`, and nothing after it.

## Step 5 — Post (only with `--post` and a PR number)

```bash
gh pr comment <n> --body-file .pr-review/<id>/comment.md
```

Without `--post`, do not post anything anywhere.
