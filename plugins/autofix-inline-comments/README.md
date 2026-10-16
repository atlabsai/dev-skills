# autofix-inline-comments

A Claude Code mod for the desktop app's Auto-fix. Auto-fix wakes a session on CI
failures, merge conflicts and review comments, but it can miss inline review
threads. This mod fetches them itself and hands them to Claude.

## What it does

**Delivers inline review threads.** While Auto-fix is on for the session's PR
(read from the app's PR monitor), the mod checks the PR every 3 minutes with
`gh api graphql`. When an unresolved inline thread gets a comment Claude has not
seen, it sends Claude the thread: file and line, links, and the comments.
Claude is asked to fix each one, or to reply on the thread saying why not. Each
Auto-fix wake (`<ci-monitor-event>`) also carries every unresolved inline
thread, so the turn that handles a CI failure sees the reviews too. Resolved
threads, threads started by an ignored author, and threads with nothing new
are skipped. `/inline-review` runs the check right away.

**Signs Claude's comments.** Claude posts PR comments under your GitHub login,
so the mod has to tell its replies from yours. Every comment-posting `gh`
command Claude (or a subagent) runs must end with Claude Code's footer:

```
_🤖 Addressed by [Claude Code](https://claude.com/claude-code)_
```

When the footer is missing, the mod adds it where the command's shape allows:

- a body passed as a plain argument (`-f body='...'`, `--body "..."`): the
  command is rewritten with every word single-quoted, so quoting cannot change
  what is posted
- a body from a quoted heredoc (`--body "$(cat <<'EOF' ...)"`), or a heredoc
  that writes the body file in the same command: the footer becomes the
  heredoc's last line
- a body file at an absolute path (`--body-file`, `-F body=@file`): the footer is
  appended to the file; for `--input` JSON, to the review's `body` and each
  inline comment's `body`

A body it cannot sign (a shell variable, a pipe, a GraphQL query string) is
refused, and Claude is asked to add the footer itself and run it again. A comment
under your login is then Claude's only when it carries the footer: anything you
write yourself on GitHub reaches Claude as feedback.

Covered commands: `gh pr comment`, `gh issue comment`, `gh pr review` with a
body, `gh api` writes to comment and review endpoints, and GraphQL comment
mutations. Comments posted another way (`curl`, an MCP tool) are not checked.

## Load it

autofix-inline-comments is a [mod](https://code.claude.com/docs/en/plugins/mods/overview),
checked on Claude Code v2.1.295. The review-thread delivery needs the Claude
desktop app (it reads Auto-fix from the app's PR monitor) and the
[GitHub CLI](https://cli.github.com) logged in. In a terminal session it stays
idle, and only the signing runs.

```
/plugin marketplace add atlabsai/dev-skills
/plugin install autofix-inline-comments@atlabs-dev-skills
```

To turn it on for everyone working in a repository, add this to the repository's
`.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "atlabs-dev-skills": {
      "source": { "source": "github", "repo": "atlabsai/dev-skills" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": { "autofix-inline-comments@atlabs-dev-skills": true }
}
```

## Options

- `pollMinutes` (default 3): how often to check the PR while Auto-fix is on
- `ignoreAuthors` (default `atlabs-ciel[bot]`): comma-separated logins whose
  threads are never delivered; the `[bot]` suffix is optional

## Commands

- `/inline-review`: fetch the PR's unresolved inline review threads now

Check changes with `claude plugin validate plugins/autofix-inline-comments` and
`claude plugin test plugins/autofix-inline-comments`.
