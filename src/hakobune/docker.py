"""Docker access for the build side, and offline verification of `docker save` files.

On PGX Hakobune may only read (AGENTS.md). The wrapper below therefore runs only
`docker image inspect` and `docker save`, and refuses anything else, so a bug cannot
start, stop, pull or remove anything there.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tarfile
from dataclasses import dataclass

from hakobune.errors import HakobuneError

_READ_ONLY = {("image", "inspect"), ("save",)}
_BLOB = re.compile(r"^blobs/sha256/([0-9a-f]{64})$")


def run_docker(args: list[str]) -> str:
    if tuple(args[:2]) not in _READ_ONLY and tuple(args[:1]) not in _READ_ONLY:
        raise HakobuneError(f"refusing docker {' '.join(args[:2])}: build side is read-only")
    try:
        proc = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise HakobuneError("docker not found") from None
    if proc.returncode != 0:
        raise HakobuneError(f"docker {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout


@dataclass(frozen=True)
class LocalImage:
    image_id: str
    platform: str
    size: int
    repo_digests: tuple[str, ...]


def inspect(ref: str) -> LocalImage:
    out = run_docker(["image", "inspect", "--format", "{{json .}}", ref])
    info = json.loads(out)
    platform = f"{info['Os']}/{info['Architecture']}"
    # arm64 images may or may not carry the default variant v8; both mean linux/arm64.
    if info.get("Variant") and not (info["Architecture"] == "arm64" and info["Variant"] == "v8"):
        platform += f"/{info['Variant']}"
    return LocalImage(info["Id"], platform, int(info.get("Size", 0)), tuple(info.get("RepoDigests") or ()))


def save(ref: str, platform: str, out_path: str) -> None:
    run_docker(["save", "--platform", platform, "-o", out_path, ref])


class _HashingReader:
    """File wrapper that hashes everything read through it."""

    def __init__(self, f):
        self.f, self.h, self.size = f, hashlib.sha256(), 0

    def read(self, n=-1):
        data = self.f.read(n)
        self.h.update(data)
        self.size += len(data)
        return data

    def drain(self):
        while self.read(16 * 1024 * 1024):
            pass


@dataclass(frozen=True)
class ArchiveCheck:
    sha256: str
    size: int
    layers: int


def verify_archive(path: str, image_id: str) -> ArchiveCheck:
    """Prove a `docker save` file holds exactly the image `image_id`.

    The config blob must hash to the image ID; the config's rootfs.diff_ids must be
    the manifest's layers, in order; and every blob must hash to its own name. That
    chains every byte that `docker load` will use back to the locked image ID.
    """
    want = image_id.removeprefix("sha256:")
    blobs: dict[str, int] = {}
    manifest = config = None
    with open(path, "rb") as raw:
        reader = _HashingReader(raw)
        try:
            with tarfile.open(fileobj=reader, mode="r|") as tar:
                for member in tar:
                    if not member.isfile():
                        continue
                    m = _BLOB.match(member.name)
                    if member.name == "manifest.json" or m:
                        f = tar.extractfile(member)
                        h = hashlib.sha256()
                        keep = bytearray() if (not m or m.group(1) == want) else None
                        while block := f.read(16 * 1024 * 1024):
                            h.update(block)
                            if keep is not None:
                                keep += block
                        if m:
                            if h.hexdigest() != m.group(1):
                                raise HakobuneError(f"{path}: blob {m.group(1)[:12]} is corrupt")
                            blobs[m.group(1)] = member.size
                            if m.group(1) == want:
                                config = json.loads(keep)
                        else:
                            manifest = json.loads(keep)
        except tarfile.TarError as e:
            raise HakobuneError(f"{path}: not a valid image archive: {e}") from None
        reader.drain()
    if manifest is None or not isinstance(manifest, list) or len(manifest) != 1:
        raise HakobuneError(f"{path}: expected exactly one image in manifest.json")
    entry = manifest[0]
    if entry.get("Config") != f"blobs/sha256/{want}" or config is None:
        raise HakobuneError(f"{path}: does not contain image {image_id}")
    layers = [l.removeprefix("blobs/sha256/") for l in entry.get("Layers", [])]
    for layer in layers:
        if layer not in blobs:
            raise HakobuneError(f"{path}: layer {layer[:12]} missing")
    diff_ids = [d.removeprefix("sha256:") for d in config.get("rootfs", {}).get("diff_ids", [])]
    if diff_ids != layers:
        raise HakobuneError(f"{path}: layers do not match the image config's diff_ids")
    return ArchiveCheck(reader.h.hexdigest(), reader.size, len(layers))
