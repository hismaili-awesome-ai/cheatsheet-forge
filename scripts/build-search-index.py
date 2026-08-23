#!/usr/bin/env python3
"""Generate the guard search index for the documentation site.

    build-search-index.py [--check]

Reads every tech-profiles/*.yml and rewrites the JSON payload embedded in
docs/index.html between the GUARD-INDEX markers. The site therefore searches
what the guard actually enforces, and cannot drift from it: the only way to
change the index is to change a profile.

The payload is inlined rather than fetched so the page stays a single
self-contained file that works from file:// as well as over HTTP.

  --check   exit 3 if the embedded index is stale, writing nothing. For CI.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import forgeconfig as fc          # noqa: E402

ROOT = HERE.parent
PAGE = ROOT / "docs" / "index.html"
START = "<!-- GUARD-INDEX:START -->"
END = "<!-- GUARD-INDEX:END -->"

# Binaries the guard treats as universal: they belong to no single technology,
# so listing them as owned would be a lie. Kept in step with hooks/guard.py.
UNIVERSAL_NOTE = "universal — never a boundary violation"


def build():
    """Return the index as a plain dict, ready to serialise."""
    profiles = []
    binaries = {}          # binary -> [topics]
    destructive = []
    footguns = []

    for path in sorted((ROOT / "tech-profiles").glob("*.yml")):
        if path.name.startswith("_"):
            continue
        data = fc.load_yaml(path) or {}
        tech = str(data.get("tech", "") or path.stem).lower()

        bins = [str(b) for b in (data.get("detect_binaries") or [])]
        for b in bins:
            binaries.setdefault(b, [])
            if tech not in binaries[b]:
                binaries[b].append(tech)

        dpats = []
        for entry in (data.get("destructive_patterns") or []):
            if not isinstance(entry, dict):
                continue
            pat = str(entry.get("pattern", "")).strip()
            con = str(entry.get("consequence", "")).strip()
            if not pat:
                continue
            dpats.append({"pattern": pat, "consequence": con})
            destructive.append({"tech": tech, "pattern": pat, "consequence": con})

        fgs = []
        for entry in (data.get("footguns") or []):
            if isinstance(entry, dict):
                text = str(entry.get("note") or entry.get("footgun") or
                           next(iter(entry.values()), "")).strip()
            else:
                text = str(entry).strip()
            if text:
                fgs.append(text)
                footguns.append({"tech": tech, "text": text})

        docs = [str(d) for d in (data.get("authoritative_docs") or [])]

        # Subcommand-decided ownership: `expo build:android` is mobile,
        # `expo build:web` is web. Surfaced so the index explains the split
        # rather than showing one binary owned by two topics with no reason.
        subs = []
        for binary, mapping in (data.get("subcommand_owners") or {}).items():
            for keyword, owner in (mapping or {}).items():
                subs.append({"binary": str(binary), "keyword": str(keyword),
                             "owner": str(owner).lower()})

        profiles.append({
            "tech": tech,
            "file": f"tech-profiles/{path.name}",
            "binaries": bins,
            "destructive": dpats,
            "footguns": fgs,
            "docs": docs,
            "subcommands": subs,
        })

    records = []
    for binary, owners in sorted(binaries.items()):
        records.append({
            "kind": "binary",
            "title": binary,
            "tech": owners,
            "body": ("owned by " + " and ".join(owners)) if len(owners) > 1
                    else "owned by " + owners[0],
            "shared": len(owners) > 1,
        })
    for d in destructive:
        records.append({
            "kind": "destructive",
            "title": d["pattern"],
            "tech": [d["tech"]],
            "body": d["consequence"],
        })
    for f in footguns:
        records.append({
            "kind": "footgun",
            "title": f["text"],
            "tech": [f["tech"]],
            "body": "",
        })

    gaps = sorted(p["tech"] for p in profiles if not p["destructive"])

    return {
        "generated_from": "tech-profiles/*.yml",
        "counts": {
            "profiles": len(profiles),
            "binaries": len(binaries),
            "destructive": len(destructive),
            "footguns": len(footguns),
        },
        "gaps": gaps,
        "profiles": profiles,
        "records": records,
        "universalNote": UNIVERSAL_NOTE,
    }


def render(index):
    payload = json.dumps(index, indent=1, sort_keys=False, ensure_ascii=False)
    # </script> inside a JSON string would close the host element early.
    payload = payload.replace("</", "<\\/")
    return (f'{START}\n<script id="guard-index" type="application/json">\n'
            f'{payload}\n</script>\n{END}')


def main(argv):
    if not PAGE.exists():
        print(f"missing {PAGE}", file=sys.stderr)
        return 1

    html = PAGE.read_text()
    if START not in html or END not in html:
        print(f"markers not found in {PAGE.name}; expected {START} ... {END}",
              file=sys.stderr)
        return 1

    index = build()
    block = render(index)
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    updated = pattern.sub(lambda _m: block, html, count=1)

    c = index["counts"]
    summary = (f"{c['profiles']} profiles · {c['binaries']} binaries · "
               f"{c['destructive']} destructive patterns · {c['footguns']} footguns")

    if "--check" in argv:
        if updated != html:
            print(f"search index is STALE — run: python3 scripts/build-search-index.py\n  {summary}",
                  file=sys.stderr)
            return 3
        print(f"search index is current  ({summary})")
        return 0

    if updated == html:
        print(f"search index unchanged   ({summary})")
        return 0

    PAGE.write_text(updated)
    print(f"search index rebuilt     ({summary})")
    if index["gaps"]:
        print("  no destructive patterns yet: " + ", ".join(index["gaps"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
