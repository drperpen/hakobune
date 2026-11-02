"""The three inputs: components.json (what to ship, in git), hakobune.lock (exact
bytes, in git, generated) and hakobune.local.json (where this machine keeps the
sources, gitignored)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from hakobune.errors import HakobuneError

SCHEMA = 1
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


def _load_json(path: str, what: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise HakobuneError(f"{what} not found: {path}") from None
    except json.JSONDecodeError as e:
        raise HakobuneError(f"{what} is not valid JSON: {path}: {e}") from None
    if not isinstance(data, dict):
        raise HakobuneError(f"{what} must be a JSON object: {path}")
    return data


def _check_name(name: str, seen: set[str], what: str) -> None:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise HakobuneError(f"{what}: invalid name {name!r} (lowercase letters, digits, '.', '-')")
    if name in seen:
        raise HakobuneError(f"{what}: duplicate name {name!r}")
    seen.add(name)


def check_relpath(path: str, what: str) -> None:
    """A path inside a component: relative, normalised, no '..'."""
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\\" in path
        or os.path.normpath(path) != path
        or path.split("/")[0] == ".."
    ):
        raise HakobuneError(f"{what}: unsafe path {path!r}")


@dataclass(frozen=True)
class ImageSpec:
    name: str
    ref: str
    platform: str
    image_id: str | None = None  # required when ref is a mutable tag
    note: str = ""

    @property
    def ref_digest(self) -> str | None:
        return self.ref.split("@", 1)[1] if "@" in self.ref else None


@dataclass(frozen=True)
class ModelSpec:
    name: str
    hf_repo: str
    revision: str
    exclude: tuple[str, ...] = (".gitattributes",)


@dataclass(frozen=True)
class RecipeSpec:
    name: str
    git: str
    commit: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class NoticeSpec:
    """A file for the bundle's notices/: copied from a component, or still pending."""

    to: str  # path under notices/; ends in "/" when path is a directory prefix
    kind: str | None = None  # image | model | recipe
    source: str | None = None  # component name
    path: str | None = None  # exact path, or prefix ending in "/"
    pending: str | None = None  # why it cannot be shipped yet


REVIEW_STATES = ("pending", "approved")


@dataclass(frozen=True)
class Components:
    images: tuple[ImageSpec, ...]
    models: tuple[ModelSpec, ...]
    recipes: tuple[RecipeSpec, ...]
    notices: tuple[NoticeSpec, ...] = ()
    review: dict = field(default_factory=dict)  # component name -> pending | approved


def load_components(path: str) -> Components:
    data = _load_json(path, "components file")
    if data.get("schema") != SCHEMA:
        raise HakobuneError(f"{path}: unsupported schema {data.get('schema')!r}, expected {SCHEMA}")
    seen: set[str] = set()
    images = []
    for item in data.get("images", []):
        _check_name(item.get("name"), seen, path)
        ref, image_id = item.get("ref"), item.get("image_id")
        if not isinstance(ref, str) or not ref:
            raise HakobuneError(f"{path}: image {item['name']}: missing ref")
        if "@" in ref:
            if not SHA256_ID.match(ref.split("@", 1)[1]):
                raise HakobuneError(f"{path}: image {item['name']}: bad digest in ref")
        elif image_id is None:
            raise HakobuneError(
                f"{path}: image {item['name']}: tag ref {ref!r} is mutable; pin it with image_id"
            )
        if image_id is not None and not SHA256_ID.match(image_id):
            raise HakobuneError(f"{path}: image {item['name']}: bad image_id")
        images.append(
            ImageSpec(item["name"], ref, item.get("platform", "linux/arm64"), image_id, item.get("note", ""))
        )
    models = []
    for item in data.get("models", []):
        _check_name(item.get("name"), seen, path)
        rev = item.get("revision")
        if not isinstance(rev, str) or not HEX40.match(rev):
            raise HakobuneError(f"{path}: model {item['name']}: revision must be a full 40-hex commit")
        if not isinstance(item.get("hf_repo"), str) or item["hf_repo"].count("/") != 1:
            raise HakobuneError(f"{path}: model {item['name']}: hf_repo must be 'org/name'")
        models.append(ModelSpec(item["name"], item["hf_repo"], rev, tuple(item.get("exclude", [".gitattributes"]))))
    recipes = []
    for item in data.get("recipes", []):
        _check_name(item.get("name"), seen, path)
        commit = item.get("commit")
        if not isinstance(commit, str) or not HEX40.match(commit):
            raise HakobuneError(f"{path}: recipe {item['name']}: commit must be a full 40-hex commit")
        files = tuple(item.get("files", []))
        if not files:
            raise HakobuneError(f"{path}: recipe {item['name']}: no files listed")
        for f in files:
            check_relpath(f, f"{path}: recipe {item['name']}")
        recipes.append(RecipeSpec(item["name"], item.get("git", ""), commit, files))
    review = {}
    for kind in ("images", "models", "recipes"):
        for item in data.get(kind, []):
            state = item.get("review", "pending")
            if state not in REVIEW_STATES:
                raise HakobuneError(f"{path}: {item['name']}: review must be one of {REVIEW_STATES}")
            review[item["name"]] = state
    notices = []
    kinds = {"image": {i.name for i in images}, "model": {m.name for m in models}, "recipe": {r.name for r in recipes}}
    for item in data.get("notices", []):
        to = item.get("to", "")
        check_relpath(to.rstrip("/"), f"{path}: notice")
        if "pending" in item:
            notices.append(NoticeSpec(to, pending=str(item["pending"])))
            continue
        kind, _, source = str(item.get("from", "")).partition(":")
        if source not in kinds.get(kind, ()):
            raise HakobuneError(f"{path}: notice {to}: unknown source {item.get('from')!r}")
        src_path = item.get("path", "")
        check_relpath(src_path.rstrip("/"), f"{path}: notice {to}")
        if src_path.endswith("/") != to.endswith("/"):
            raise HakobuneError(f"{path}: notice {to}: a directory must be copied to a directory")
        notices.append(NoticeSpec(to, kind, source, src_path))
    return Components(tuple(images), tuple(models), tuple(recipes), tuple(notices), review)


@dataclass(frozen=True)
class LocalSource:
    path: str
    hf_metadata: str | None = None  # folder holding .cache/huggingface, if not path itself


@dataclass
class Local:
    store: str
    models: dict[str, LocalSource] = field(default_factory=dict)
    recipes: dict[str, str] = field(default_factory=dict)


def load_local(path: str, base_dir: str) -> Local:
    data = _load_json(path, "local sources file (copy hakobune.local.example.json)")

    def resolve(p: str) -> str:
        p = os.path.expanduser(p)
        return p if os.path.isabs(p) else os.path.join(base_dir, p)

    models = {}
    for name, item in data.get("models", {}).items():
        if isinstance(item, str):
            item = {"path": item}
        meta = item.get("hf_metadata")
        models[name] = LocalSource(resolve(item["path"]), resolve(meta) if meta else None)
    recipes = {name: resolve(p) for name, p in data.get("recipes", {}).items()}
    return Local(resolve(data.get("store", "store")), models, recipes)


def load_lock(path: str) -> dict:
    data = _load_json(path, "lockfile (run 'hakobune lock')")
    if data.get("schema") != SCHEMA:
        raise HakobuneError(f"{path}: unsupported lock schema {data.get('schema')!r}")
    for kind in ("images", "models", "recipes"):
        for entry in data.get(kind, []):
            for f in entry.get("files", []):
                check_relpath(f["path"], f"{path}: {entry['name']}")
    return data


def dump_lock(lock: dict) -> str:
    return json.dumps(lock, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
