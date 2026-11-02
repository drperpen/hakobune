"""Command line: hakobune lock | collect | verify | status."""

from __future__ import annotations

import argparse
import os
import sys

from hakobune import __version__
from hakobune.config import dump_lock, load_components, load_local, load_lock
from hakobune.errors import HakobuneError
from hakobune.lock import build_lock
from hakobune.store import Store


def _paths(args) -> tuple[str, str, str]:
    root = os.path.abspath(args.root)
    return (
        os.path.join(root, "components.json"),
        os.path.join(root, "hakobune.lock"),
        os.path.join(root, "hakobune.local.json"),
    )


def cmd_lock(args) -> int:
    comp_path, lock_path, local_path = _paths(args)
    components = load_components(comp_path)
    local = load_local(local_path, os.path.dirname(local_path))
    text = dump_lock(build_lock(components, local))
    try:
        with open(lock_path, encoding="utf-8") as f:
            current = f.read()
    except FileNotFoundError:
        current = None
    if args.check:
        if current != text:
            print("hakobune.lock is out of date with components.json or the sources", file=sys.stderr)
            return 1
        print("hakobune.lock is up to date")
        return 0
    if current == text:
        print("hakobune.lock unchanged")
        return 0
    tmp = lock_path + ".partial"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, lock_path)
    print("wrote hakobune.lock; review the diff before committing (the operator approves pin changes)")
    return 0


def _store(args):
    _comp, lock_path, local_path = _paths(args)
    lock = load_lock(lock_path)
    local = load_local(local_path, os.path.dirname(local_path))
    return Store(local.store, lock), local


def cmd_collect(args) -> int:
    store, local = _store(args)
    with store.open():
        store.collect(local, set(args.only) or None)
        problems = [f"{x}: not in the lock" for x in store.extras()] if not args.only else []
    for p in problems:
        print(f"warning: {p}", file=sys.stderr)
    print("collect done")
    return 0


def cmd_verify(args) -> int:
    store, _local = _store(args)
    with store.open():
        problems = store.verify(set(args.only) or None)
    for p in problems:
        print(f"FAIL {p}", file=sys.stderr)
    if problems:
        return 1
    print("store verified against hakobune.lock")
    return 0


def cmd_status(args) -> int:
    store, _local = _store(args)
    with store.open():
        rows = store.status()
    width = max(len(r[1]) for r in rows) if rows else 0
    for kind, name, state in rows:
        print(f"{kind:7} {name:{width}}  {state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hakobune", description=__doc__)
    parser.add_argument("--version", action="version", version=f"hakobune {__version__}")
    parser.add_argument("--root", default=".", help="checkout holding components.json (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("lock", help="resolve components.json into hakobune.lock")
    p.add_argument("--check", action="store_true", help="fail if the lock is out of date; write nothing")
    p.set_defaults(func=cmd_lock)

    for name, func, text in (
        ("collect", cmd_collect, "fill the artifact store from local images, weights and recipes"),
        ("verify", cmd_verify, "re-hash the whole store against the lock"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--only", action="append", default=[], metavar="NAME", help="limit to one component (repeatable)")
        p.set_defaults(func=func)

    p = sub.add_parser("status", help="show what the store holds, without hashing")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except HakobuneError as e:
        print(f"hakobune: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("hakobune: interrupted; partial files are removed, re-run to continue", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
