"""File hashing and copying that stays out of the page cache.

PGX serves models from the same files Hakobune reads (the store copies them from
the very inodes the Qwen container mounts, and vLLM streams the 53 GB PLE table
from disk on demand). Reading 124 GB through the page cache would evict the pages
the live server depends on. So sources are read with O_DIRECT where the file
system allows it, and pages Hakobune writes are dropped as soon as they are on
disk. Pages of *source* files are never dropped: they may be the server's.
"""

from __future__ import annotations

import hashlib
import mmap
import os
import sys
import time
from typing import Callable

CHUNK = 16 * 1024 * 1024
_DROP_EVERY = 256 * 1024 * 1024


def git_blob_sha1(path: str) -> str:
    """The git object ID of a file's content, as Hugging Face reports for non-LFS files."""
    size = os.path.getsize(path)
    h = hashlib.sha1(b"blob %d\0" % size)
    with open(path, "rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _open_source(path: str) -> tuple[int, bool]:
    flag = getattr(os, "O_DIRECT", 0)
    if flag:
        try:
            return os.open(path, os.O_RDONLY | flag), True
        except OSError:
            pass
    return os.open(path, os.O_RDONLY), False


def _read_chunks(path: str):
    """Yield memoryviews of the file's content, using O_DIRECT when possible.

    Each view is only valid until the next one is requested.
    """
    fd, direct = _open_source(path)
    buf = mmap.mmap(-1, CHUNK)  # page aligned, as O_DIRECT requires
    try:
        while True:
            try:
                n = os.readv(fd, [buf])
            except OSError:
                if not direct:
                    raise
                # The file system accepted O_DIRECT at open but not for reads.
                pos = os.lseek(fd, 0, os.SEEK_CUR)
                os.close(fd)
                fd, direct = os.open(path, os.O_RDONLY), False
                os.lseek(fd, pos, os.SEEK_SET)
                continue
            if n == 0:
                return
            view = memoryview(buf)[:n]
            try:
                yield view
            finally:
                view.release()
    finally:
        os.close(fd)
        buf.close()


class Progress:
    """Prints a throttled progress line to stderr for long reads."""

    def __init__(self, label: str, total: int, stream=None):
        self.label, self.total = label, total
        self.stream = stream if stream is not None else sys.stderr
        self.done = 0
        self.start = self.last = time.monotonic()

    def advance(self, n: int) -> None:
        self.done += n
        now = time.monotonic()
        if now - self.last >= 10 or self.done == self.total:
            self.last = now
            rate = self.done / max(now - self.start, 1e-6) / 1e6
            pct = 100.0 * self.done / self.total if self.total else 100.0
            print(f"  {self.label}: {pct:5.1f}% ({rate:,.0f} MB/s)", file=self.stream, flush=True)


def sha256_file(path: str, progress: Callable[[int], None] | None = None) -> str:
    h = hashlib.sha256()
    for view in _read_chunks(path):
        h.update(view)
        if progress:
            progress(len(view))
    return h.hexdigest()


def copy_and_hash(src: str, dst: str, progress: Callable[[int], None] | None = None) -> tuple[str, int]:
    """Copy src to dst (created or truncated), returning (sha256, size).

    dst is fsynced before returning. The caller verifies the hash and renames.
    """
    h = hashlib.sha256()
    size = 0
    out = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        since_drop = 0
        for view in _read_chunks(src):
            h.update(view)
            off = 0
            while off < len(view):
                off += os.write(out, view[off:])
            size += len(view)
            since_drop += len(view)
            if progress:
                progress(len(view))
            if since_drop >= _DROP_EVERY:
                _flush_and_drop(out)
                since_drop = 0
        _flush_and_drop(out)
    finally:
        os.close(out)
    return h.hexdigest(), size


def _flush_and_drop(fd: int) -> None:
    os.fdatasync(fd)
    if hasattr(os, "posix_fadvise"):
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
