#!/usr/bin/env python3
"""Deterministic write guard for cheatsheet-forge.

Fires on PreToolUse for Write/Edit/MultiEdit. Two blocking checks:

  1. SECRETS  - tokens, keys, passwords, home paths, private IPs, internal DNS
  2. BOUNDARY - a command belonging to another technology landing in a topic file

Neither check is model-mediated. An agent cannot reason its way past them.
Placeholders (<FOO>, [REDACTED], $VAR, ${VAR}) are always allowed.

Nothing here is specific to any repository. Layout, topics, aliases and the
extra strings a given repo treats as identifying come from its
.cheatsheet-repo.yml; binary ownership comes from tech-profiles/. Adding a
technology is a YAML file, never an edit to this guard.

The secret scan runs on every governed write, whether or not the topic is
recognised — an unknown topic must never mean an unscanned file.
"""
import json
import pathlib
import re
import sys

# forgeconfig lives in scripts/. A blocking hook must not die on an import, so
# every failure degrades to built-in defaults rather than crashing the write.
try:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import forgeconfig as fc
except Exception:                                    # pragma: no cover
    fc = None

# --------------------------------------------------------------------------
# 1. Secret patterns  (name, regex, hint)
# --------------------------------------------------------------------------
SECRETS = [
    ("JWT / bearer token",
     r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+", None),
    ("OpenShift session token",
     r"sha256~[A-Za-z0-9_-]{20,}", None),
    ("Private key block",
     r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", None),
    ("AWS access key id",
     r"\bAKIA[0-9A-Z]{16}\b", None),
    ("GitHub token",
     r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", None),
    ("Vault token",
     r"\b[hs]vs?\.[A-Za-z0-9]{20,}\b", None),
    ("Literal bearer credential",
     r"Bearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}", "use $TOKEN"),
    ("Hardcoded password/secret value",
     r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*[\"']([^\"'<\[$][^\"']{5,})[\"']", "use a placeholder"),
    ("Absolute home directory",
     r"/(?:Users|home)/(?!<)[A-Za-z][A-Za-z0-9._-]{1,}", "use $HOME or <USER>"),
    ("Private IP address",
     r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b", "use <HOST_IP>"),
    ("Internal cluster DNS",
     r"\b(?![a-z0-9-]*<)[a-z0-9-]+\.[a-z0-9-]+\.svc(?:\.cluster\.local)?\b", "parameterise the service/namespace"),
]

# Any line carrying one of these is considered already sanitised.
SAFE_MARKERS = re.compile(r"<[A-Z_][A-Z0-9_]*>|\[REDACTED[^\]]*\]|\$\{?[A-Z_]+\}?|example\.com|<USER>")

# Binaries that are legitimately universal - never a boundary violation.
UNIVERSAL = {"curl", "echo", "cat", "grep", "sed", "awk", "export", "cd", "ls", "chmod",
             "chown", "mkdir", "rm", "cp", "mv", "ssh", "scp", "openssl", "base64", "jq",
             "for", "do", "done", "if", "then", "fi", "while", "source",
             "brew", "tar", "unzip", "wget", "printf", "test", "which", "find"}

# Prefixes that WRAP another command. They must be stripped before the boundary
# check, never treated as the command itself -- `sudo gem install` is a gem command.
WRAPPERS = {"sudo", "env", "time", "nohup", "nice", "xargs", "command", "exec",
            "doas", "stdbuf", "timeout", "watch"}


# --------------------------------------------------------------------------
# Repo-derived configuration
# --------------------------------------------------------------------------
def _config():
    return fc.load() if fc else None


def extra_secret_patterns(cfg):
    """Repo-specific identifiers: employer and client names, internal product
    codenames. These live in the repo's own config precisely so they are never
    baked into a plugin that gets published."""
    out = []
    if not cfg:
        return out
    for name in cfg.named_entities():
        # Case-insensitive: a name is identifying however it is capitalised.
        out.append(("Client/employer identifier", "(?i)" + re.escape(name),
                    "use a generic placeholder"))
    for pat in cfg.extra_patterns():
        out.append(("Repo-configured secret pattern", pat, None))
    return out


# NOTE: tech-profiles carry a `secret_patterns` list. It is deliberately NOT
# wired in here. Those patterns are broad locators ("system:serviceaccount:",
# "unseal", "role-id") meant to tell the reviewer where to look; as deny rules
# they block legitimate documented commands. The reviewer consumes them; the
# guard blocks only on shapes that are credentials by construction.


def topic_of(path, cfg):
    """The topic a governed file belongs to, or None.

    Matches the configured layout rather than guessing: nested repos keep
    <topic>/<topic>.md, flat repos keep <topic>.md.
    """
    if not cfg:
        return None
    p = pathlib.Path(path)
    parts = [x.lower() for x in p.parts]
    known = cfg.known_topics()
    flat = cfg.data.get("layout") == "flat"
    if flat:
        cand = cfg.canonical(p.stem)
        return cand if cand in known else None
    # nested: the directory name owns the file
    for part in reversed(parts[:-1]):
        cand = cfg.canonical(part)
        if cand in known:
            return cand
    return None


def governed(path, cfg):
    """Is this write inside the cheat-sheet repo and not a raw dump?

    Returns (bool, reason). Raw dumps are expected to contain secrets and are
    gitignored; everything else the pipeline writes gets scanned.
    """
    if not path.endswith((".md", ".mdx", ".yml", ".yaml")):
        return False, "not a document"
    p = pathlib.Path(path)
    if not cfg:
        return False, "unconfigured"
    src_name = cfg.data.get("sources_dir", "_sources")
    if src_name in p.parts:
        return False, "raw dump"
    try:
        p.resolve().relative_to(cfg.root)
    except ValueError:
        # Outside the configured repo. This is the common case once the plugin
        # is installed globally: the hook fires on every write in every project,
        # and a file belonging to some unrelated codebase must pass through
        # untouched. Relative paths resolve against the cwd, which for a hook is
        # the project being worked in -- so this correctly excludes them too.
        return False, "outside repo"
    return True, ""


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def check_secrets(text, patterns):
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for name, pattern, hint in patterns:
            try:
                m = re.search(pattern, line)
            except re.error:
                continue
            if not m:
                continue
            if SAFE_MARKERS.search(m.group(0)):
                continue
            frag = m.group(0)
            if len(frag) > 48:
                frag = frag[:45] + "..."
            hits.append(f"  line {lineno}: {name} -> {frag}" + (f"  ({hint})" if hint else ""))
    return hits


def bash_blocks(text):
    """Yield lines inside ```bash / ```sh fenced blocks."""
    inside = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            inside = s.startswith("```bash") or s.startswith("```sh") or s.startswith("```shell")
            continue
        if inside:
            yield line


def check_boundary(text, topic):
    if not topic or not fc:
        return []
    owners_map = fc.binary_owners()
    subcmd_map = fc.subcommand_owners()
    hits = []
    for line in bash_blocks(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = [tok for tok in stripped.split() if not tok.startswith("-")]
        idx = 0
        while idx < len(tokens) - 1 and tokens[idx].lstrip("$(").strip("`") in WRAPPERS:
            idx += 1                      # unwrap sudo/env/time/... to the real binary
        if idx >= len(tokens):
            continue
        first = tokens[idx].lstrip("$(").strip("`")
        if "=" in first:                  # VAR=value prefix assignment
            continue
        if first in UNIVERSAL:
            continue

        # Some tools do not own a single topic: the subcommand decides. `expo
        # build:android` is a native mobile build, `expo build:web` targets the
        # web bundle. Declared per profile as subcommand_owners.
        sub_idx = None
        if first in subcmd_map:
            sub_idx = idx
        elif idx + 1 < len(tokens):
            nxt = tokens[idx + 1].lstrip("$(").strip("`")
            if nxt in subcmd_map and first in ("npx", "yarn", "pnpm", "bunx"):
                first, sub_idx = nxt, idx + 1
        if sub_idx is not None:
            sub = tokens[sub_idx + 1].lower() if sub_idx + 1 < len(tokens) else ""
            owners = {t for kw, t in subcmd_map[first].items() if kw in sub}
            if owners and topic not in owners:
                hits.append(f"  `{first} {sub}` belongs to '{'/'.join(sorted(owners))}', "
                            f"not '{topic}': {stripped[:70]}")
            continue

        owners = owners_map.get(first, set())
        if owners and topic not in owners:
            hits.append(f"  `{first}` belongs to '{'/'.join(sorted(owners))}', "
                        f"not '{topic}': {stripped[:70]}")
    return hits


# --------------------------------------------------------------------------
def evaluate(path, content, cfg):
    """Return (decision, reason). decision is 'allow' or 'deny'."""
    ok, _why = governed(path, cfg)
    if not ok:
        return "allow", ""

    topic = topic_of(path, cfg)
    problems = []

    patterns = SECRETS + extra_secret_patterns(cfg)
    sec = check_secrets(content, patterns)
    if sec:
        problems.append("SECRET / PII LEAK — blocking:\n" + "\n".join(sec[:12]))

    bnd = check_boundary(content, topic)
    if bnd:
        problems.append("TOPIC BOUNDARY — blocking:\n" + "\n".join(bnd[:12]))

    if topic is None and cfg and cfg.unknown_topic_policy() == "deny":
        problems.append(
            "UNKNOWN TOPIC — blocking:\n"
            f"  '{path}' does not match a topic declared in .cheatsheet-repo.yml.\n"
            "  Add it to `topics:` (or set guard.unknown_topic: warn) before writing.")

    if not problems:
        return "allow", ""

    src = cfg.data.get("sources_dir", "_sources") if cfg else "_sources"
    return "deny", ("cheatsheet-forge guard blocked this write.\n\n"
                    + "\n\n".join(problems)
                    + "\n\nParameterise the value (<PLACEHOLDER>) or move the command to the "
                      f"correct topic file. Raw dumps belong in {src}/ (gitignored).")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if payload.get("tool_name", "") not in ("Write", "Edit", "MultiEdit"):
        sys.exit(0)

    ti = payload.get("tool_input", {}) or {}
    path = ti.get("file_path", "") or ""
    if not path:
        sys.exit(0)

    content = ti.get("content") or ti.get("new_string") or ""
    if not content and "edits" in ti:
        content = "\n".join(e.get("new_string", "") for e in ti.get("edits", []))
    if not content:
        sys.exit(0)

    try:
        cfg = _config()
    except Exception:
        sys.exit(0)
    # An unconfigured repo has no layout to reason about. /init is mandatory;
    # the commands refuse before any agent gets this far.
    if cfg is None or not cfg.configured:
        sys.exit(0)

    decision, reason = evaluate(path, content, cfg)
    if decision == "deny":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
    sys.exit(0)


if __name__ == "__main__":
    main()
