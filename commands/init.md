---
description: Initialise a repository for cheatsheet-forge — required once before any other command
argument-hint: [path] [--layout nested|flat] [--force]
---

Initialise **$ARGUMENTS** (default: the current repository) for the forge.

This is mandatory and runs once. Nothing else in the pipeline works without it: the plugin carries no knowledge of your repository, so until this file exists there is no way to tell a topic file from any other markdown, and the write guard has no layout to reason about.

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init.py" [path] [flags]
```

It writes `.cheatsheet-repo.yml`, creates the sources directory, appends the gitignore entries that keep raw dumps out of git, and records `CHEATSHEET_REPO` in `.claude/settings.local.json` so hooks and scripts resolve the same root regardless of the directory they are invoked from.

**Existing content is inspected, never modified.** Layout and topics are inferred from what is already on disk. Report what it found back to the user — particularly:

- **The layout it chose.** `nested` (`<topic>/<topic>.md`) or `flat` (`<topic>.md`). If the repo is empty it guesses `nested`; say so, because changing it later means moving files.
- **Directories it could not map.** A directory whose markdown does not match its own name gets a guessed alias. Those guesses are how the guard identifies the topic, so they need the user's eye — a wrong alias means the boundary check silently protects the wrong file.
- **That `redact.named_entities` is empty.** If these sheets come from client or employer systems, those names belong there now. The guard blocks any write containing one, and the file never leaves their repo — which is exactly why the plugin itself must never contain such a name.

If `.cheatsheet-repo.yml` already exists, the script refuses rather than overwriting. Do not pass `--force` on your own initiative: it discards a config the user may have hand-tuned. Offer it, and let them ask.

## Next step

- Initialised, topics discovered → the repo is ready; suggest `/cheatsheet-forge:forge <topic>` for a topic that has dumps, or say what to drop in the sources directory first.
- Initialised, repo empty → tell them where to put dumps, then `/cheatsheet-forge:analyze <topic>`.
- Aliases guessed, or `named_entities` empty → raise those before suggesting anything else. They are cheap to fix now and expensive to discover later.
