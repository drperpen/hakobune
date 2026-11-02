"""`hakobune lock`: resolve components.json into hakobune.lock.

Every pinned value is anchored upstream, not merely observed locally:

* images: the local image must resolve from the pinned ref (registry digest) or
  match the pinned image ID; the lock records the image ID that `docker load` will
  reproduce.
* model files: the file list and the hashes come from the Hugging Face metadata of
  the pinned revision. LFS files (all the weights) take the LFS sha256 that the hub
  published; they are hashed for real at `collect`. Small files are hashed now and
  their git blob ID must match the hub's.
* recipe files: read from the pinned git commit, not from the working tree.

Nothing about this machine (paths, host names) goes into the lock.
"""

from __future__ import annotations

import os
import subprocess

from hakobune import docker, hashing
from hakobune.config import Components, Local, ModelSpec, RecipeSpec
from hakobune.errors import HakobuneError
from hakobune.hfmeta import read_upstream


def resolve_image(spec) -> dict:
    local = docker.inspect(spec.ref)
    if spec.image_id and local.image_id != spec.image_id:
        raise HakobuneError(
            f"image {spec.name}: {spec.ref} is {local.image_id}, components.json pins {spec.image_id}"
        )
    if local.platform != spec.platform:
        raise HakobuneError(f"image {spec.name}: platform {local.platform}, expected {spec.platform}")
    repo_digest = spec.ref_digest
    if repo_digest is None:
        repo = spec.ref.rsplit(":", 1)[0]
        for d in local.repo_digests:
            if d.split("@", 1)[0] == repo:
                repo_digest = d.split("@", 1)[1]
    entry = {"name": spec.name, "ref": spec.ref, "image_id": local.image_id, "platform": spec.platform}
    entry["registry_digest"] = repo_digest
    entry["size"] = local.size
    if spec.note:
        entry["note"] = spec.note
    return entry


def resolve_model(spec: ModelSpec, src) -> tuple[dict, list[str]]:
    meta_dir = src.hf_metadata or src.path
    upstream, how = read_upstream(meta_dir, spec.revision)
    files = []
    for path in sorted(upstream):
        if path in spec.exclude:
            continue
        up = upstream[path]
        local = os.path.join(src.path, path)
        if not os.path.isfile(local):
            raise HakobuneError(f"model {spec.name}: {path} is missing from {src.path}")
        size = os.path.getsize(local)
        if up.size is not None and size != up.size:
            raise HakobuneError(f"model {spec.name}: {path} is {size} bytes, upstream says {up.size}")
        if up.lfs_sha256:
            sha = up.lfs_sha256
        else:
            blob = hashing.git_blob_sha1(local)
            if blob != up.git_blob:
                raise HakobuneError(f"model {spec.name}: {path} differs from upstream (git blob {blob})")
            sha = hashing.sha256_file(local)
        files.append({"path": path, "size": size, "sha256": sha})
    extra = sorted(_walk(src.path) - set(upstream) - set(spec.exclude))
    entry = {
        "name": spec.name,
        "hf_repo": spec.hf_repo,
        "revision": spec.revision,
        "verified_against": how,
        "size": sum(f["size"] for f in files),
        "files": files,
    }
    return entry, extra


def _walk(root: str) -> set[str]:
    out = set()
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".cache"]
        for f in files:
            out.add(os.path.relpath(os.path.join(d, f), root))
    return out


def git_show(repo: str, commit: str, path: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", repo, "show", f"{commit}:{path}"], capture_output=True, check=False
    )
    if proc.returncode != 0:
        raise HakobuneError(f"git: cannot read {path} at {commit[:12]} in {repo}: {proc.stderr.decode().strip()}")
    return proc.stdout


def git_blob_id(repo: str, commit: str, path: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, "rev-parse", f"{commit}:{path}"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise HakobuneError(f"git: {path} not found at {commit[:12]} in {repo}")
    return proc.stdout.strip()


def resolve_recipe(spec: RecipeSpec, repo: str) -> dict:
    files = []
    for path in sorted(spec.files):
        data = git_show(repo, spec.commit, path)
        files.append(
            {
                "path": path,
                "size": len(data),
                "sha256": hashing.sha256_bytes(data),
                "git_blob": git_blob_id(repo, spec.commit, path),
            }
        )
    return {"name": spec.name, "git": spec.git, "commit": spec.commit, "files": files}


def build_lock(components: Components, local: Local, log=print) -> dict:
    lock = {"schema": 1, "images": [], "models": [], "recipes": []}
    for spec in components.images:
        lock["images"].append(resolve_image(spec))
        log(f"image  {spec.name}: {lock['images'][-1]['image_id'][:19]}")
    for spec in components.models:
        src = local.models.get(spec.name)
        if src is None:
            raise HakobuneError(f"model {spec.name}: no local source in hakobune.local.json")
        entry, extra = resolve_model(spec, src)
        lock["models"].append(entry)
        log(f"model  {spec.name}: {len(entry['files'])} files, {entry['size'] / 1e9:.1f} GB ({entry['verified_against']})")
        for x in extra:
            log(f"       not upstream, left out: {x}")
    for spec in components.recipes:
        repo = local.recipes.get(spec.name)
        if repo is None:
            raise HakobuneError(f"recipe {spec.name}: no local clone in hakobune.local.json")
        lock["recipes"].append(resolve_recipe(spec, repo))
        log(f"recipe {spec.name}: {len(spec.files)} files at {spec.commit[:12]}")
    return lock
