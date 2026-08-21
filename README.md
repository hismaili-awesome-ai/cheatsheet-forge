# cheatsheet-forge

Turns raw terminal dumps into provenance-checked cheat sheets, then into a docs site.

```
_sources/<topic>/*.txt          (gitignored — raw, may contain secrets)
        │
        ├─ /analyze  → analyst   → _sources/<topic>/commands.yml   (structured, scrubbed)
        ├─ /write    → writer    → <topic>/<topic>.md              (the cheat sheet)
        ├─ /review   → reviewer  → findings + PASS | BLOCKED
        │                          ▣ human gate
        └─ /publish  → publisher → site/  (local preview only — you push)

/forge <topic>  runs analyze → write → review, then stops at the gate.
/cleanup <topic> archives dumps once published (reversible; --purge is not).
```

Each command ends by naming the next one to run, keyed to its outcome. A BLOCKED
review never suggests publishing — it points back at `/write` or `/analyze`
depending on whether the fault is in the writing or the extraction.

## Why it is shaped this way

Every rule here exists because the failure it prevents actually happened while building
this repo's OpenShift sheet:

| Failure observed | Control |
|---|---|
| Writer invented 4 commands that were never in the dump | Provenance: no `source_ref`, no output |
| Writer silently dropped 10 of ~60 source commands | Reviewer diffs source↔doc in both directions |
| Reviewer worked from a summary → found 1 of 9 defects | Reviewer reads raw source first, never a summary |
| Two working commands were "corrected" into wrongness | Flag-don't-fix; mandate 4 never blocks, never edits |
| A dump for another topic overwrote `openshift.md` | Topic-boundary hook, deterministic |
| Redaction applied inconsistently, secrets survived | Secret-scan hook, deterministic |

The last two are hooks rather than instructions, because a model can reason its way around
an instruction and cannot reason its way around a `PreToolUse` deny.

## Sanitising happens at extraction

The analyst is the only agent that reads raw source, so every credential and identifier
dies there rather than downstream. Three tiers:

| Tier | Examples | Treatment |
|---|---|---|
| Credentials | tokens, JWTs, private keys, passwords, secret-ids | replaced everywhere, never reproduced |
| Identity | home paths, usernames, client/employer names, private IPs, internal hosts | replaced with placeholders |
| Specifics | canonical namespaces, versions, ports | parameterised in `command`, kept real in `verbatim` |

Both `command` and `verbatim` must be clean of tiers 1 and 2 — `verbatim` is a readable
example, not an audit log; the unmodified truth stays in the dump that `source_ref` points at.

The analyst must pass `scripts/lint-commands.py` before reporting done:

```bash
python3 cheatsheet-forge/scripts/lint-commands.py _sources/<topic>/commands.yml
```

It validates schema, resolves every `source_ref` to a real file and line, and scans both
fields using the write guard's own patterns — one source of truth for what counts as a secret.

This is why the reviewer's secrets mandate says *expect to find nothing*: two layers stand in
front of it, so its budget goes to provenance and destructive-command judgement instead, where
a model is actually irreplaceable. A leak reaching the reviewer is reported as an upstream
process failure, not just a defect in the file.

## Existing content is never destroyed

The writer regenerates topic files wholesale, so the pipeline has to know whether a file
was its own output or somebody's hand-written work. `scripts/manifest.py` stores a hash of
what was last generated:

| Status | Meaning | Effect |
|---|---|---|
| `absent` | no topic file yet | write freely |
| `unmodified` | matches our last output | regenerate wholesale |
| `virgin` | exists but predates the pipeline | analyst must ingest it first |
| `modified` | hand-edited since we generated it | analyst must ingest it first |

On `virgin` or `modified` the **writer refuses to run**. The analyst reads the existing file,
absorbs any command not already covered (tagged `origin: pre-existing`, with a `source_ref`
pointing into the `.md`), and only then may the writer regenerate. Non-command content —
hand-written prose, tables — cannot be represented in `commands.yml`, so the analyst reports
what will be lost rather than dropping it silently.

The manifest lives in gitignored `_sources/`, so a fresh clone reads `virgin` and errs toward
preserving content rather than destroying it.

## Cleanup

`/cleanup <topic>` archives dumps to `_sources/<topic>/.archive/<timestamp>/` and deletes
`commands.yml` (regenerable via `/analyze`). Reversible with `--restore`.

`--purge` permanently deletes dumps and is never taken on an agent's initiative — `_sources/`
is gitignored and local-only, so there is no git history to recover from.

Cleanup is a separate user-run command, deliberately not part of the reviewer: the reviewer
runs *before* the human gate, and a BLOCKED verdict is precisely when the raw dumps are most
needed to act on it.

## Guardrails

| Rule | Enforced by | Blocking |
|---|---|---|
| No secrets, PII, home paths, private IPs, internal DNS | `hooks/guard.py` | yes |
| Commands stay in their own topic file | `hooks/guard.py` | yes |
| Every command traces to a dump line | reviewer | yes |
| Destructive commands carry accurate warnings | reviewer | yes |
| No agent alters a working command | all agents + reviewer | yes |
| Upstream documentation accuracy | reviewer | **no — reports only** |
| Nothing reaches a remote | publisher has no push capability | yes |

## Agents

| Agent | Model | Reads | Writes | Asks you |
|---|---|---|---|---|
| analyst | sonnet/high | raw dumps | `commands.yml` | ambiguous command intent |
| writer | sonnet | `commands.yml` | `<topic>.md` | taxonomy splits |
| reviewer | **opus/high** | raw dumps + `.md` | nothing | never, by design |
| publisher | sonnet/high | reviewed `.md` | `site/` | structure, tone, scope |

The reviewer is the one place not to economise — it is the proven failure point.

## Adding a technology

Drop dumps in `_sources/<topic>/` and run `/forge <topic>`. Unknown technologies work
without a profile: the reviewer finds the official docs, verifies against them, and reports
at reduced confidence plus a proposed profile. Add it to `tech-profiles/<tech>.yml` to make
the next review sharper.

## Testing the guard

```bash
python3 -c "import json;print(json.dumps({'tool_name':'Write','tool_input':{'file_path':'openshift/openshift.md','content':open('FILE').read()}}))" \
  | python3 cheatsheet-forge/hooks/guard.py
```
Output is empty when allowed, and a JSON deny payload when blocked.
