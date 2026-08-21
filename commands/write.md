---
description: Generate a topic's cheat-sheet markdown from its commands.yml
argument-hint: <topic>
---

Write the cheat sheet for topic **$ARGUMENTS**.

Require `_sources/$ARGUMENTS/commands.yml`. If it is absent, stop and tell the user to run `/analyze $ARGUMENTS` first — the writer must not read raw dumps.

Dispatch the `cheatsheet-forge:writer` agent to produce `$ARGUMENTS/$ARGUMENTS.md`.

If the write guard blocks the agent, do not work around it: report what it caught and fix the underlying content.

Relay: sections, command count, destructive warnings added, exceptions explained.

## Next step

Close by telling the user what to run next:

- File written → `/cheatsheet-forge:review <topic>`

Always suggest the review. Never suggest `/publish` from here — nothing is publishable until it has a Reviewer PASS, and skipping straight there defeats the only quality gate in the pipeline.

If the write guard blocked the agent, the next step is fixing the flagged content and re-running `/cheatsheet-forge:write <topic>`, not working around the guard.
