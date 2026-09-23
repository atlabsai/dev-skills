# pr-review

Multi-agent pull request review for Claude Code, run locally with `/pr-review:review` or on every PR through a reusable GitHub Actions workflow.

Most AI reviewers read the lines that changed. This pipeline does two more things:

1. **It checks its own findings.** A validator re-reads the code behind every finding before anything reaches you. It throws out false positives, fixes line numbers, lowers severities it can't justify, merges duplicates, checks that the suggested fix is actually correct, and states how confident it is and why.
2. **It maps what the change can break.** An impact analyst traces the callers of everything the diff touches and names the existing user flows at risk: the *integration contours*. From those it builds a manual test checklist, with the flows most likely to regress listed first.

```
                 ┌─ reviewer-bugs ─────┐
                 ├─ reviewer-arch ─────┤
PR diff ──────▶  ├─ reviewer-quality ──┼──▶ validator ──┐
                 ├─ reviewer-simplify ─┤   (re-reads    │
                 ├─ reviewer-prod ─────┤    the code)   ├──▶ formatter ──▶ one PR comment
                 ├─ your own reviewers ┘                │   (a Python
                 └─ impact-analyst ─────────────────────┘    script)
                    all in parallel
```

## What a review looks like

````markdown
🤖 PR Review — PR #412: Move session locks to per-request keys
5 reviewers · validated · 3 contours · 4 findings

Moves the submit lock from a per-attempt key to a per-request key. 1 critical issue flagged.

## 🔴 Critical (1)
### 1. Old and new workers take different locks during a rolling deploy
`tasks.py:115`
**Confidence:** 🟢 high — Traced acquire/release in both versions; neither checks the other key.
```python
lock_key = f"submit:{request_id}"  # ← issue here
```
While both versions are running, an old worker locks `submit:{attempt_id}` and a new one
locks `submit:{request_id}` for the same job, so both call the provider...
**Suggested fix:** Acquire both keys until the old version is fully drained.

## 📍 Integration Contours (3)
**Retry sweeper → submit** — `sweeper.py:88`, `tasks.py:115`
The sweeper re-dispatches stuck jobs and relies on the lock to skip live ones...

## ✅ Manual Test Targets
- ⚠️ Kill a worker mid-submit and let the sweeper re-dispatch: the provider should be called once.
````

## Install

**Locally**, as a Claude Code plugin:

```
/plugin marketplace add atlabsai/dev-skills
/plugin install pr-review@atlabs-dev-skills
```

Then:

```
/pr-review:review              # review the current branch against the default branch
/pr-review:review 412          # review PR #412 (check it out first: gh pr checkout 412)
/pr-review:review 412 --post   # ...and post the review as a PR comment
```

**In CI:** with the plugin installed, run `/pr-review:setup-gh-action` in your repo. It checks the repo can use the workflow, adds `.github/workflows/pr-review.yml`, and tells you how to add the Claude secret if the repo doesn't have one yet. To do it by hand instead, copy [`templates/pr-review.yml`](templates/pr-review.yml) to `.github/workflows/` and add a `CLAUDE_CODE_OAUTH_TOKEN` secret (from `claude setup-token`) or an `ANTHROPIC_API_KEY` secret. Every PR is then reviewed when it's opened or marked ready, and any member can comment `/pr-review` to run it again.

## Running it on Codex

The same pipeline (same reviewers, validator, impact analyst and formatter) also runs on OpenAI Codex. `/pr-review:setup-gh-action` offers Claude, Codex or both; by hand, copy [`templates/pr-review-codex.yml`](templates/pr-review-codex.yml) and add an `OPENAI_API_KEY` repo secret.

- It posts as **PR Review (Codex)** and re-runs on a `/codex-review` comment, so it can run alongside the Claude version without the two triggering each other. In our experience the two catch different things, so running both is reasonable.
- It needs an OpenAI API key. Codex's ChatGPT sign-in isn't supported in CI.
- The model runs in Codex's read-only sandbox, and a permission profile makes Codex's own credentials file unreadable to it. A PR could try to talk the model into printing secrets into the posted review; this makes that impossible. Only the login step ever sees the API key.
- Each stage's output is its final message, so a stage can't skip saving its result; JSON is cut out of the message and a stage whose JSON doesn't parse is retried once.
- The model defaults to the Codex CLI's default; set `model` (or per-stage `models`) to choose.

## Configuration

Inputs to the reusable workflow:

