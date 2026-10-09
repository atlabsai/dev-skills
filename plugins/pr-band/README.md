# pr-band

A Claude Code mod that shows the current branch's open pull request above the
prompt, styled like the desktop app's PR chip:

- `#number` (links to GitHub), repo name, branch
- `+additions −deletions`
- a CI dot: green passing, red failing, yellow running, grey no checks
- on hover, a card like the app's PR popup (Open / Merged / Closed, owner/repo #number, age, title, author, `+/−`, files changed, and a `↻` refresh button beside the age); `×` hides the chip for the session

It runs `gh pr view` on the session's branch at session start, after every turn
and every 5 minutes while the session has been active in the last 30 (so not
overnight). It needs the [GitHub CLI](https://cli.github.com) installed and
logged in. A PR that merges or closes while shown stays on the chip with its
state; no open PR on the branch otherwise means no chip. `/pr-band-demo` holds
until `/pr-band`.

## Load it

pr-band is a [mod](https://code.claude.com/docs/en/plugins/mods/overview), so it
needs Claude Code v2.1.286 or later.

```
/plugin marketplace add atlabsai/dev-skills
/plugin install pr-band@atlabs-dev-skills
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
  "enabledPlugins": { "pr-band@atlabs-dev-skills": true }
}
```

## Commands

- `/pr-band`: show the chip again and refresh it from `gh`
- `/pr-band-demo`: fill the chip with sample data

Check changes with `claude plugin validate plugins/pr-band`.
