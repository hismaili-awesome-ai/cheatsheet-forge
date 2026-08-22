#!/usr/bin/env python3
"""Verify every command in a topic file traces to its commands.yml.

    check-provenance.py <topic> [--strict]

lint-commands.py validates commands.yml. This validates the DOCUMENT against it,
closing the gap that let a writer read an unaccounted source file directly and
ship 12 commands that never passed the analyst's schema, leak or destructiveness
checks.

If the topic has no commands.yml the file is hand-authored and is skipped --
this checks pipeline output, not everything that is a markdown file.

Matching is order-insensitive: `oc -n <NS> get X` and `oc get X -n <NS>` are the
same command, and a document that reorders flags is not lying about provenance.
A doc command that is a *generalisation* of a source command -- <VERB> standing
where the dump had `patch` -- is reported separately: it is not an invention,
but it is a claim the source does not support and only the author can judge it.

Exit 0 = every command accounted for. Exit 1 = orphans (or, with --strict,
generalisations too).
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import forgeconfig as fc          # noqa: E402

import re

try:
    import yaml
except ImportError:
    print("PyYAML required: pip3 install pyyaml")
    sys.exit(2)

# Placeholder vocabulary differs harmlessly (<NS> vs <NAMESPACE>), so compare on
# structure: collapse every placeholder and shell var to a single token.
NORM = [
    (re.compile(r"<[^>]+>"), "\x00"),
    (re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"), "\x00"),
    (re.compile(r"\s+"), " "),
]


PLACEHOLDER = re.compile(r"^(?:<[^>]+>|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)$")


def norm(cmd):
    s = cmd.strip().rstrip("\\").strip()
    for pat, rep in NORM:
        s = pat.sub(rep, s)
    return s


def toks(cmd):
    """Normalised tokens. Placeholders collapse to a single wildcard token so
    <NS> and $NAMESPACE compare equal."""
    return tuple(norm(t) for t in cmd.strip().rstrip("\\").split() if t)


def bag(cmd):
    return tuple(sorted(toks(cmd)))


def generalises(doc_cmd, src_cmd):
    """True when doc_cmd is src_cmd with one or more literals widened into
    placeholders -- same shape, strictly less specific."""
    d, s = list(toks(doc_cmd)), list(toks(src_cmd))
    if len(d) != len(s) or not d:
        return False
    remaining, wildcards = list(s), 0
    for tok in d:
        if tok == "\x00":
            wildcards += 1
            continue
        if tok in remaining:
            remaining.remove(tok)
        else:
            return False
    return len(remaining) == wildcards and wildcards > 0


# Shell control-flow fragments are not commands.
KEYWORDS = {"done", "do", "fi", "then", "else", "esac", "}", "{", "))"}
# A command deliberately shown as WRONG is documentation, not a claim of provenance.
COUNTEREXAMPLE = re.compile(r"(?i)\b(wrong|don't|do not|never|bad|avoid|instead of)\b")


def doc_commands(md_path):
    """Yield (line_no, command) for real commands in bash blocks.

    Skips shell keywords, and skips any command sitting under a comment that
    marks it as a counter-example -- the exception sections deliberately show
    the wrong form beside the right one.
    """
    out, inside, counter = [], False, False
    for i, line in enumerate(md_path.read_text().splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            inside = s.startswith(("```bash", "```sh", "```shell"))
            counter = False
            continue
        if not inside:
            continue
        if not s:
            counter = False
            continue
        if s.startswith("#"):
            counter = bool(COUNTEREXAMPLE.search(s))
            continue
        if s in KEYWORDS or s.split()[0] in KEYWORDS:
            continue
        if counter:
            continue
        # Join backslash-continued lines into the single command they are.
        if out and out[-1][1].rstrip().endswith("\\"):
            prev_i, prev = out[-1]
            out[-1] = (prev_i, prev.rstrip().rstrip("\\").strip() + " " + s)
            continue
        out.append((i, s))
    return out


def main(topic, strict=False):
    cfg = fc.require()
    topic = cfg.canonical(topic)
    md = cfg.topic_md(topic)
    cy = cfg.commands_yml(topic)

    if not md.exists():
        print(f"{topic}: no document at {cfg.topic_md_rel(topic)}")
        return 1
    if not cy.exists():
        print(f"{topic}: no commands.yml — hand-authored, skipping")
        return 0

    doc = yaml.safe_load(cy.read_text()) or {}
    sources, exact, bags = [], set(), set()
    for e in doc.get("commands") or []:
        for field in ("command", "verbatim"):
            for line in str(e.get(field, "")).splitlines():
                if line.strip():
                    sources.append(line)
                    exact.add(norm(line))
                    bags.add(bag(line))

    emitted = doc_commands(md)
    orphans, widened = [], []
    for i, c in emitted:
        if norm(c) in exact or bag(c) in bags:
            continue
        src = next((s for s in sources if generalises(c, s)), None)
        (widened if src else orphans).append((i, c, src))

    print(f"{topic}: {len(emitted)} commands in document, "
          f"{len(doc.get('commands') or [])} entries in commands.yml")

    if widened:
        print(f"\nGENERALISED — the document is less specific than the source "
              f"({len(widened)}). Not inventions; confirm each is a claim the "
              f"dump supports:")
        for i, c, src in widened:
            print(f"  {cfg.topic_md_rel(topic)}:{i}  {c[:88]}")
            print(f"    source: {src.strip()[:88]}")

    if orphans:
        print(f"\nORPHANS — present in the document, absent from commands.yml:")
        for i, c, _ in orphans:
            print(f"  {cfg.topic_md_rel(topic)}:{i}  {c[:88]}")
        print(f"\nFAIL: {len(orphans)} unaccounted command(s). Either add entries "
              f"via /analyze, or remove them from the document.")
        return 1
    if widened and strict:
        print(f"\nFAIL (--strict): {len(widened)} generalisation(s).")
        return 1
    print(f"PASS: every command traces to commands.yml"
          + (f" ({len(widened)} generalised — listed above)" if widened else ""))
    return 0


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not a:
        print(__doc__); sys.exit(2)
    sys.exit(main(a[0], strict="--strict" in sys.argv))
