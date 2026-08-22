#!/usr/bin/env python3
"""Lint a commands.yml before it leaves the analyst.

Checks schema, provenance, and leaks in BOTH the `command` and `verbatim`
fields. Reuses the write guard's patterns so there is one source of truth for
what counts as a secret.

The point is shift-left: anything caught here is a cheap fix at extraction
time, instead of an expensive reviewer finding after a whole doc is written.

    python3 lint-commands.py <topic>
    python3 lint-commands.py path/to/commands.yml

Exit 0 = clean. Exit 1 = problems, listed on stdout.
"""
import importlib.util
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import forgeconfig as fc                 # noqa: E402

_spec = importlib.util.spec_from_file_location("guard", HERE.parent / "hooks" / "guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)          # safe: guard.py only acts under __main__

try:
    import yaml
except ImportError:
    print("PyYAML required: pip3 install pyyaml")
    sys.exit(2)

REQUIRED = {"id", "command", "purpose", "category", "source_ref", "verbatim",
            "destructive", "uncertain"}

# Values that must never survive extraction, in any field.
CREDENTIAL = {"JWT / bearer token", "OpenShift session token", "Private key block",
              "AWS access key id", "GitHub token", "Vault token",
              "Literal bearer credential", "Hardcoded password/secret value"}
# Values that identify a person, employer, or private network.
IDENTITY = {"Absolute home directory", "Private IP address", "Internal cluster DNS"}

def named_entities(cfg):
    """Client, employer and internal product names come from the repo's own
    .cheatsheet-repo.yml, never from the plugin — the plugin is published, the
    config is not."""
    names = [re.escape(n) for n in cfg.named_entities() if n.strip()]
    if not names:
        return None
    return re.compile(r"(?i)(" + "|".join(names) + r")")


def scan(text, entities, extra):
    """Return [(severity, name, fragment)] for a single field value."""
    out = []
    for name, pattern, _hint in guard.SECRETS + extra:
        for m in re.finditer(pattern, text):
            frag = m.group(0)
            if guard.SAFE_MARKERS.search(frag):
                continue
            sev = "LEAK" if name in CREDENTIAL else ("IDENTITY" if name in IDENTITY else "LEAK")
            out.append((sev, name, frag[:60]))
    if entities:
        for m in entities.finditer(text):
            out.append(("IDENTITY", "Client/employer identifier", m.group(0)))
    return out


def main(target):
    cfg = fc.require()
    p = pathlib.Path(target)
    if not p.suffix:                      # a topic name, not a path
        p = cfg.commands_yml(cfg.canonical(target))
    if not p.is_absolute():
        p = (pathlib.Path.cwd() / p) if p.exists() else (cfg.root / p)
    if not p.exists():
        print(f"not found: {p}")
        return 1
    entities = named_entities(cfg)
    extra = [("Repo-configured secret pattern", pat, None) for pat in cfg.extra_patterns()]
    doc = yaml.safe_load(p.read_text()) or {}
    cmds = doc.get("commands") or []
    if not cmds:
        print(f"{p}: no commands — nothing to lint")
        return 1

    base = p.parent
    problems, warnings = [], []

    for i, c in enumerate(cmds):
        cid = c.get("id", f"<entry {i}>")

        missing = REQUIRED - set(c)
        if missing:
            problems.append(f"  {cid}: missing fields {sorted(missing)}")

        ref = str(c.get("source_ref", ""))
        fname, _, lineno = ref.rpartition(":")
        # A ref resolves either beside the dumps, or (for content ingested from an
        # existing topic file) relative to the repo root.
        src = next((cand for cand in (base / fname, cfg.root / fname) if cand.exists()), None)
        if not fname or src is None:
            problems.append(f"  {cid}: source_ref points at missing file '{fname}'")
        elif not lineno.isdigit() or not (1 <= int(lineno) <= len(src.read_text().splitlines())):
            problems.append(f"  {cid}: source_ref line '{lineno}' out of range for {fname}")

        for field in ("command", "verbatim"):
            for sev, name, frag in scan(str(c.get(field, "")), entities, extra):
                msg = f"  {cid}.{field}: {name} -> {frag}"
                (problems if sev == "LEAK" else warnings).append(msg)

    ids = [c.get("id") for c in cmds]
    for dup in {x for x in ids if ids.count(x) > 1}:
        problems.append(f"  duplicate id: {dup}")

    print(f"{p}: {len(cmds)} entries")
    if warnings:
        print("\nIDENTITY — parameterise these (they name a person, employer, or private network):")
        print("\n".join(sorted(set(warnings))))
    if problems:
        print("\nBLOCKING:")
        print("\n".join(sorted(set(problems))))
        print(f"\nFAIL: {len(set(problems))} blocking, {len(set(warnings))} identity")
        return 1
    if warnings:
        print(f"\nFAIL: {len(set(warnings))} identity leak(s) — scrub before reporting done")
        return 1
    print("PASS: schema, provenance and leak checks clean")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
