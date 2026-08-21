#!/usr/bin/env python3
"""Deterministic write guard for cheatsheet-forge.

Fires on PreToolUse for Write/Edit/MultiEdit. Two blocking checks:

  1. SECRETS  - tokens, keys, passwords, home paths, private IPs, internal DNS
  2. BOUNDARY - a command belonging to another technology landing in a topic file

Neither check is model-mediated. An agent cannot reason its way past them.
Placeholders (<FOO>, [REDACTED], $VAR, ${VAR}) are always allowed.
"""
import json
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Which files this guard governs
# --------------------------------------------------------------------------
TOPIC_FILE = re.compile(r"(?:^|/)([A-Za-z0-9_-]+)/\1?[A-Za-z0-9_-]*\.md$")
GOVERNED_DIRS = ("openshift", "linux", "podman", "git", "kafka",
                 "Haschicorp-vault", "vault", "spring", "java", "ruby",
                 "web", "mobile", "site")

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

# --------------------------------------------------------------------------
# 2. Topic boundary  (binary -> the topic it belongs to)
# --------------------------------------------------------------------------
BINARY_TOPIC = {
    "oc": "openshift", "kubectl": "openshift", "argocd": "openshift",
    "podman": "podman", "podman-compose": "podman", "buildah": "podman", "skopeo": "podman",
    "docker": "podman", "docker-compose": "podman",
    "vault": "vault",
    "git": "git",
    "systemctl": "linux", "journalctl": "linux", "yum": "linux", "dnf": "linux",
    "apt": "linux", "apt-get": "linux", "lsof": "linux", "fuser": "linux", "useradd": "linux",
    "mvn": "spring", "gradle": "spring", "./mvnw": "spring", "./gradlew": "spring",
    "npm": "web", "npx": "web", "yarn": "web", "pnpm": "web", "node": "web",
    "flutter": "mobile", "pod": "mobile", "xcodebuild": "mobile",
    "gem": "ruby", "bundle": "ruby", "rails": "ruby", "rbenv": "ruby", "pod": "ruby",
    "kafka-topics": "kafka", "kafka-console-producer": "kafka", "kafka-console-consumer": "kafka",
}
# `expo` doesn't own a single topic: `expo build:android`/`build:ios` are native
# mobile builds, but `expo build:web`/`start`/`export:web` etc. target the web
# bundle. Resolved per-subcommand in check_boundary(), not via BINARY_TOPIC.
EXPO_SUBCOMMAND_TOPIC = {"android": "mobile", "ios": "mobile", "web": "web"}

# Binaries that are legitimately universal - never a boundary violation.
UNIVERSAL = {"curl", "echo", "cat", "grep", "sed", "awk", "export", "cd", "ls", "chmod",
             "chown", "mkdir", "rm", "cp", "mv", "ssh", "scp", "openssl", "base64", "jq",
             "for", "do", "done", "if", "then", "fi", "while", "source",
             "brew", "tar", "unzip", "wget", "printf", "test", "which", "find"}

# Prefixes that WRAP another command. They must be stripped before the boundary
# check, never treated as the command itself -- `sudo gem install` is a gem command.
WRAPPERS = {"sudo", "env", "time", "nohup", "nice", "xargs", "command", "exec",
            "doas", "stdbuf", "timeout", "watch"}

# Topic directory aliases -> canonical topic key
TOPIC_ALIAS = {"haschicorp-vault": "vault", "hashicorp-vault": "vault"}


def topic_of(path: str):
    parts = Path(path).parts
    for p in parts:
        key = TOPIC_ALIAS.get(p.lower(), p.lower())
        if key in set(BINARY_TOPIC.values()) | {"openshift", "linux", "podman", "git", "kafka", "vault"}:
            return key
    return None


def bash_blocks(text: str):
    """Yield lines inside ```bash / ```sh fenced blocks."""
    inside = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            inside = s.startswith("```bash") or s.startswith("```sh") or s.startswith("```shell")
            continue
        if inside:
            yield line


def check_secrets(text: str):
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for name, pattern, hint in SECRETS:
            m = re.search(pattern, line)
            if not m:
                continue
            if SAFE_MARKERS.search(m.group(0)):
                continue
            frag = m.group(0)
            if len(frag) > 48:
                frag = frag[:45] + "..."
            hits.append(f"  line {lineno}: {name} -> {frag}" + (f"  ({hint})" if hint else ""))
    return hits


def check_boundary(text: str, topic: str):
    if not topic:
        return []
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

        # `expo`, bare or via `npx`, is resolved per-subcommand rather than a
        # fixed owner: `build:android`/`build:ios` are native mobile builds,
        # `build:web` and friends target the web bundle. See EXPO_SUBCOMMAND_TOPIC.
        expo_idx = None
        if first == "expo":
            expo_idx = idx
        elif first == "npx" and idx + 1 < len(tokens) and tokens[idx + 1].lstrip("$(").strip("`") == "expo":
            expo_idx = idx + 1
        if expo_idx is not None:
            sub = tokens[expo_idx + 1].lower() if expo_idx + 1 < len(tokens) else ""
            owners = {t for kw, t in EXPO_SUBCOMMAND_TOPIC.items() if kw in sub}
            if owners and topic not in owners:
                shown = "/".join(sorted(owners))
                hits.append(f"  `expo {sub}` belongs to '{shown}', not '{topic}': {stripped[:70]}")
            continue

        owner = BINARY_TOPIC.get(first)
        owners = owner if isinstance(owner, (set, frozenset)) else ({owner} if owner else set())
        if owners and topic not in owners:
            shown = "/".join(sorted(owners))
            hits.append(f"  `{first}` belongs to '{shown}', not '{topic}': {stripped[:70]}")
    return hits


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = payload.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit"):
        sys.exit(0)

    ti = payload.get("tool_input", {}) or {}
    path = ti.get("file_path", "") or ""
    if not path.endswith((".md", ".mdx", ".yml", ".yaml")):
        sys.exit(0)
    if "_sources/" in path:          # raw dumps are expected to contain secrets
        sys.exit(0)
    if not any(d in path for d in GOVERNED_DIRS):
        sys.exit(0)

    content = ti.get("content") or ti.get("new_string") or ""
    if not content and "edits" in ti:
        content = "\n".join(e.get("new_string", "") for e in ti.get("edits", []))
    if not content:
        sys.exit(0)

    problems = []
    sec = check_secrets(content)
    if sec:
        problems.append("SECRET / PII LEAK — blocking:\n" + "\n".join(sec[:12]))
    bnd = check_boundary(content, topic_of(path))
    if bnd:
        problems.append("TOPIC BOUNDARY — blocking:\n" + "\n".join(bnd[:12]))

    if problems:
        reason = ("cheatsheet-forge guard blocked this write.\n\n"
                  + "\n\n".join(problems)
                  + "\n\nParameterise the value (<PLACEHOLDER>) or move the command to the "
                    "correct topic file. Raw dumps belong in _sources/ (gitignored).")
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
