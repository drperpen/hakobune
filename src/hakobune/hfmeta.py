"""Upstream file identities from the Hugging Face metadata that `hf download` leaves
beside a local download (`<dir>/.cache/huggingface/`).

Two sources, both written by huggingface_hub:

* `trees/<revision>.json`: the repository's file list at that revision, with each
  file's size, git blob ID and, for LFS files, the LFS sha256.
* `download/<path>.metadata`: per downloaded file, three lines: commit, ETag,
  timestamp. The ETag is the LFS sha256 (64 hex) for LFS files and the git blob ID
  (40 hex) for regular files.

The tree is preferred because it also says which files exist upstream.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from hakobune.config import check_relpath
from hakobune.errors import HakobuneError

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class UpstreamFile:
    path: str
    size: int | None  # None when only download metadata is available
    lfs_sha256: str | None
    git_blob: str | None


def read_upstream(meta_dir: str, revision: str) -> tuple[dict[str, UpstreamFile], str]:
    """Return ({path: UpstreamFile}, source description) for a revision."""
    hf = os.path.join(meta_dir, ".cache", "huggingface")
    tree_path = os.path.join(hf, "trees", f"{revision}.json")
    if os.path.isfile(tree_path):
        return _from_tree(tree_path), "hf-tree"
    dl = os.path.join(hf, "download")
    if os.path.isdir(dl):
        return _from_download_metadata(dl, revision), "hf-download-metadata"
    raise HakobuneError(
        f"no Hugging Face metadata for revision {revision} under {hf}; "
        "cannot prove where these files came from"
    )


def _from_tree(path: str) -> dict[str, UpstreamFile]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for name, info in data.get("files", {}).items():
        check_relpath(name, path)
        lfs = info.get("lfs_sha256")
        out[name] = UpstreamFile(name, int(info["size"]), lfs, info.get("blob_id"))
    if not out:
        raise HakobuneError(f"{path}: empty file list")
    return out


def _from_download_metadata(dl: str, revision: str) -> dict[str, UpstreamFile]:
    out = {}
    for root, _dirs, files in os.walk(dl):
        for fname in files:
            if not fname.endswith(".metadata"):
                continue
            meta_path = os.path.join(root, fname)
            rel = os.path.relpath(meta_path, dl)[: -len(".metadata")]
            check_relpath(rel, meta_path)
            with open(meta_path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            if len(lines) < 2:
                raise HakobuneError(f"{meta_path}: malformed")
            commit, etag = lines[0].strip(), lines[1].strip().strip('"')
            if commit != revision:
                raise HakobuneError(f"{rel}: downloaded from commit {commit}, expected {revision}")
            if _HEX64.match(etag):
                out[rel] = UpstreamFile(rel, None, etag, None)
            elif _HEX40.match(etag):
                out[rel] = UpstreamFile(rel, None, None, etag)
            else:
                raise HakobuneError(f"{meta_path}: unrecognised ETag {etag!r}")
    if not out:
        raise HakobuneError(f"{dl}: no download metadata")
    return out
