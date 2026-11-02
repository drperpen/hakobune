import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        for d, _dirs, files in os.walk(self.tmp):
            for f in files:
                os.chmod(os.path.join(d, f), 0o644)
        self._tmp.cleanup()

    def write(self, rel: str, data: bytes) -> str:
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path


REVISION = "a" * 40
SMALL = b'{"architectures": ["Test"]}\n'
BIG = os.urandom(3 * 1024 * 1024 + 123)  # stands in for an LFS weight file


def make_hf_model(test: TempDirTest, name="model", tree=True, revision=REVISION) -> str:
    """A model folder laid out the way `hf download --local-dir` leaves it."""
    base = os.path.join(test.tmp, name)
    test.write(f"{name}/config.json", SMALL)
    test.write(f"{name}/model.safetensors", BIG)
    test.write(f"{name}/.gitattributes", b"*.safetensors filter=lfs\n")
    hf = f"{name}/.cache/huggingface"
    if tree:
        files = {
            "config.json": {"size": len(SMALL), "blob_id": git_blob(SMALL)},
            "model.safetensors": {"size": len(BIG), "blob_id": "0" * 40, "lfs_sha256": sha(BIG)},
            ".gitattributes": {"size": 25, "blob_id": "1" * 40},
        }
        test.write(f"{hf}/trees/{revision}.json", json.dumps({"format_version": 1, "files": files}).encode())
    else:
        test.write(f"{hf}/download/config.json.metadata", f"{revision}\n{git_blob(SMALL)}\n1.0\n".encode())
        test.write(f"{hf}/download/model.safetensors.metadata", f"{revision}\n{sha(BIG)}\n1.0\n".encode())
    return base


def make_git_repo(test: TempDirTest, files: dict[str, bytes]) -> tuple[str, str]:
    repo = os.path.join(test.tmp, "recipe")
    os.makedirs(repo)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    subprocess.run(["git", "init", "-q", repo], check=True, env=env)
    for rel, data in files.items():
        test.write(os.path.join("recipe", rel), data)
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "x"], check=True, env=env)
    commit = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    return repo, commit


def layer_tar(files: dict) -> bytes:
    """An image layer: {path: bytes} for files, {path: None} for a directory,
    {path: ("link", target)} for a symlink."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif isinstance(data, tuple):
                info.type, info.linkname = tarfile.SYMTYPE, data[1]
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def make_image_archive(path: str, layers: list[bytes], tamper_layer: bool = False,
                       diff_ids: list[str] | None = None) -> str:
    """A `docker save` style archive; returns its image ID."""
    layer_ids = [sha(l) for l in layers]
    config = json.dumps({
        "architecture": "arm64", "os": "linux",
        "rootfs": {"type": "layers", "diff_ids": ["sha256:" + d for d in (diff_ids or layer_ids)]},
    }).encode()
    image_id = sha(config)
    manifest = json.dumps([{
        "Config": f"blobs/sha256/{image_id}", "RepoTags": ["test:1"],
        "Layers": [f"blobs/sha256/{d}" for d in layer_ids],
    }]).encode()
    with tarfile.open(path, "w") as tar:
        def add(name, data):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for d, l in zip(layer_ids, layers):
            add(f"blobs/sha256/{d}", l + (b"x" if tamper_layer else b""))
        add(f"blobs/sha256/{image_id}", config)
        add("manifest.json", manifest)
    return "sha256:" + image_id
