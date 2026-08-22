---
description: Generate a topic's cheat-sheet markdown from its commands.yml
argument-hint: <topic>
---

**Requires an initialised repository.** If `.cheatsheet-repo.yml` is absent and `$CHEATSHEET_REPO` is unset, stop and tell the user to run `/cheatsheet-forge:init` first — the scripts exit 2 with that message anyway, and every path below is resolved from that config, not assumed.

Write the cheat sheet for topic **$ARGUMENTS**.

Require `<sources_dir>/$ARGUMENTS/commands.yml`. If it is absent, stop and tell the user to run `/analyze $ARGUMENTS` first — the writer must not read raw dumps.

Dispatch the `cheatsheet-forge:writer` agent to produce the topic file (`manifest.py` and the config decide its path — `<topic>/<topic>.md` under the default `nested` layout, `<topic>.md` when `flat`).

If the write guard blocks the agent, do not work around it: report what it caught and fix the underlying content.

Relay: sections, command count, destructive warnings added, exceptions explained.

## Next step

Close by telling the user what to run next:

- File written → `/cheatsheet-forge:review <topic>`

Always suggest the review. Never suggest `/publish` from here — nothing is publishable until it has a Reviewer PASS, and skipping straight there defeats the only quality gate in the pipeline.

If the write guard blocked the agent, the next step is fixing the flagged content and re-running `/cheatsheet-forge:write <topic>`, not working around the guard.
