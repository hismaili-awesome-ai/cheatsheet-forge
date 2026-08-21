#!/usr/bin/env python3
"""Lint a commands.yml before it leaves the analyst.

Checks schema, provenance, and leaks in BOTH the `command` and `verbatim`
fields. Reuses the write guard's patterns so there is one source of truth for
what counts as a secret.

The point is shift-left: anything caught here is a cheap fix at extraction
time, instead of an expensive reviewer finding after a whole doc is written.

    python3 lint-commands.py _sources/<topic>/commands.yml

Exit 0 = clean. Exit 1 = problems, listed on stdout.
"""
import importlib.util
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
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

# Client/employer identifiers seen in this project's dumps. Extend as needed.
NAMED_ENTITIES = re.compile(r"(?i)\b(loreal|l'oreal|admin\.partner|compass-[a-z0-9-]+)\b")


def scan(text):
    """Return [(severity, name, fragment)] for a single field value."""
    out = []
    for name, pattern, _hint in guard.SECRETS:
        for m in re.finditer(pattern, text):
            frag = m.group(0)
            if guard.SAFE_MARKERS.search(frag):
                continue
            sev = "LEAK" if name in CREDENTIAL else ("IDENTITY" if name in IDENTITY else "LEAK")
            out.append((sev, name, frag[:60]))
    for m in NAMED_ENTITIES.finditer(text):
        out.append(("IDENTITY", "Client/employer identifier", m.group(0)))
    return out


def main(path):
    p = pathlib.Path(path)
    if not p.exists():
        print(f"not found: {p}")
        return 1
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
        repo_root = base.parent.parent
        src = next((cand for cand in (base / fname, repo_root / fname) if cand.exists()), None)
        if not fname or src is None:
            problems.append(f"  {cid}: source_ref points at missing file '{fname}'")
        elif not lineno.isdigit() or not (1 <= int(lineno) <= len(src.read_text().splitlines())):
            problems.append(f"  {cid}: source_ref line '{lineno}' out of range for {fname}")

        for field in ("command", "verbatim"):
            for sev, name, frag in scan(str(c.get(field, ""))):
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
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "commands.yml"))
