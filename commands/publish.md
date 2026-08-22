---
description: Build the Starlight docs site from reviewed cheat sheets and serve it locally
argument-hint: [topic|all]
---

**Requires an initialised repository.** If `.cheatsheet-repo.yml` is absent and `$CHEATSHEET_REPO` is unset, stop and tell the user to run `/cheatsheet-forge:init` first — the scripts exit 2 with that message anyway, and every path below is resolved from that config, not assumed.

Build the documentation site for **$ARGUMENTS** (default: all topics with a passing review).

Before dispatching, confirm every topic in scope has a Reviewer PASS. Skip any that do not and say which.

Dispatch the `cheatsheet-forge:publisher` agent to build into the configured `site_dir` and serve a local preview.

**Nothing is pushed.** The publisher has no push capability and must not attempt one. When it finishes, give the user the preview URL and state plainly that publishing is theirs to do by hand.

## Next step

The pipeline ends here — the remaining step is the user's, and you cannot do it.

Close with the local preview URL, then state plainly that publishing is a manual push they perform themselves, and show the commands for it (`git add` / `git commit` / `git push`) as text for them to run. Do not run them, and do not offer to.

If topics were skipped for want of a PASS, list them with `/cheatsheet-forge:review <topic>` so they can be brought up to standard.
