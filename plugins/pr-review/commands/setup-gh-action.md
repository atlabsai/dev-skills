---
description: Set up pr-review on GitHub Actions for this repo, on Claude, Codex or both — checks the repo can run it, adds the workflow, and walks you through the secret.
allowed-tools: Bash(git:*), Bash(gh:*), Read, Write, Glob, AskUserQuestion
---

Set up the pr-review GitHub Action in the current repository. Work through the steps in order and stop at the first one that fails, telling the user exactly what to fix.

First ask the user (AskUserQuestion) which engine to set up — the same pipeline either way, run on a different model:
- **Claude** (recommended default): `.github/workflows/pr-review.yml`, secret `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`, re-run by commenting `/pr-review`.
- **Codex**: `.github/workflows/pr-review-codex.yml`, secret `OPENAI_API_KEY`, re-run by commenting `/codex-review`.
- **Both**: both files. Each engine posts its own review; they catch different things, so running both is reasonable.

Do every step below for each chosen engine.

**Never ask the user to paste a token, API key or any secret value into this conversation**, and never pass one on a command line you run. Secrets are only ever set by the user, in their own terminal or through `/install-github-app`. You may read secret *names*; you can never read their values.

## 1. Check the repository

- `git rev-parse --show-toplevel` — must be inside a git repo.
- `gh auth status` — `gh` must be installed and logged in. If not: tell the user to run `gh auth login` and re-run this command.
- `gh repo view --json nameWithOwner,defaultBranchRef,viewerPermission,isFork` — the repo must be on GitHub. Note `nameWithOwner` (`<repo>` below) and the default branch.
  - If `viewerPermission` is not `ADMIN`, warn that adding a repo secret needs admin access, so someone with admin may have to do step 3.

## 2. Check it isn't already set up, and that Actions allows it

- Glob `.github/workflows/*.yml` and `*.yaml` and read any that mention `atlabsai/dev-skills`. If one already calls the chosen engine's workflow (`atlabsai/dev-skills/.github/workflows/pr-review.yml` for Claude, `…/pr-review-codex.yml` for Codex), say so, show the file path, and skip that engine.
- `gh api repos/<repo>/actions/permissions`:
  - `enabled: false` → Actions is disabled for this repo; the user must enable it under Settings → Actions. Stop.
  - `allowed_actions: "all"` → fine.
  - `"local_only"` → workflows from other repositories are blocked, including this one. The user (or an org admin) must allow `atlabsai/dev-skills/.github/workflows/*` under Settings → Actions → General. Stop.
  - `"selected"` → it may be blocked. Tell the user to check that `atlabsai/dev-skills/*` is in the allowed list, then continue.

## 3. Check for the secret

Claude needs one of `CLAUDE_CODE_OAUTH_TOKEN` (Claude subscription) or `ANTHROPIC_API_KEY` (API key). Codex needs `OPENAI_API_KEY`. Check both places a secret can come from — names only:

- `gh secret list --repo <repo>`
- `gh api repos/<repo>/actions/organization-secrets --jq '.secrets[].name'` (an error here just means there are no org secrets visible; ignore it)

If the chosen engine's secret is present, say which name and where (repo or org), and continue.

If the chosen engine's secret is missing, tell the user how to add it.

For **Claude**, give both ways:

1. **Easiest:** type `/install-github-app` in Claude Code. It creates the secret through a browser sign-in. When it asks which workflows to add, choose **Skip for now** (or untick them all) — this setup only needs the secret, and adds its own workflow.
2. **By hand**, in their own terminal (not here): run `claude setup-token` for a subscription token, then `gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <repo>` and paste it when prompted. With an API key instead: `gh secret set ANTHROPIC_API_KEY --repo <repo>`.

For **Codex**: in their own terminal (not here), run `gh secret set OPENAI_API_KEY --repo <repo>` and paste an OpenAI API key when prompted (from platform.openai.com → API keys). Codex's ChatGPT sign-in is not supported in CI; it needs an API key.

Continue with step 4 either way — the workflow file can be added before the secret exists. Remember whether the secret was missing, for step 6.

## 4. Add the workflow file

For Claude, read `${CLAUDE_PLUGIN_ROOT}/templates/pr-review.yml` and write it, unchanged, to `.github/workflows/pr-review.yml`. For Codex, read `${CLAUDE_PLUGIN_ROOT}/templates/pr-review-codex.yml` and write it, unchanged, to `.github/workflows/pr-review-codex.yml`. If a destination already exists (and wasn't caught in step 2), ask before overwriting it.

Tell the user, in two or three lines, what the workflow does: a review is posted when a PR is opened or marked ready for review; any member can comment `/pr-review` (Claude) or `/codex-review` (Codex) on a PR to re-run it; the optional settings (per-stage models, custom reviewers, self-hosted runners) are commented in the file.

## 5. Offer to open a pull request

Ask the user (AskUserQuestion) whether to commit the file on a new branch and open a PR, or leave it uncommitted for them. Only if they say yes:

```bash
git checkout -b add-pr-review
git add <the workflow file(s) you wrote>
git commit -m "Add pr-review GitHub Action"
git push -u origin add-pr-review
gh pr create --title "Add pr-review GitHub Action" --body "Adds multi-agent PR review via https://github.com/atlabsai/dev-skills."
```

If the working tree has other uncommitted changes, say so first — only the workflow file(s) should go into this commit.

## 6. Finish

Summarise what was done and what is left. If a PR was opened and the secret exists, point out that the PR itself gets the first review — GitHub runs the workflow from the PR's own branch — so it's a live test within about 10 minutes. If the secret was missing in step 3, the last line must remind the user to add it — without it, every review run stops at its auth check with "Pass claude_code_oauth_token or anthropic_api_key to this workflow." (Claude) or "Pass openai_api_key to this workflow." (Codex).
