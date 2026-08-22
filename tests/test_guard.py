#!/usr/bin/env python3
"""Fixture tests for the write guard and the config layer.

The guard is the only non-model-mediated control in the pipeline, so it is the
one place where a silent regression is invisible until something leaks. Run:

    python3 tests/test_guard.py

No test framework, no dependencies — this must run wherever the hook runs.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

CONFIG = """\
version: 1
sources_dir: _sources
site_dir: site
layout: {layout}
topics:
  - openshift
  - ruby
  - mobile
  - vault
aliases:
  haschicorp-vault: vault
redact:
  named_entities:
    - Contoso
  extra_patterns: []
guard:
  unknown_topic: {unknown_topic}
"""

FAILED = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}\n          expected {want!r}\n          got      {got!r}")
        FAILED.append(name)


def load_guard():
    spec = importlib.util.spec_from_file_location("guard", ROOT / "hooks" / "guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def md(*lines):
    return "# Sheet\n\n```bash\n" + "\n".join(lines) + "\n```\n"


# --------------------------------------------------------------------------
CASES = [
    # (name, relative path, content, expected decision)
    ("clean openshift sheet", "openshift/openshift.md",
     md("oc get pods -n <NAMESPACE>", "oc auth can-i patch <RESOURCE> -n <NAMESPACE>"), "allow"),

    # -- secrets ----------------------------------------------------------
    ("session token", "openshift/openshift.md",
     md("oc login --token=sha256~AbCdEfGhIjKlMnOpQrStUvWxYz012345"), "deny"),
    ("jwt", "openshift/openshift.md",
     md("curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdef'"), "deny"),
    ("absolute home path", "ruby/ruby.md",
     md("export GEM_HOME=/Users/jdoe/.gem"), "deny"),
    ("home path parameterised", "ruby/ruby.md",
     md("export GEM_HOME=$HOME/.gem"), "allow"),
    ("private ip", "openshift/openshift.md",
     md("ssh core@10.11.12.13"), "deny"),
    ("internal cluster dns", "openshift/openshift.md",
     md("curl https://noobaa-mgmt.openshift-storage.svc.cluster.local"), "deny"),
    ("aws key", "openshift/openshift.md",
     md("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"), "deny"),
    ("hardcoded password", "vault/vault.md",
     md("vault login -method=userpass password='hunter2secret'"), "deny"),
    ("placeholder password", "vault/vault.md",
     md("vault login -method=userpass password=<PASSWORD>"), "allow"),

    # -- repo-configured named entity (never hardcoded in the plugin) -----
    ("configured client name", "openshift/openshift.md",
     md("oc project contoso-prod"), "deny"),

    # -- topic boundary ---------------------------------------------------
    ("gem in openshift", "openshift/openshift.md",
     md("gem install bundler"), "deny"),
    ("npm in openshift", "openshift/openshift.md",
     md("npm ci"), "deny"),
    ("sudo unwrapped to gem", "openshift/openshift.md",
     md("sudo gem install bundler"), "deny"),
    ("universal binary is never a violation", "openshift/openshift.md",
     md("openssl x509 -in <CERT> -noout -text"), "allow"),
    ("var assignment prefix", "openshift/openshift.md",
     md("KUBECONFIG=<PATH> oc get nodes"), "allow"),
    ("prose outside bash fence is not scanned for boundary", "openshift/openshift.md",
     "# Sheet\n\nRun `gem install bundler` elsewhere.\n", "allow"),

    # -- the pod collision: owned by BOTH mobile and ruby ------------------
    ("pod allowed in mobile", "mobile/mobile.md", md("pod install"), "allow"),
    ("pod allowed in ruby", "ruby/ruby.md", md("pod install"), "allow"),
    ("pod rejected in openshift", "openshift/openshift.md", md("pod install"), "deny"),

    # -- subcommand-decided ownership --------------------------------------
    ("expo build:android in mobile", "mobile/mobile.md", md("npx expo build:android"), "allow"),
    ("expo build:web in mobile", "mobile/mobile.md", md("npx expo build:web"), "deny"),

    # -- alias resolution --------------------------------------------------
    ("alias dir resolves to canonical topic", "haschicorp-vault/hvault.md",
     md("vault status"), "allow"),
    ("alias dir still enforces boundary", "haschicorp-vault/hvault.md",
     md("gem install bundler"), "deny"),

    # -- raw dumps are exempt ---------------------------------------------
    ("raw dump exempt from secret scan", "_sources/openshift/dump.md",
     md("oc login --token=sha256~AbCdEfGhIjKlMnOpQrStUvWxYz012345"), "allow"),

    # -- unknown topic: secrets still scanned (the old fail-open hole) -----
    ("unknown topic still secret-scanned", "terraform/terraform.md",
     md("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"), "deny"),
    ("unknown topic skips boundary under warn", "terraform/terraform.md",
     md("gem install bundler"), "allow"),
]


def run_layout(tmp, layout="nested", unknown_topic="warn"):
    root = pathlib.Path(tmp)
    (root / ".cheatsheet-repo.yml").write_text(
        CONFIG.format(layout=layout, unknown_topic=unknown_topic))
    os.environ["CHEATSHEET_REPO"] = str(root)
    guard = load_guard()
    cfg = guard._config()
    for name, rel, content, want in CASES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        decision, _reason = guard.evaluate(str(p), content, cfg)
        check(name, decision, want)


def run_flat(tmp):
    root = pathlib.Path(tmp)
    (root / ".cheatsheet-repo.yml").write_text(
        CONFIG.format(layout="flat", unknown_topic="warn"))
    os.environ["CHEATSHEET_REPO"] = str(root)
    guard = load_guard()
    cfg = guard._config()
    check("flat layout: boundary enforced on <topic>.md",
          guard.evaluate(str(root / "openshift.md"), md("gem install bundler"), cfg)[0], "deny")
    check("flat layout: clean file allowed",
          guard.evaluate(str(root / "openshift.md"), md("oc get pods -n <NS>"), cfg)[0], "allow")


def run_deny_policy(tmp):
    root = pathlib.Path(tmp)
    (root / ".cheatsheet-repo.yml").write_text(
        CONFIG.format(layout="nested", unknown_topic="deny"))
    os.environ["CHEATSHEET_REPO"] = str(root)
    guard = load_guard()
    cfg = guard._config()
    check("unknown_topic=deny refuses undeclared topic",
          guard.evaluate(str(root / "terraform/terraform.md"),
                         md("terraform apply"), cfg)[0], "deny")


def run_foreign_project(tmp):
    """Installed globally, the hook fires on every write in every project. A
    file in some unrelated codebase must pass through untouched even while
    $CHEATSHEET_REPO points at a real, configured cheat-sheet repo."""
    root = pathlib.Path(tmp)
    repo = root / "sheets"
    repo.mkdir()
    (repo / ".cheatsheet-repo.yml").write_text(
        CONFIG.format(layout="nested", unknown_topic="deny"))
    os.environ["CHEATSHEET_REPO"] = str(repo)
    other = root / "unrelated-app"
    (other / "docs").mkdir(parents=True)

    leaky = md("ssh deploy@10.0.0.5")
    payload = json.dumps({"tool_name": "Write", "tool_input": {
        "file_path": "docs/setup.md", "content": leaky}})
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard.py")],
                       input=payload, capture_output=True, text=True, cwd=str(other))
    check("relative path in a foreign project is not governed", r.stdout.strip(), "")

    guard = load_guard()
    cfg = guard._config()
    check("absolute path in a foreign project is not governed",
          guard.evaluate(str(other / "docs" / "setup.md"), leaky, cfg)[0], "allow")
    check("foreign path is not caught by unknown_topic=deny",
          guard.evaluate(str(other / "terraform" / "terraform.md"),
                         md("terraform apply"), cfg)[0], "allow")
    check("the configured repo is still guarded",
          guard.evaluate(str(repo / "openshift" / "openshift.md"), leaky, cfg)[0], "deny")


def run_unconfigured(tmp):
    """An unconfigured repo must be inert, not crash the write."""
    root = pathlib.Path(tmp)
    os.environ.pop("CHEATSHEET_REPO", None)
    payload = json.dumps({"tool_name": "Write", "tool_input": {
        "file_path": str(root / "openshift/openshift.md"),
        "content": md("oc login --token=sha256~AbCdEfGhIjKlMnOpQrStUvWxYz012345")}})
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard.py")],
                       input=payload, capture_output=True, text=True, cwd=str(root))
    check("unconfigured repo exits cleanly", r.returncode, 0)
    check("unconfigured repo emits no decision", r.stdout.strip(), "")


def run_config_layer():
    import forgeconfig as fc
    owners = fc.binary_owners()
    check("pod has two owners", owners.get("pod"), {"mobile", "ruby"})
    check("oc owned by openshift", owners.get("oc"), {"openshift"})
    check("expo resolved per subcommand",
          fc.subcommand_owners().get("expo", {}).get("android"), "mobile")
    # the dependency-free fallback parser must agree with PyYAML
    parsed = fc._mini_load(CONFIG.format(layout="nested", unknown_topic="warn"))
    check("fallback parser: scalars", parsed.get("layout"), "nested")
    check("fallback parser: block list", parsed.get("topics"),
          ["openshift", "ruby", "mobile", "vault"])
    check("fallback parser: nested map", parsed.get("aliases"),
          {"haschicorp-vault": "vault"})
    check("fallback parser: two-level nesting",
          parsed.get("redact", {}).get("named_entities"), ["Contoso"])
    check("fallback parser: flow list", fc._flow_list("[a, b, 'c']"), ["a", "b", "c"])


def main():
    print("config layer")
    run_config_layer()
    for label, fn in (("nested layout", run_layout), ("flat layout", run_flat),
                      ("unknown_topic=deny", run_deny_policy),
                      ("foreign project", run_foreign_project),
                      ("unconfigured repo", run_unconfigured)):
        print(f"\n{label}")
        tmp = tempfile.mkdtemp()
        try:
            fn(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILED:
        print(f"FAIL: {len(FAILED)} case(s): {', '.join(FAILED)}")
        return 1
    print("PASS: all guard fixtures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
