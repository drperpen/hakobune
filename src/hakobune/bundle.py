"""`hakobune build` and bundle verification (ADR-001 §6).

A bundle is a directory:

    hakobune-<release>/
      manifest.json          release, components, sha256 and size of every other file
      manifest.json.sig      Ed25519 signature of manifest.json (added by `hakobune sign`)
      hakobune.pyz           the installer, standard library only
      images/<name>.tar      docker save archives
      models/<name>/...      weights as served
      recipes/<name>/...     recipe files
      notices/...            licenses and notices

Large files are hardlinked from the store, so a bundle costs almost no extra
disk (ADR-001 §13). Store files are read-only, so a hardlink cannot be used to
change the store.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import zipfile

from hakobune import __version__, docker, hashing
from hakobune.config import Components, check_relpath
from hakobune.errors import HakobuneError
from hakobune.store import Store

SCHEMA = 1
RELEASE_RE = re.compile(r"^(\d{4})\.(0[1-9]|1[0-2])\.(\d+)(-dev\.\d+)?$")
NVIDIA_SOURCE_NOTICE = "This software contains source code provided by NVIDIA Corporation."
MANIFEST, SIGNATURE, INSTALLER = "manifest.json", "manifest.json.sig", "hakobune.pyz"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def parse_release(release: str) -> bool:
    """Validate a release version; returns True for a dev build."""
    m = RELEASE_RE.match(release)
    if not m:
        raise HakobuneError(f"release {release!r} must look like 2026.11.0, or 2026.11.0-dev.1 for a test build")
    return m.group(4) is not None


def _git(root: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise HakobuneError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def write_pyz(package_dir: str, out_path: str) -> None:
    """A reproducible zipapp of the hakobune package (same sources, same bytes)."""
    files = []
    for d, dirs, names in os.walk(package_dir):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for n in sorted(names):
            if n.endswith(".py"):
                full = os.path.join(d, n)
                files.append((os.path.join("hakobune", os.path.relpath(full, package_dir)), full))
    with open(out_path, "wb") as raw:
        raw.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
            def add(name: str, data: bytes) -> None:
                info = zipfile.ZipInfo(name, _ZIP_TIME)
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, data)
            add("__main__.py", b"import sys\nfrom hakobune.cli import main\nsys.exit(main())\n")
            for name, full in files:
                with open(full, "rb") as f:
                    add(name, f.read())


def check_lock_matches(components: Components, lock: dict) -> None:
    """The lock must resolve exactly the components listed (run `hakobune lock` otherwise)."""
    stale = "hakobune.lock does not match components.json; run 'hakobune lock'"
    want = {
        "images": {i.name: i.ref for i in components.images},
        "models": {m.name: m.revision for m in components.models},
        "recipes": {r.name: (r.commit, sorted(r.files)) for r in components.recipes},
    }
    have = {
        "images": {e["name"]: e["ref"] for e in lock.get("images", [])},
        "models": {e["name"]: e["revision"] for e in lock.get("models", [])},
        "recipes": {e["name"]: (e["commit"], sorted(f["path"] for f in e["files"])) for e in lock.get("recipes", [])},
    }
    if want != have:
        raise HakobuneError(stale)
    for i in components.images:
        e = next(x for x in lock["images"] if x["name"] == i.name)
        if i.image_id and e["image_id"] != i.image_id:
            raise HakobuneError(stale)


def release_blockers(components: Components, git_dirty: bool) -> list[str]:
    out = [f"third-party review of {n} is {s}" for n, s in components.review.items() if s != "approved"]
    out += [f"notice {n.to} is pending: {n.pending}" for n in components.notices if n.pending]
    if git_dirty:
        out.append("the hakobune checkout has uncommitted changes")
    return out


class _Builder:
    def __init__(self, stage: str, link: bool):
        self.stage, self.link = stage, link
        self.files: dict[str, dict] = {}

    def place(self, src: str, rel: str, sha256: str, size: int) -> None:
        dst = os.path.join(self.stage, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if self.link:
            try:
                os.link(src, dst)
            except OSError as e:
                raise HakobuneError(
                    f"cannot hardlink {rel} from the store ({e.strerror}); the bundle directory must be on the "
                    "store's file system, or use --copy"
                ) from None
        else:
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o444)
        self.files[rel] = {"path": rel, "size": size, "sha256": sha256}

    def write(self, rel: str, data: bytes, mode: int = 0o444) -> None:
        dst = os.path.join(self.stage, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        os.chmod(dst, mode)
        self.files[rel] = {"path": rel, "size": len(data), "sha256": hashing.sha256_bytes(data)}


def _notices(components: Components, store: Store, lock: dict, b: _Builder, dev: bool) -> list[str]:
    """Copy the notices into notices/ and return the lines of notices/README.md."""
    by_name = {e["name"]: e for k in ("images", "models", "recipes") for e in lock[k]}
    lines = [
        "# Notices",
        "",
        "This system contains third-party software and models under their own licenses.",
        "The files in this folder are the principal licenses and notices. Every container",
        "image also keeps the per-package notices of its own contents inside the image",
        "(for example `/usr/share/doc/*/copyright` and Python `*.dist-info/licenses/`).",
        "",
        NVIDIA_SOURCE_NOTICE,
        "",
        "| File | Source |",
        "| --- | --- |",
    ]
    by_image: dict[str, list] = {}
    for n in components.notices:
        if n.kind == "image":
            by_image.setdefault(n.source, []).append(n)
    for name, specs in by_image.items():
        found = docker.read_image_files(store.image_path(by_name[name]), [s.path for s in specs])
        for s in specs:
            items = (
                [(s.to + k[len(s.path):], v) for k, v in sorted(found.items()) if k.startswith(s.path)]
                if s.path.endswith("/") else [(s.to, found[s.path])]
            )
            for to, data in items:
                check_relpath(to, "notice")
                b.write(f"notices/{to}", data)
                lines.append(f"| `{to}` | image `{name}` (`{by_name[name]['image_id'][:19]}…`), `/{s.path}` |")
    for n in components.notices:
        if n.kind in ("model", "recipe"):
            kind = n.kind + "s"
            entry = by_name[n.source]
            if not any(f["path"] == n.path for f in entry["files"]):
                raise HakobuneError(f"notice {n.to}: {n.path} is not a locked file of {n.source}")
            with open(os.path.join(store.root, kind, n.source, n.path), "rb") as f:
                b.write(f"notices/{n.to}", f.read())
            lines.append(f"| `{n.to}` | {n.kind} `{n.source}`, `{n.path}` |")
    pending = [n for n in components.notices if n.pending]
    if pending:
        lines += ["", "## Missing (test build only; a release cannot be built with these missing)", ""]
        lines += [f"- `{n.to}`: {n.pending}" for n in pending]
    return lines


def build(root: str, components: Components, lock: dict, store: Store, release: str, out_dir: str,
          link: bool = True, log=print) -> str:
    dev = parse_release(release)
    check_lock_matches(components, lock)
    commit = _git(root, "rev-parse", "HEAD")
    dirty = bool(_git(root, "status", "--porcelain"))
    blockers = release_blockers(components, dirty)
    if blockers and not dev:
        raise HakobuneError("cannot build a release:\n  " + "\n  ".join(blockers))
    for x in blockers:
        log(f"warning (test build): {x}")

    final = os.path.join(out_dir, f"hakobune-{release}")
    if os.path.exists(final):
        raise HakobuneError(f"{final} already exists; bundles are immutable, use a new release number")
    stage = os.path.join(out_dir, f".hakobune-{release}.partial")
    if os.path.exists(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)
    b = _Builder(stage, link)
    try:
        with store.open():
            for kind, e in store.entries(None):
                if kind == "images":
                    sha = store.image_sha256(e)
                    path = store.image_path(e)
                    b.place(path, f"images/{e['name']}.tar", sha, os.path.getsize(path))
                    continue
                for f in e["files"]:
                    rel = os.path.join(kind, e["name"], f["path"])
                    store.require_good(rel, f)
                    b.place(os.path.join(store.root, rel), rel, f["sha256"], f["size"])
            notice_lines = _notices(components, store, lock, b, dev)
        b.write("notices/README.md", ("\n".join(notice_lines) + "\n").encode())
        pyz = os.path.join(stage, INSTALLER)
        write_pyz(os.path.dirname(os.path.abspath(__file__)), pyz)
        with open(pyz, "rb") as f:
            b.write(INSTALLER, f.read(), mode=0o555)

        with open(os.path.join(root, "hakobune.lock"), "rb") as f:
            lock_sha = hashing.sha256_bytes(f.read())
        manifest = {
            "schema": SCHEMA,
            "release": release,
            "dev": dev,
            "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hakobune": {"version": __version__, "git_commit": commit, "git_dirty": dirty},
            "lock_sha256": lock_sha,
            "release_blockers": blockers,
            "components": {
                "images": [{k: e[k] for k in ("name", "ref", "image_id", "platform", "registry_digest")}
                           for e in lock["images"]],
                "models": [{k: e[k] for k in ("name", "hf_repo", "revision")} for e in lock["models"]],
                "recipes": [{k: e[k] for k in ("name", "git", "commit")} for e in lock["recipes"]],
            },
            "files": [b.files[k] for k in sorted(b.files)],
        }
        data = (json.dumps(manifest, indent=2) + "\n").encode()
        with open(os.path.join(stage, MANIFEST), "wb") as f:
            f.write(data)
        os.chmod(os.path.join(stage, MANIFEST), 0o444)
        os.replace(stage, final)
    except BaseException:
        _rmtree_ro(stage)
        raise
    total = sum(f["size"] for f in b.files.values())
    log(f"built {final}: {len(b.files)} files, {total / 1e9:.1f} GB")
    return final


def _rmtree_ro(path: str) -> None:
    if not os.path.exists(path):
        return
    for d, _dirs, files in os.walk(path):
        os.chmod(d, 0o755)
    shutil.rmtree(path)


def verify_bundle(path: str, pubkey: str | None, allow_unsigned: bool = False, quick: bool = False,
                  log=print) -> dict:
    """Check the signature, then that the directory holds exactly the listed files."""
    from hakobune import signing

    mpath = os.path.join(path, MANIFEST)
    if not os.path.isfile(mpath):
        raise HakobuneError(f"{path}: no {MANIFEST}; not a bundle")
    if pubkey:
        signing.verify(mpath, os.path.join(path, SIGNATURE), pubkey)
        log(f"signature ok ({signing.fingerprint(pubkey)})")
    elif not allow_unsigned:
        raise HakobuneError("give --pubkey to check the signature (or --unsigned for a test bundle)")
    with open(mpath, encoding="utf-8") as f:
        manifest = json.load(f)
    if manifest.get("schema") != SCHEMA:
        raise HakobuneError(f"{path}: unsupported bundle schema {manifest.get('schema')!r}")
    listed = {}
    for f in manifest["files"]:
        check_relpath(f["path"], MANIFEST)
        listed[f["path"]] = f
    present = set()
    for d, dirs, files in os.walk(path):
        for n in dirs + files:
            full = os.path.join(d, n)
            if os.path.islink(full):
                raise HakobuneError(f"{os.path.relpath(full, path)}: symbolic links are not allowed in a bundle")
        for n in files:
            present.add(os.path.relpath(os.path.join(d, n), path))
    present -= {MANIFEST, SIGNATURE}
    problems = [f"{p}: missing" for p in sorted(set(listed) - present)]
    problems += [f"{p}: not in the manifest" for p in sorted(present - set(listed))]
    for rel in sorted(set(listed) & present):
        f, full = listed[rel], os.path.join(path, rel)
        if os.path.getsize(full) != f["size"]:
            problems.append(f"{rel}: wrong size")
        elif not quick:
            progress = hashing.Progress(rel, f["size"]).advance if f["size"] > 1e9 else None
            if hashing.sha256_file(full, progress) != f["sha256"]:
                problems.append(f"{rel}: content does not match the manifest")
    if problems:
        raise HakobuneError("bundle does not verify:\n  " + "\n  ".join(problems))
    log(f"bundle {manifest['release']} verified: {len(listed)} files"
        + (" (sizes only)" if quick else ""))
    return manifest
