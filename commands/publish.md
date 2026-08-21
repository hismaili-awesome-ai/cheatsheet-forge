---
description: Build the Starlight docs site from reviewed cheat sheets and serve it locally
argument-hint: [topic|all]
---

Build the documentation site for **$ARGUMENTS** (default: all topics with a passing review).

Before dispatching, confirm every topic in scope has a Reviewer PASS. Skip any that do not and say which.

Dispatch the `cheatsheet-forge:publisher` agent to build into `site/` and serve a local preview.

**Nothing is pushed.** The publisher has no push capability and must not attempt one. When it finishes, give the user the preview URL and state plainly that publishing is theirs to do by hand.

## Next step

The pipeline ends here — the remaining step is the user's, and you cannot do it.

Close with the local preview URL, then state plainly that publishing is a manual push they perform themselves, and show the commands for it (`git add` / `git commit` / `git push`) as text for them to run. Do not run them, and do not offer to.

If topics were skipped for want of a PASS, list them with `/cheatsheet-forge:review <topic>` so they can be brought up to standard.
