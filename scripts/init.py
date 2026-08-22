#!/usr/bin/env python3
"""Initialise a repository for cheatsheet-forge. Mandatory before anything else.

    init.py [PATH] [--layout nested|flat] [--sources-dir D] [--site-dir D]
            [--redact NAME]... [--force]

Writes .cheatsheet-repo.yml, creates the sources directory, adds the gitignore
entries that keep raw dumps out of git, and records $CHEATSHEET_REPO in
.claude/settings.local.json so hooks and scripts resolve the same root no
matter what directory they are invoked from.

Existing content is inspected, never modified: layout and topics are inferred
from what is already on disk and reported for confirmation.
"""
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import forgeconfig as fc          # noqa: E402

GITIGNORE_BLOCK = """
# -- cheatsheet-forge
# Raw command dumps: contain tokens, passwords, home paths, client names.
# NEVER commit. Agents read these locally; commands.yml is the committed artifact.
{sources}/

# Generated site
{site}/dist/
{site}/node_modules/
{site}/.astro/

# CHEATSHEET_REPO is an absolute path, so this file is machine-specific.
.claude/settings.local.json
"""

TEMPLATE = """\
# cheatsheet-forge — repository configuration
# Created by /cheatsheet-forge:init. Commit this file: it is what makes the
# pipeline reproducible for anyone who clones the repo.
version: 1

# Where raw terminal dumps live. Gitignored — they hold unsanitised secrets.
sources_dir: {sources_dir}

# Where the generated documentation site is built.
site_dir: {site_dir}

# nested -> <topic>/<topic>.md      flat -> <topic>.md
layout: {layout}

# Topics the pipeline manages. Leave empty to discover them from sources_dir.
topics:{topics}

# Directory name -> canonical topic, for directories that do not match the
# topic they hold (a typo you would rather not rename, a legacy name).
aliases:{aliases}

# Redaction the write guard enforces, on top of its built-in secret patterns.
#
# named_entities: literal names that identify a person, employer, client or
# internal product. The guard blocks any write containing one. Keep them here
# rather than in the plugin: this file is yours, the plugin is published.
redact:
  named_entities: []
  extra_patterns: []

# unknown_topic: what to do with a write that does not match a known topic.
#   warn  — scan it for secrets, skip the topic-boundary check (default)
#   deny  — refuse it until the topic is declared above
#   allow — scan for secrets only, never mention it
guard:
  unknown_topic: {unknown_topic}
"""


def detect(root, sources_dir):
    """Infer layout, topics and unmapped directories from existing content."""
    skip = {".git", ".idea", ".vscode", ".claude", ".claude-plugin",
            "node_modules", sources_dir, "site", "dist"}
    nested, flat, unmapped = [], [], []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name in skip or d.name.startswith("."):
            continue
        mds = sorted(d.glob("*.md"))
        if not mds:
            continue
        if (d / f"{d.name}.md").exists():
            nested.append(d.name.lower())
        else:
            unmapped.append((d.name, [m.name for m in mds]))
    for f in sorted(root.glob("*.md")):
        if f.name.lower() not in ("readme.md", "claude.md", "license.md", "contributing.md"):
            flat.append(f.stem.lower())
    return nested, flat, unmapped


def yaml_list(items, indent="  "):
    if not items:
        return " []"
    return "\n" + "\n".join(f"{indent}- {i}" for i in items)


def yaml_map(pairs, indent="  "):
    if not pairs:
        return " {}"
    return "\n" + "\n".join(f"{indent}{k}: {v}" for k, v in pairs)


def write_gitignore(root, sources, site):
    gi = root / ".gitignore"
    existing = gi.read_text() if gi.exists() else ""
    if f"{sources}/" in existing:
        return "already covers " + sources
    gi.write_text(existing.rstrip("\n") + "\n" +
                  GITIGNORE_BLOCK.format(sources=sources, site=site))
    return "appended"


