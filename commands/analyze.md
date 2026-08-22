---
description: Extract a structured, provenance-tagged commands.yml from a topic's raw dumps
argument-hint: <topic> [paste a dump inline, optional]
---

**Requires an initialised repository.** If `.cheatsheet-repo.yml` is absent and `$CHEATSHEET_REPO` is unset, stop and tell the user to run `/cheatsheet-forge:init` first — the scripts exit 2 with that message anyway, and every path below is resolved from that config, not assumed.

Arguments: `$ARGUMENTS`

**Parse them first.** The first whitespace-delimited token is the topic. Everything after it — if anything — is a dump the user pasted inline. Never treat the whole argument string as a path; a pasted dump contains newlines and backticks and will produce a nonsense path if you do.

If an inline dump is present, write it verbatim to `<sources_dir>/<topic>/inline-$(date +%Y-%m-%d-%H%M).txt` before doing anything else. The configured sources directory is gitignored and exempt from the write guard, so raw unsanitised content is safe there — and only there.

Then confirm `<sources_dir>/<topic>/` exists and is non-empty. If it is empty and nothing was pasted, stop and tell the user what to put there: this pipeline is source-only and will not invent commands to fill a gap.

**Check the topic fits the content before dispatching.** Resolve the leading binary of each command (unwrapping `sudo`/`env`/`time`) and compare it against the topic. If the dump clearly belongs to a different technology than the topic named — `gem` in `linux`, `npm` in `openshift` — stop and ask the user where it belongs rather than filing it wrongly. The write guard will block it downstream regardless, so catching it here saves a wasted pass.

Then dispatch the `cheatsheet-forge:analyst` agent to read every dump in `<sources_dir>/<topic>/` and write `<sources_dir>/<topic>/commands.yml`.

Relay: entry count, uncertain entries, destructive entries, and any questions the analyst raised.

## Next step

Close by telling the user what to run next, as a copy-pasteable command:

- Entries written, lint clean → `/cheatsheet-forge:write <topic>`
- Zero entries, or the dump held nothing usable → no next command; say what source material is missing.
- Very few entries (one or two) → say so plainly and suggest holding until there is more material, rather than generating a page not worth having. Give the `/write` command anyway so it is theirs to choose.
- Topic mismatch, dump belongs elsewhere → `/cheatsheet-forge:analyze <correct-topic>` with the content re-routed.
- The analyst raised questions → answer those first; the next command comes after.
