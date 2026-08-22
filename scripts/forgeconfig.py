#!/usr/bin/env python3
"""Single source of truth for where a cheat-sheet repo lives and how it is laid out.

Every script and the write guard resolve paths through here, so the plugin
carries no knowledge of any particular repository. Nothing is hardcoded to a
topic list, a directory layout, or an employer's name.

Resolution order for the repo root:

  1. $CHEATSHEET_REPO                     — set by /cheatsheet-forge:init
  2. nearest ancestor holding .cheatsheet-repo.yml, walking up from cwd
  3. cwd                                  — unconfigured; require() refuses

Run `/cheatsheet-forge:init` in a repo to create the config. It is mandatory:
without it the pipeline has no way to tell a topic file from any other markdown,
and the guard would have to choose between blocking everything and nothing.

    python3 forgeconfig.py            # show resolved configuration
"""
import os
import pathlib
import re
import sys

CONFIG_NAME = ".cheatsheet-repo.yml"
PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE_DIR = PLUGIN_ROOT / "tech-profiles"

DEFAULTS = {
    "version": 1,
    "sources_dir": "_sources",
    "site_dir": "site",
    "layout": "nested",          # nested -> <topic>/<topic>.md ; flat -> <topic>.md
    "topics": [],                # empty -> discover from sources_dir
    "aliases": {},               # directory name -> canonical topic
    "redact": {"named_entities": [], "extra_patterns": []},
    "guard": {"unknown_topic": "warn"},   # warn | deny | allow
}


# --------------------------------------------------------------------------
# YAML loading. PyYAML when present; a deliberately small fallback otherwise,
# because the write guard is a blocking PreToolUse hook and must not depend on
# a pip install being present in whatever interpreter Claude Code invokes.
# --------------------------------------------------------------------------
def _flow_list(raw):
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    return [i.strip().strip("'\"") for i in inner.split(",") if i.strip()]


def _scalar(raw):
    v = raw.strip().strip("'\"")
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _mini_load(text):
    """Parse the subset this plugin's own config and profiles are written in:
    scalars, flow lists, block lists, and one level of nested mapping."""
    root = {}
    stack = [(-1, root)]
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        s = line.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if s.startswith("- "):
            if not isinstance(parent, list):
                continue
            parent.append(_scalar(s[2:]))
            continue

        m = re.match(r"^([A-Za-z_][\w.-]*)\s*:\s*(.*)$", s)
        if not m:
            continue
        key, rest = m.group(1), m.group(2)

        if rest.startswith("["):
            parent[key] = _flow_list(rest)
        elif rest.startswith("|") or rest.startswith(">"):
            block = []
            while i < len(lines) and (not lines[i].strip()
                                      or len(lines[i]) - len(lines[i].lstrip()) > indent):
                block.append(lines[i].strip())
                i += 1
            parent[key] = "\n".join(block).strip()
        elif rest:
            parent[key] = _scalar(rest)
        else:
            # A container: list if the next meaningful line is a "- " item.
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            child = [] if (j < len(lines) and lines[j].strip().startswith("- ")) else {}
            parent[key] = child
            stack.append((indent, child))
    return root


def load_yaml(path):
    try:
        import yaml
        return yaml.safe_load(path.read_text()) or {}
    except ImportError:
        return _mini_load(path.read_text())
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Repo resolution
# --------------------------------------------------------------------------
def find_root(start=None):
    """Return (root, configured). Never raises — callers decide how to react."""
    env = os.environ.get("CHEATSHEET_REPO")
    if env:
        p = pathlib.Path(env).expanduser().resolve()
        return p, (p / CONFIG_NAME).exists()
    here = pathlib.Path(start or pathlib.Path.cwd()).resolve()
    for cand in (here, *here.parents):
        if (cand / CONFIG_NAME).exists():
            return cand, True
    return here, False