def write_settings(root):
    """Record the repo root so hooks resolve it regardless of cwd.

    settings.local.json rather than settings.json: the value is an absolute
    path and therefore machine-specific, so it must not be committed.
    """
    d = root / ".claude"
    d.mkdir(exist_ok=True)
    f = d / "settings.local.json"
    try:
        data = json.loads(f.read_text()) if f.exists() else {}
    except Exception:
        return "left alone (unparseable — set CHEATSHEET_REPO yourself)"
    env = data.setdefault("env", {})
    if env.get("CHEATSHEET_REPO") == str(root):
        return "already set"
    env["CHEATSHEET_REPO"] = str(root)
    f.write_text(json.dumps(data, indent=2) + "\n")
    return "set"


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = [a for a in argv if a.startswith("--")]

    def opt(name, default):
        for i, f in enumerate(flags):
            if f == f"--{name}" and i + 1 < len(flags):
                return flags[i + 1]
            if f.startswith(f"--{name}="):
                return f.split("=", 1)[1]
        for i, a in enumerate(argv):
            if a == f"--{name}" and i + 1 < len(argv):
                return argv[i + 1]
        return default

    root = pathlib.Path(args[0] if args else os.getcwd()).expanduser().resolve()
    force = "--force" in flags
    sources_dir = opt("sources-dir", "_sources")
    site_dir = opt("site-dir", "site")
    redact = [argv[i + 1] for i, a in enumerate(argv) if a == "--redact" and i + 1 < len(argv)]

    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1

    cfg_path = root / fc.CONFIG_NAME
    if cfg_path.exists() and not force:
        print(f"{fc.CONFIG_NAME} already exists at {root}.\n"
              f"Edit it directly, or re-run with --force to regenerate.")
        return 1

    nested, flat, unmapped = detect(root, sources_dir)
    layout = opt("layout", None) or ("flat" if (flat and not nested) else "nested")
    topics = sorted(set(nested if layout == "nested" else flat))

    alias_pairs = []
    for name, mds in unmapped:
        guess = pathlib.Path(mds[0]).stem.lower()
        alias_pairs.append((name.lower(), guess))

    cfg_path.write_text(TEMPLATE.format(
        sources_dir=sources_dir,
        site_dir=site_dir,
        layout=layout,
        topics=yaml_list(topics),
        aliases=yaml_map(alias_pairs),
        unknown_topic="warn",
    ))

    (root / sources_dir).mkdir(exist_ok=True)
    for t in topics:
        (root / sources_dir / t).mkdir(exist_ok=True)

    gi = write_gitignore(root, sources_dir, site_dir)
    st = write_settings(root)

    if redact:
        text = cfg_path.read_text().replace(
            "  named_entities: []",
            "  named_entities:\n" + "\n".join(f"    - {r}" for r in redact))
        cfg_path.write_text(text)

    print(f"initialised {root}\n")
    print(f"  {fc.CONFIG_NAME:26} written")
    print(f"  {sources_dir + '/':26} created ({len(topics)} topic dir(s))")
    print(f"  .gitignore                 {gi}")
    print(f"  .claude/settings.local.json CHEATSHEET_REPO {st}")
    print(f"\n  layout   {layout}  ->  " +
          ("<topic>/<topic>.md" if layout == "nested" else "<topic>.md"))
    print(f"  topics   {', '.join(topics) or '(none yet)'}")
    if alias_pairs:
        print("\n  These directories do not match the layout. init guessed an alias for\n"
              "  each — check them, they are how the guard identifies the topic:")
        for name, guess in alias_pairs:
            print(f"    {name}/ -> {guess}")
    if not redact:
        print("\n  redact.named_entities is empty. If these sheets come from client or\n"
              "  employer systems, add those names now — the guard blocks any write\n"
              "  containing one, and this file never leaves your repo.")
    print(f"\n  For shells outside Claude Code:  export CHEATSHEET_REPO={root}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
