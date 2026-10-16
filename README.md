# dev-skills

Claude Code plugins for software teams, built and run in production at [Atlabs](https://atlabs.ai).

```
/plugin marketplace add atlabsai/dev-skills
```

| Plugin | What it does |
|---|---|
| [**pr-review**](plugins/pr-review) | Multi-agent PR review. Six specialist reviewers run in parallel, including one that compares old and new code for unintended behavior changes; a validator re-reads the code behind every finding (dedupes, calibrates severity, scores confidence, checks the suggested fix); an impact analyst maps which existing flows the change could break and writes a manual test checklist. Runs locally via `/pr-review:review` or on every PR via a reusable GitHub Actions workflow. |
| [**pr-band**](plugins/pr-band) | Shows the current branch's pull request above the prompt, like the desktop app's PR chip: number, `+/-` lines, a CI status dot, and a hover card with title, author and state. Refreshes after every turn. Needs the GitHub CLI. |
| [**autofix-inline-comments**](plugins/autofix-inline-comments) | For the desktop app's Auto-fix: while it is on for the session's PR, hands Claude the unresolved inline review threads Auto-fix did not deliver, and signs every PR comment Claude posts from your account so its replies are never read back as your feedback. Needs the GitHub CLI. |

```
/plugin install pr-review@atlabs-dev-skills
/plugin install pr-band@atlabs-dev-skills
/plugin install autofix-inline-comments@atlabs-dev-skills
```

Issues and pull requests are welcome.

## License

MIT, see [LICENSE](LICENSE).
