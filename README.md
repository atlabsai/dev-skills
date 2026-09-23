# dev-skills

Claude Code plugins for software teams, built and run in production at [Atlabs](https://atlabs.ai).

```
/plugin marketplace add atlabsai/dev-skills
```

| Plugin | What it does |
|---|---|
| [**pr-review**](plugins/pr-review) | Multi-agent PR review. Five specialist reviewers run in parallel; a validator re-reads the code behind every finding (dedupes, calibrates severity, scores confidence, checks the suggested fix); an impact analyst maps which existing flows the change could break and writes a manual test checklist. Runs locally via `/pr-review:review` or on every PR via a reusable GitHub Actions workflow. |

```
/plugin install pr-review@atlabs-dev-skills
```

Issues and pull requests are welcome.

## License

MIT, see [LICENSE](LICENSE).
