#!/usr/bin/env python3
"""Index the repository and emit codemap.json for the showcase code web.

A tiny file indexer / mapper: it walks the repo, groups files by directory and
extracts import relations between local Python modules, then writes a small
JSON graph the showcase renders as an interactive web. Stdlib only.

Usage:  python3 build_codemap.py [repo_root] [out.json]
"""
from __future__ import annotations

import json
import os
import re
import sys

SKIP_DIRS = {".git", ".studio", ".venv", "__pycache__", "agentcore", "wheels", "node_modules"}
SKIP_FILES = {".gitignore", ".env", ".env.local", "codemap.json", "signals.json"}
KEEP_EXT = {".py", ".toml", ".md", ".html", ".png", ".json", ""}

IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w]*)\s+import|import\s+([A-Za-z_][\w]*))", re.M)


def index(root: str) -> dict:
    groups: dict[str, list[str]] = {}
    pyfiles: dict[str, str] = {}  # module name -> group/file id

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = os.path.relpath(dirpath, root)
        group = "root" if rel == "." else rel.replace(os.sep, "/")
        for fn in sorted(filenames):
            if fn in SKIP_FILES or fn == "LICENSE" and group != "root":
                continue
            ext = os.path.splitext(fn)[1]
            if ext not in KEEP_EXT:
                continue
            groups.setdefault(group, []).append(fn)
            if ext == ".py":
                pyfiles[os.path.splitext(fn)[0]] = f"{group}/{fn}"

    imports: list[list[str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = os.path.relpath(dirpath, root)
        group = "root" if rel == "." else rel.replace(os.sep, "/")
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            src = f"{group}/{fn}"
            try:
                text = open(os.path.join(dirpath, fn), encoding="utf-8").read()
            except Exception:
                continue
            for m in IMPORT_RE.finditer(text):
                mod = m.group(1) or m.group(2)
                dst = pyfiles.get(mod)
                if dst and dst != src:
                    imports.append([src, dst])

    return {"groups": [{"name": g, "files": fs} for g, fs in sorted(groups.items())],
            "imports": sorted(set(map(tuple, imports)))}


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "codemap.json")
    data = index(root)
    data["imports"] = [list(t) for t in data["imports"]]
    with open(out, "w") as f:
        json.dump(data, f, indent=1)
    n = sum(len(g["files"]) for g in data["groups"])
    print(f"indexed {n} files, {len(data['imports'])} import links -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