def _merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, root, data, configured):
        self.root = root
        self.data = data
        self.configured = configured

    # -- layout ----------------------------------------------------------
    @property
    def sources(self):
        return self.root / self.data["sources_dir"]

    @property
    def site(self):
        return self.root / self.data["site_dir"]

    def topic_md(self, topic):
        if self.data.get("layout") == "flat":
            return self.root / f"{topic}.md"
        return self.root / topic / f"{topic}.md"

    def topic_md_rel(self, topic):
        return str(self.topic_md(topic).relative_to(self.root))

    def source_dir(self, topic):
        return self.sources / topic

    def manifest(self, topic):
        return self.source_dir(topic) / ".forge-manifest.json"

    def commands_yml(self, topic):
        return self.source_dir(topic) / "commands.yml"

    # -- topics ----------------------------------------------------------
    def canonical(self, name):
        aliases = {str(k).lower(): str(v).lower()
                   for k, v in (self.data.get("aliases") or {}).items()}
        return aliases.get(str(name).lower(), str(name).lower())

    def topics(self):
        """Declared topics, else discovered from the sources directory."""
        declared = [str(t).lower() for t in (self.data.get("topics") or [])]
        if declared:
            return sorted(set(declared))
        if not self.sources.exists():
            return []
        return sorted({d.name.lower() for d in self.sources.iterdir()
                       if d.is_dir() and not d.name.startswith("_")})

    def known_topics(self):
        """Every name that may legitimately appear as a topic directory,
        including aliases and every topic any tech profile claims."""
        names = set(self.topics())
        names |= {str(k).lower() for k in (self.data.get("aliases") or {})}
        names |= {str(v).lower() for v in (self.data.get("aliases") or {}).values()}
        names |= set(profile_topics())
        return names

    # -- redaction -------------------------------------------------------
    def named_entities(self):
        return [str(e) for e in (self.data.get("redact", {}).get("named_entities") or [])]

    def extra_patterns(self):
        return [str(p) for p in (self.data.get("redact", {}).get("extra_patterns") or [])]

    def unknown_topic_policy(self):
        return str(self.data.get("guard", {}).get("unknown_topic", "warn")).lower()


def load(start=None):
    root, configured = find_root(start)
    data = dict(DEFAULTS)
    if configured:
        data = _merge(DEFAULTS, load_yaml(root / CONFIG_NAME))
    return Config(root, data, configured)


MISSING = (
    "cheatsheet-forge is not initialised for this repository.\n\n"
    f"  No {CONFIG_NAME} found, and $CHEATSHEET_REPO is unset.\n\n"
    "Run /cheatsheet-forge:init once in the repository that holds your cheat\n"
    "sheets. It writes the config, wires $CHEATSHEET_REPO, and adds the\n"
    "gitignore entries that keep raw dumps out of git."
)


def require(start=None):
    """Load config or exit 2. Every entry point calls this — init is mandatory."""
    cfg = load(start)
    if not cfg.configured:
        print(MISSING, file=sys.stderr)
        sys.exit(2)
    return cfg


# --------------------------------------------------------------------------
# Tech profiles: the plugin's own data, not the repo's.
# Binary ownership lives here so adding a technology is one YAML file, never
# an edit to the guard.
# --------------------------------------------------------------------------
def _profiles():
    if not PROFILE_DIR.exists():
        return []
    return [load_yaml(p) for p in sorted(PROFILE_DIR.glob("*.yml"))
            if not p.name.startswith("_")]


def profile_topics():
    return {str(p.get("tech", "")).lower() for p in _profiles() if p.get("tech")}


def binary_owners():
    """binary -> set(topics). A binary owned by more than one technology (pod:
    CocoaPods for mobile, also a Ruby gem) maps to all of them; the guard only
    objects when the file's topic is in none."""
    owners = {}
    for prof in _profiles():
        tech = str(prof.get("tech", "")).lower()
        if not tech:
            continue
        for b in prof.get("detect_binaries") or []:
            owners.setdefault(str(b), set()).add(tech)
    return owners


def subcommand_owners():
    """binary -> {keyword: topic}, for tools whose subcommand decides the topic
    (`expo build:android` is mobile, `expo build:web` is web)."""
    out = {}
    for prof in _profiles():
        tech = str(prof.get("tech", "")).lower()
        for b, mapping in (prof.get("subcommand_owners") or {}).items():
            dest = out.setdefault(str(b), {})
            for kw, topic in (mapping or {}).items():
                dest[str(kw).lower()] = str(topic).lower()
    return out


def profile_secret_patterns():
    """Extra literal fragments each technology treats as a secret. Loaded by the
    guard so tech-profiles are live configuration rather than documentation."""
    out = {}
    for prof in _profiles():
        tech = str(prof.get("tech", "")).lower()
        pats = prof.get("secret_patterns") or []
        if tech and pats:
            out[tech] = [str(p) for p in pats]
    return out


if __name__ == "__main__":
    cfg = load()
    print(f"root:        {cfg.root}")
    print(f"configured:  {cfg.configured}" + ("" if cfg.configured else f"  (no {CONFIG_NAME})"))
    print(f"sources:     {cfg.sources}")
    print(f"layout:      {cfg.data['layout']}  ->  {cfg.topic_md('<topic>')}")
    print(f"topics:      {', '.join(cfg.topics()) or '(none)'}")
    print(f"aliases:     {cfg.data.get('aliases') or '(none)'}")
    print(f"named ents:  {len(cfg.named_entities())} configured")
    print(f"profiles:    {', '.join(sorted(profile_topics()))}")
    sys.exit(0 if cfg.configured else 2)