| Input | Default | |
|---|---|---|
| `models` | `{}` (every stage on `sonnet`) | Per-stage override, e.g. `{"impact":"opus","validator":"opus"}`. Invalid values are ignored with a warning; they never block a review. |
| `reviewers` | `bugs arch quality simplify prod` | Which built-in reviewers to run. |
| `extra_reviewers` | none | Paths in your repo to your own reviewer specs (see below). |
| `trigger_phrase` | `/pr-review` | Comment that re-runs a review. Honoured only from owners, members and collaborators. |
| `runs_on` | `"ubuntu-latest"` | Runner labels as JSON. |
| `claude_cli_version` | pinned | The Claude Code CLI version. Pinned so a CLI release never silently changes review behaviour. |
| `tooling_ref` | `v1` | Keep equal to the ref in your `uses:` line. |

**Project conventions.** The architecture and quality reviewers read your `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` and `docs/architecture/` if they exist, and judge the diff against your rules rather than generic taste. The better those files are, the better the review.

## Adding your own reviewer

A reviewer is one markdown file. Put it at `.github/pr-review/reviewer-<name>.md` in your repo:

- `/pr-review:review` picks it up automatically.
- In CI, list it in `extra_reviewers`.

It runs in parallel with the built-ins, and the validator checks its findings like any other reviewer's. Any output works, either a JSON array in the same shape the built-in reviewers return or plain prose. The validator normalises both. Custom reviewers are where team-specific checks belong, for example "every new button fires an analytics event", "migrations must be backwards-compatible" or "every user flow change has an end-to-end test".

## What we learned running it

We ran this pipeline on every PR in a production monorepo (Django, React, Celery). We then audited 20 merged PRs, checking commit by commit whether each of the 111 first-review findings got fixed and whether each "critical" was a real bug.

- **77% of findings were addressed**, or about 71% if you exclude findings that only disappeared because the code was rewritten for other reasons. The ignored ones were almost all low-severity notes.
- **Of 12 criticals, 5 were clearly real bugs.** Examples:
  - A lock-key rename that let two versions of a worker double-call a paid API during a rolling deploy. It was fixed within 15 minutes.
  - A usage-billing path that under-charged whenever a media duration hadn't been measured yet.
  - A settings toggle that was saved but never applied.
- **The other criticals were over-escalated.** Most were documented rules that had been broken with no real production exposure. That is why the validator now calibrates severity: `critical` needs a concrete failure path.
- **Overlapping reviewers reported the same defect 2–3 times** on several PRs. That is why the validator now merges duplicates.
- **Once, the suggested fix was itself a bug.** That is why the validator now checks the fix, not just the finding.
- **It is not a complete review.** Another AI reviewer running on the same PRs caught behaviour bugs this one missed on about a third of them, including a migration whose application-level default would break old workers mid-deploy (the prod reviewer now checks for that). This pipeline was stronger on structure, duplication and deploy hazards, the other on behaviour. Run more than one reviewer, and keep a human.

"Addressed" means a later commit fixed the flagged issue. That doesn't prove the review caused the fix.

**Infrastructure lessons, which cost us real time:**

1. **Don't let a model orchestrate other models in CI.** A one-shot `claude -p` session that spawned reviewers kept saying it would "continue once they finish" and then ended its turn. Nothing posted and nothing failed. Now bash waits on real process IDs, and every model call is one session that never orchestrates.
2. **Don't use a model for formatting.** Turning JSON into markdown with an LLM took ~10 minutes per review. A Python script does it in milliseconds, identically every time.
3. **Run the stages in one job.** GitHub bills each job's wall-clock rounded up, plus a cold start. Going from ten jobs to one cut billed time from ~29 to ~10 minutes per review.
4. **Check the output file, not the exit code.** A session can exit 0 having skipped its final write, and in practice sometimes does. Each stage's contract is "the file exists and isn't empty", and a stage that breaks it is retried once.
5. **Degrade, don't die.** A failed reviewer is listed in the comment, and a malformed stage output or config value falls back with a warning. A job-level timeout is a hard cancel that posts nothing, so per-call timeouts are sized to always fire first.

## Cost and security

- **Cost:** a review is seven model sessions (five reviewers, the impact analyst and the validator). With every stage on Sonnet, a ~400-line diff took about 7 minutes and $3 locally; in CI the reviewers run concurrently and a review typically takes 8–10 minutes end to end. Use `models` to move stages to a cheaper model, or `reviewers` to run fewer.
- **Agent permissions:** agents get `Read`, `Grep`, `Glob` and `Write` only. They have no shell and no network, and the checkout does not persist git credentials.
- **Untrusted PR content:** the model reads the PR's code and description. A malicious PR could try to steer what the review says, but not what the job can do.
- **Who can trigger a review:** comment triggers are accepted only from owners, members and collaborators. Pull requests from forks don't receive your secrets, so they aren't reviewed automatically.
