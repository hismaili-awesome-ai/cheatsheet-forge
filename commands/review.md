---
description: Adversarially audit a cheat sheet against its raw source dumps
argument-hint: <topic>
---

Audit the cheat sheet for topic **$ARGUMENTS**.

Dispatch the `cheatsheet-forge:reviewer` agent. It must read `_sources/$ARGUMENTS/` directly and build its own picture of the source before opening `$ARGUMENTS/$ARGUMENTS.md`.

Do not summarise the source material for it, do not tell it what the writer did or intended, and do not pass along any prior review. A summary is exactly what makes this review fail — it must re-derive.

Relay findings verbatim, blocking first, keeping confirmed defects separate from open questions. State the coverage numbers and the PASS / BLOCKED verdict.

If it returns open questions under mandate 4 (upstream accuracy), present them as questions for the user to answer — never act on them yourself. Commands in the dumps ran successfully on real systems; documentation disagreeing with them is a question, not a defect.

## Next step

Close by telling the user what to run next, keyed to the verdict:

- **PASS** → `/cheatsheet-forge:publish <topic>`
- **PASS with open questions** → list the questions, note they are the user's to resolve, and give the `/publish` command. Mandate-4 questions never block publication.
- **BLOCKED** → state exactly what must change, then `/cheatsheet-forge:write <topic>` to regenerate (if the fault is in the writing) or `/cheatsheet-forge:analyze <topic>` (if the fault is in the extraction — a missing command, a bad parameterisation, a leak that should have been scrubbed). Re-review after.

**Never suggest publishing a BLOCKED topic**, and never offer a way around the verdict. A blocked review means the content is wrong, not that the gate is inconvenient.

If a leak was found, also flag that the analyst's lint should have caught it and say the profile or lint needs strengthening — the fix belongs upstream.
