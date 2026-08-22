---
description: Run the full analyse -> write -> review pipeline for one topic, then stop at the human gate
argument-hint: <topic>
---

**Requires an initialised repository.** If `.cheatsheet-repo.yml` is absent and `$CHEATSHEET_REPO` is unset, stop and tell the user to run `/cheatsheet-forge:init` first — the scripts exit 2 with that message anyway, and every path below is resolved from that config, not assumed.

Arguments: `$ARGUMENTS`. The first token is the topic; anything after it is an inline dump — write it to `<sources_dir>/<topic>/inline-$(date +%Y-%m-%d-%H%M).txt` first, exactly as `/analyze` does. Never treat the whole argument string as a path.

Verify `<sources_dir>/<topic>/` exists and is non-empty. If not, stop and say what is needed.

Then call the **Workflow** tool with a script that runs three phases in strict order, passing the topic through `args`:

1. **Analyse** — one `cheatsheet-forge:analyst` agent producing `commands.yml`. If it reports zero entries, stop the workflow and return that fact.
2. **Write** — one `cheatsheet-forge:writer` agent producing the topic file from that file.
3. **Review** — one `cheatsheet-forge:reviewer` agent, prompted to read `<sources_dir>/<topic>/` first and to receive **no** description of what phases 1 and 2 did. Return its findings and verdict as structured output.

The phases are strictly sequential — each depends on the previous one's artifact, so use plain sequential `agent()` calls, not `parallel()`.

The pipeline **stops at review**. It does not publish, and it does not fix what the review found. Present the verdict and findings to the user and let them decide: fix and re-run, or `/publish <topic>`.

## Next step

The pipeline stops at the review gate. Close by telling the user what follows, keyed to the verdict:

- **PASS** → `/cheatsheet-forge:publish <topic>`
- **PASS with open questions** → surface the questions, then give the `/publish` command.
- **BLOCKED** → name what must change, then `/cheatsheet-forge:write <topic>` or `/cheatsheet-forge:analyze <topic>` depending on whether the fault is in the writing or the extraction, and `/cheatsheet-forge:review <topic>` after.

Never suggest publishing a BLOCKED topic, and never offer to bypass the gate.
