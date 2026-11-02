"""The artifact store: `collect`, `verify` and `status`.

Layout (gitignored, see ADR-001 §13):

    store/images/<name>.tar           docker save of exactly the locked image ID
    store/models/<name>/<path>        weights and model files, as served
    store/recipes/<name>/<path>       recipe files read from the pinned commit
    store/state.json                  hashes already verified (lets re-runs skip them)

Files land under a `.partial` name, are verified against the lock, made read-only
and only then renamed into place, so a file at its final name is always good.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
from contextlib import contextmanager

from hakobune import docker, hashing
from hakobune.config import Local
from hakobune.errors import HakobuneError
from hakobune.lock import git_show

SPACE_MARGIN = 10 * 1000**3


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


class Store:
    def __init__(self, root: str, lock: dict):
        self.root = os.path.abspath(root)
        self.lock = lock
        self.state_path = os.path.join(self.root, "state.json")
        self.state = {"files": {}, "images": {}}

    # -- state ---------------------------------------------------------------

    @contextmanager
    def open(self):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, ".lock"), "w") as lk:
            try:
                fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HakobuneError(f"another hakobune process is using {self.root}") from None
            self._load_state()
            yield self

    def _load_state(self) -> None:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            self.state = {"files": data.get("files", {}), "images": data.get("images", {})}
        except FileNotFoundError:
            pass
        except json.JSONDecodeError:
            _err("store state is unreadable; everything will be re-verified")

    def _save_state(self) -> None:
        tmp = self.state_path + ".partial"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.state_path)

    def _stat_key(self, path: str) -> dict | None:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "ino": st.st_ino}

    def _known_good(self, rel: str, sha256: str) -> bool:
        rec = self.state["files"].get(rel)
        now = self._stat_key(os.path.join(self.root, rel))
        return bool(rec and now and rec["sha256"] == sha256 and all(rec[k] == now[k] for k in now))

    def _record(self, rel: str, sha256: str) -> None:
        self.state["files"][rel] = {**self._stat_key(os.path.join(self.root, rel)), "sha256": sha256}
        self._save_state()

    # -- selection -------------------------------------------------------------

    def entries(self, only: set[str] | None):
        names = {e["name"] for k in ("images", "models", "recipes") for e in self.lock.get(k, [])}
        if only and (unknown := only - names):
            raise HakobuneError(f"not in the lock: {', '.join(sorted(unknown))}")
        for kind in ("recipes", "models", "images"):
            for e in self.lock.get(kind, []):
                if not only or e["name"] in only:
                    yield kind, e

    # -- collect ---------------------------------------------------------------

    def collect(self, local: Local, only: set[str] | None = None) -> None:
        todo = list(self.entries(only))
        self._check_space(todo)
        for kind, e in todo:
            if kind == "models":
                self._collect_model(e, local)
            elif kind == "recipes":
                self._collect_recipe(e, local)
            else:
                self._collect_image(e)

    def _check_space(self, todo) -> None:
        need = 0
        for kind, e in todo:
            if kind == "images":
                if not self._image_good(e):
                    need += e.get("size", 0)
            else:
                for f in e["files"]:
                    rel = os.path.join(kind, e["name"], f["path"])
                    if not os.path.exists(os.path.join(self.root, rel)):
                        need += f["size"]
        free = shutil.disk_usage(self.root).free
        if need + SPACE_MARGIN > free:
            raise HakobuneError(
                f"store needs {need / 1e9:.1f} GB more plus a {SPACE_MARGIN / 1e9:.0f} GB margin; "
                f"{free / 1e9:.1f} GB free on {self.root}"
            )

    def _collect_model(self, e: dict, local: Local) -> None:
        src = local.models.get(e["name"])
        if src is None:
            raise HakobuneError(f"model {e['name']}: no local source in hakobune.local.json")
        print(f"model {e['name']} ({e['size'] / 1e9:.1f} GB)", flush=True)
        for f in e["files"]:
            rel = os.path.join("models", e["name"], f["path"])
            self._place_file(rel, f, lambda partial, f=f: self._copy_from(os.path.join(src.path, f["path"]), partial, f))

    def _copy_from(self, src: str, partial: str, f: dict) -> str:
        progress = hashing.Progress(f["path"], f["size"]).advance if f["size"] > 1e9 else None
        sha, _size = hashing.copy_and_hash(src, partial, progress)
        return sha

    def _collect_recipe(self, e: dict, local: Local) -> None:
        repo = local.recipes.get(e["name"])
        if repo is None:
            raise HakobuneError(f"recipe {e['name']}: no local clone in hakobune.local.json")
        print(f"recipe {e['name']} at {e['commit'][:12]}", flush=True)
        for f in e["files"]:
            rel = os.path.join("recipes", e["name"], f["path"])

            def write(partial, f=f):
                data = git_show(repo, e["commit"], f["path"])
                with open(partial, "wb") as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                return hashing.sha256_bytes(data)

            self._place_file(rel, f, write)

    def _place_file(self, rel: str, f: dict, produce) -> None:
        dst = os.path.join(self.root, rel)
        if self._known_good(rel, f["sha256"]):
            print(f"  ok      {f['path']}", flush=True)
            return
        if os.path.exists(dst):
            progress = hashing.Progress(f["path"], f["size"]).advance if f["size"] > 1e9 else None
            if os.path.getsize(dst) == f["size"] and hashing.sha256_file(dst, progress) == f["sha256"]:
                self._record(rel, f["sha256"])
                print(f"  ok      {f['path']} (re-verified)", flush=True)
                return
            _err(f"  replacing bad store copy of {f['path']}")
            os.unlink(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        partial = dst + ".partial"
        try:
            sha = produce(partial)
            size = os.path.getsize(partial)
            if size != f["size"] or sha != f["sha256"]:
                raise HakobuneError(
                    f"{rel}: source does not match the lock (got {size} bytes, sha256 {sha}); "
                    "nothing was stored"
                )
            os.chmod(partial, 0o444)
            os.replace(partial, dst)
        finally:
            if os.path.exists(partial):
                os.unlink(partial)
        self._record(rel, f["sha256"])
        print(f"  stored  {f['path']}", flush=True)

    def image_path(self, e: dict) -> str:
        return os.path.join(self.root, "images", f"{e['name']}.tar")

    def image_sha256(self, e: dict) -> str:
        """The archive's sha256, re-verifying it unless the state shows it unchanged."""
        if not self._image_good(e):
            path = self.image_path(e)
            if not os.path.exists(path):
                raise HakobuneError(f"image {e['name']} is not in the store; run 'hakobune collect'")
            print(f"verifying image {e['name']}", flush=True)
            self._record_image(e, docker.verify_archive(path, e["image_id"]))
        return self.state["images"][e["name"]]["sha256"]

    def require_good(self, rel: str, f: dict) -> None:
        """Make sure a store file matches the lock, hashing it unless the state shows it unchanged."""
        if self._known_good(rel, f["sha256"]):
            return
        path = os.path.join(self.root, rel)
        if not os.path.exists(path):
            raise HakobuneError(f"{rel} is not in the store; run 'hakobune collect'")
        progress = hashing.Progress(f["path"], f["size"]).advance if f["size"] > 1e9 else None
        if os.path.getsize(path) != f["size"] or hashing.sha256_file(path, progress) != f["sha256"]:
            raise HakobuneError(f"{rel} in the store does not match the lock; run 'hakobune collect'")
        self._record(rel, f["sha256"])

    def _image_good(self, e: dict) -> bool:
        rec = self.state["images"].get(e["name"])
        now = self._stat_key(self.image_path(e))
        return bool(rec and now and rec["image_id"] == e["image_id"] and all(rec[k] == now[k] for k in now))

    def _collect_image(self, e: dict) -> None:
        print(f"image {e['name']} ({e.get('size', 0) / 1e9:.1f} GB)", flush=True)
        if self._image_good(e):
            print("  ok", flush=True)
            return
        dst = self.image_path(e)
        local = docker.inspect(e["ref"])
        if local.image_id != e["image_id"]:
            raise HakobuneError(f"image {e['name']}: {e['ref']} is now {local.image_id}, lock pins {e['image_id']}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        partial = dst + ".partial"
        if os.path.exists(dst):
            try:
                self._record_image(e, docker.verify_archive(dst, e["image_id"]))
                print("  ok      (re-verified)", flush=True)
                return
            except HakobuneError as err:
                _err(f"  replacing bad store archive: {err}")
                os.unlink(dst)
        try:
            docker.save(e["ref"], e["platform"], partial)
            check = docker.verify_archive(partial, e["image_id"])
            os.chmod(partial, 0o444)
            os.replace(partial, dst)
        finally:
            if os.path.exists(partial):
                os.unlink(partial)
        self._record_image(e, check)
        print(f"  stored  {check.layers} layers, {check.size / 1e9:.1f} GB", flush=True)

    def _record_image(self, e: dict, check) -> None:
        self.state["images"][e["name"]] = {
            **self._stat_key(self.image_path(e)),
            "image_id": e["image_id"],
            "sha256": check.sha256,
        }
        self._save_state()

    # -- verify / status ---------------------------------------------------------

    def verify(self, only: set[str] | None = None) -> list[str]:
        """Re-hash everything in the store against the lock. Returns the problems."""
        problems = []
        for kind, e in self.entries(only):
            print(f"{kind[:-1]} {e['name']}", flush=True)
            if kind == "images":
                path = self.image_path(e)
                if not os.path.exists(path):
                    problems.append(f"{e['name']}: image archive missing")
                    continue
                try:
                    check = docker.verify_archive(path, e["image_id"])
                except HakobuneError as err:
                    problems.append(str(err))
                    continue
                self._record_image(e, check)
                print("  ok", flush=True)
                continue
            for f in e["files"]:
                rel = os.path.join(kind, e["name"], f["path"])
                path = os.path.join(self.root, rel)
                if not os.path.exists(path):
                    problems.append(f"{rel}: missing")
                    continue
                if os.path.getsize(path) != f["size"]:
                    problems.append(f"{rel}: wrong size")
                    continue
                progress = hashing.Progress(f["path"], f["size"]).advance if f["size"] > 1e9 else None
                if hashing.sha256_file(path, progress) != f["sha256"]:
                    problems.append(f"{rel}: content does not match the lock")
                    continue
                self._record(rel, f["sha256"])
        if not only:
            problems += [f"{x}: not in the lock" for x in self.extras()]
        return problems

    def extras(self) -> list[str]:
        expected = {"state.json", ".lock"}
        for kind, e in self.entries(None):
            if kind == "images":
                expected.add(os.path.relpath(self.image_path(e), self.root))
            else:
                expected.update(os.path.join(kind, e["name"], f["path"]) for f in e["files"])
        found = set()
        for d, _dirs, files in os.walk(self.root):
            for f in files:
                found.add(os.path.relpath(os.path.join(d, f), self.root))
        return sorted(found - expected)

    def status(self) -> list[tuple[str, str, str]]:
        rows = []
        for kind, e in self.entries(None):
            if kind == "images":
                if self._image_good(e):
                    s = "verified"
                elif os.path.exists(self.image_path(e)):
                    s = "present, not verified"
                else:
                    s = "missing"
                rows.append((kind[:-1], e["name"], s))
                continue
            counts = {"verified": 0, "unverified": 0, "missing": 0}
            for f in e["files"]:
                rel = os.path.join(kind, e["name"], f["path"])
                if self._known_good(rel, f["sha256"]):
                    counts["verified"] += 1
                elif os.path.exists(os.path.join(self.root, rel)):
                    counts["unverified"] += 1
                else:
                    counts["missing"] += 1
            n = len(e["files"])
            s = "verified" if counts["verified"] == n else ", ".join(f"{v} {k}" for k, v in counts.items() if v)
            rows.append((kind[:-1], e["name"], s))
        return rows

