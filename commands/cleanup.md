---
description: Archive a published topic's raw dumps and remove its regenerable intermediates
argument-hint: <topic> [--restore|--purge]
---

Retire the working files for topic **$ARGUMENTS**.

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cleanup.py" <topic> [flags]
```

**Confirm the topic has actually been published first.** These dumps are gitignored and local-only — there is no git history behind them. If `<topic>/<topic>.md` does not exist, or the topic never reached a Reviewer PASS, say so and stop: cleaning now discards source material that produced nothing.

Default behaviour archives dumps to `_sources/<topic>/.archive/<timestamp>/` and deletes `commands.yml`, which is regenerable by re-running `/cheatsheet-forge:analyze`. This is reversible via `--restore`.

**Never pass `--purge` on your own initiative.** It permanently destroys dumps and leaves every `source_ref` dangling, which means the topic can never be re-reviewed or re-extracted. Pass it only when the user asks for it in those words, and tell them what they are giving up before you do.

## Next step

- Archived → note that re-running `/cheatsheet-forge:analyze <topic>` needs `--restore` first, and give that command.
- Restored → `/cheatsheet-forge:analyze <topic>`
- Nothing to clean → say so; suggest `--list` if they want to see what is already archived.
