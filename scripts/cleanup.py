#!/usr/bin/env python3
"""Retire a topic's working files after it has been published.

    cleanup.py <topic>             archive dumps, delete commands.yml  (default, reversible)
    cleanup.py <topic> --restore   move the newest archive back
    cleanup.py <topic> --purge     PERMANENTLY delete dumps (irreversible)
    cleanup.py --list              show what is archived

_sources/ is gitignored and local-only, so a deleted dump is gone for good — there
is no git history to recover it from. Archiving is therefore the default and purge
must always be asked for explicitly.

commands.yml is deleted rather than archived: it is fully regenerable from the
dumps by re-running /analyze. The manifest is kept — it is tiny, and losing it
makes an already-generated file look hand-written on the next pass.
"""
import pathlib
import shutil
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "_sources"


def dumps_in(d):
    return sorted(p for p in d.glob("*")
                  if p.is_file() and p.name not in ("commands.yml", ".forge-manifest.json"))


def do_list():
    found = False
    for arch in sorted(SRC.glob("*/.archive/*")):
        if arch.is_dir():
            found = True
            print(f"  {arch.relative_to(ROOT)}  ({len(list(arch.glob('*')))} files)")
    if not found:
        print("  nothing archived")
    return 0


def restore(topic):
    archives = sorted((SRC / topic / ".archive").glob("*"))
    if not archives:
        print(f"no archive for '{topic}'")
        return 1
    newest = archives[-1]
    for f in newest.glob("*"):
        shutil.move(str(f), str(SRC / topic / f.name))
        print(f"  restored {f.name}")
    newest.rmdir()
    print(f"restored from {newest.name} — re-run /cheatsheet-forge:analyze {topic}")
    return 0


def clean(topic, purge=False):
    d = SRC / topic
    if not d.exists():
        print(f"no sources for '{topic}'")
        return 1

    md = ROOT / topic / f"{topic}.md"
    if not md.exists():
        print(f"WARNING: {topic}/{topic}.md does not exist — nothing was ever produced "
              f"from these dumps. Cleaning now discards unused source material.")

    files = dumps_in(d)
    cy = d / "commands.yml"

    if purge:
        print(f"PURGE — permanently deleting {len(files)} dump(s) for '{topic}':")
        for f in files:
            print(f"  rm {f.name}")
            f.unlink()
    elif files:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        dest = d / ".archive" / stamp
        dest.mkdir(parents=True, exist_ok=True)
        print(f"archiving {len(files)} dump(s) to {dest.relative_to(ROOT)}/:")
        for f in files:
            shutil.move(str(f), str(dest / f.name))
            print(f"  {f.name}")
    else:
        print(f"no dumps to archive for '{topic}'")

    if cy.exists():
        cy.unlink()
        print("  deleted commands.yml (regenerable via /analyze)")

    if not purge and files:
        print(f"\nreversible: python3 cheatsheet-forge/scripts/cleanup.py {topic} --restore")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(2)
    if args[0] == "--list":
        sys.exit(do_list())
    topic, flags = args[0], set(args[1:])
    if "--restore" in flags:
        sys.exit(restore(topic))
    sys.exit(clean(topic, purge="--purge" in flags))
