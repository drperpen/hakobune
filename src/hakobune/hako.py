"""The Hako release contract (Hako ADR-024) as Hakobune consumes it.

Hako 0.4.0 and later put a release manifest at /usr/share/hakoteca/release.json in
the Core image. Hakobune reads it from the stored `docker save` archive (no
container is created) and records what the installer needs: Hako version, Alembic
heads, database setup steps and the settings Core requires in production.

Hako's guide links to six appliance pages that Hakobune must ship in
admin-guide/; Core indexes them through HAKOTECA_ADMIN_GUIDE_EXTRA_DIR.
"""

from __future__ import annotations

import json
import os
import re

from hakobune import docker
from hakobune.errors import HakobuneError

CORE_IMAGE = "hakoteca-core"
GATEWAY_IMAGE = "hakoteca-console-gateway"
MANIFEST_DIR = "usr/share/hakoteca/"
MANIFEST_PATH = MANIFEST_DIR + "release.json"
SCHEMA = 1
GUIDE_DIR = "admin-guide"
# Must equal APPLIANCE_PAGES in Hako's scripts/check-admin-guide.py.
REQUIRED_PAGES = (
    "appliance-overview.md",
    "appliance-install.md",
    "appliance-configuration.md",
    "appliance-upgrade.md",
    "appliance-backup-restore.md",
    "appliance-diagnostics.md",
)
PAGE_NAME = re.compile(r"^appliance-[a-z0-9][a-z0-9-]{0,70}\.md$")
FRONTMATTER = ("title", "audience", "covers", "reviewed")


def _tag(ref: str) -> str:
    return ref.rsplit(":", 1)[-1]


def read_release_manifest(image_archive: str) -> dict | None:
    """The Hako release manifest from a Core image archive; None if the image has none."""
    found = docker.read_image_files(image_archive, [MANIFEST_PATH], required=False)
    data = found.get(MANIFEST_PATH)
    if data is None:
        return None
    try:
        manifest = json.loads(data)
    except json.JSONDecodeError:
        raise HakobuneError(f"{MANIFEST_PATH} in the Hako Core image is not valid JSON") from None
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise HakobuneError(f"unsupported Hako release manifest schema {manifest.get('schema')!r}")
    return manifest


def check_release_manifest(manifest: dict, lock: dict) -> list[str]:
    """Problems between the Hako manifest and the locked images (empty when consistent)."""
    refs = {e["name"]: e["ref"] for e in lock.get("images", [])}
    images = manifest.get("images", {})
    problems = []
    if images.get("core") != refs.get(CORE_IMAGE):
        problems.append(f"Hako manifest names core image {images.get('core')!r}, the lock {refs.get(CORE_IMAGE)!r}")
    if GATEWAY_IMAGE in refs and images.get("gateway") != refs[GATEWAY_IMAGE]:
        problems.append(f"Hako manifest names gateway image {images.get('gateway')!r}, the lock {refs[GATEWAY_IMAGE]!r}")
    if _tag(refs.get(CORE_IMAGE, "")) != manifest.get("version"):
        problems.append(f"Hako manifest version {manifest.get('version')!r} does not match the core image tag")
    for key in ("alembic_heads", "database_setup", "settings"):
        if not manifest.get(key):
            problems.append(f"Hako manifest has no {key}")
    return problems


def bundle_record(manifest: dict) -> dict:
    """What the bundle manifest keeps for the installer."""
    return {
        "version": manifest["version"],
        "revision": manifest.get("revision"),
        "alembic_heads": manifest["alembic_heads"],
        "database_setup": manifest["database_setup"],
        "production_required": manifest["settings"].get("production_required", []),
        "listen": manifest.get("core", {}).get("listen"),
        "health": manifest.get("core", {}).get("health"),
    }


def _frontmatter(text: str) -> dict[str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fields = {}
    for line in text[4:end].splitlines():
        if line and not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def guide_pages(root: str) -> tuple[dict[str, bytes], list[str]]:
    """The appliance pages in <root>/admin-guide and the problems that block a release."""
    directory = os.path.join(root, GUIDE_DIR)
    pages: dict[str, bytes] = {}
    problems: list[str] = []
    names = sorted(os.listdir(directory)) if os.path.isdir(directory) else []
    for name in names:
        path = os.path.join(directory, name)
        if not name.endswith(".md"):
            continue
        if not PAGE_NAME.match(name) or os.path.islink(path) or not os.path.isfile(path):
            raise HakobuneError(f"{GUIDE_DIR}/{name}: appliance pages must be regular files named appliance-*.md")
        with open(path, "rb") as f:
            data = f.read()
        fields = _frontmatter(data.decode("utf-8"))
        missing = [k for k in FRONTMATTER if not (fields or {}).get(k) and k not in (fields or {})]
        if fields is None or missing:
            raise HakobuneError(f"{GUIDE_DIR}/{name}: frontmatter needs {', '.join(FRONTMATTER)}")
        pages[name] = data
    problems += [f"appliance guide page {GUIDE_DIR}/{p} is missing" for p in REQUIRED_PAGES if p not in pages]
    return pages, problems
