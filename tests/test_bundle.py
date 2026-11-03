import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from helpers import (REVISION, TempDirTest, layer_tar, make_git_repo, make_hf_model, make_image_archive)

from hakobune import bundle, docker, hako, signing
from hakobune.config import (Components, ImageSpec, Local, LocalSource, ModelSpec, NoticeSpec, RecipeSpec)
from hakobune.errors import HakobuneError
from hakobune.lock import resolve_model, resolve_recipe
from hakobune.store import Store

NGC = b"NVIDIA DEEP LEARNING CONTAINER LICENSE\n"
HAKO_REF = "hakoteca/core:9.9.9"


def hako_manifest(**changes) -> bytes:
    data = {
        "schema": 1, "product": "Hakoteca Hako", "version": "9.9.9", "revision": "c" * 40,
        "images": {"core": HAKO_REF, "gateway": "hakoteca/console-gateway:9.9.9"},
        "alembic_heads": ["0023_conversation_purpose"],
        "database_setup": {"module": "hakoteca_core.security.postgres_roles", "steps": ["x"],
                           "grant_revision": "0009_knowledge_erasure"},
        "settings": {"production_required": ["HAKOTECA_DATABASE_URL"], "all": ["HAKOTECA_DATABASE_URL"]},
        "core": {"listen": "127.0.0.1:18030", "health": "/api/v1/health"},
    }
    data.update(changes)
    return json.dumps(data).encode()


def guide_page(name: str) -> bytes:
    return (f"---\ntitle: {name}\naudience: [system-admin]\ncovers:\n  - README.md\n"
            f"reviewed: 2026-11-03\n---\n\n# {name}\n\nText.\n").encode()


class ImageFilesTest(TempDirTest):
    def archive(self, layers):
        path = os.path.join(self.tmp, "img.tar")
        make_image_archive(path, [layer_tar(l) for l in layers])
        return path

    def test_later_layers_win_and_whiteouts_apply(self):
        path = self.archive([
            {"LICENSE": b"old", "doc/": None, "doc/a": b"a", "doc/b": b"b", "doc/gone": b"x"},
            {"LICENSE": b"new", "doc/.wh.gone": b""},
        ])
        files = docker.read_image_files(path, ["LICENSE", "doc/"])
        self.assertEqual(files, {"LICENSE": b"new", "doc/a": b"a", "doc/b": b"b"})

    def test_opaque_directory_hides_lower_layers_only(self):
        path = self.archive([{"doc/a": b"a"}, {"doc/.wh..wh..opq": b"", "doc/c": b"c"}])
        self.assertEqual(docker.read_image_files(path, ["doc/"]), {"doc/c": b"c"})

    def test_missing_and_links_are_errors(self):
        path = self.archive([{"x": b"1", "lnk": ("link", "x")}])
        with self.assertRaisesRegex(HakobuneError, "not found"):
            docker.read_image_files(path, ["nope"])
        with self.assertRaisesRegex(HakobuneError, "a link"):
            docker.read_image_files(path, ["lnk"])


class BundleTest(TempDirTest):
    def setUp(self):
        super().setUp()
        # The checkout: a git repo so build can record its commit.
        self.root = os.path.join(self.tmp, "checkout")
        os.makedirs(self.root)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        os.makedirs(os.path.join(self.root, hako.GUIDE_DIR))
        for name in hako.REQUIRED_PAGES:
            with open(os.path.join(self.root, hako.GUIDE_DIR, name), "wb") as f:
                f.write(guide_page(name))
        self._commit_root()

        model_dir = make_hf_model(self)
        repo, commit = make_git_repo(self, {"LICENSE": b"Apache-2.0\n", "map.json": b"{}\n"})
        model, _ = resolve_model(ModelSpec("m", "org/m", REVISION), LocalSource(model_dir))
        recipe = resolve_recipe(RecipeSpec("r", "https://example.invalid/r", commit, ("LICENSE", "map.json")), repo)
        img_src = os.path.join(self.tmp, "img-src.tar")
        image_id = make_image_archive(img_src, [layer_tar({"NGC-DL-CONTAINER-LICENSE": NGC, "bin/x": b"x"})])
        image = {"name": "img", "ref": "test:1", "image_id": image_id, "platform": "linux/arm64",
                 "registry_digest": None, "size": 10}
        self.hako_src = os.path.join(self.tmp, "hako-src.tar")
        hako_id = make_image_archive(self.hako_src, [layer_tar({
            "usr/": None, "usr/share/": None, "usr/share/hakoteca/": None,
            "usr/share/hakoteca/release.json": hako_manifest()})])
        hako_image = {"name": hako.CORE_IMAGE, "ref": HAKO_REF, "image_id": hako_id, "platform": "linux/arm64",
                      "registry_digest": None, "size": 10}
        self.lock = {"schema": 1, "images": [image, hako_image], "models": [model], "recipes": [recipe]}
        with open(os.path.join(self.root, "hakobune.lock"), "w") as f:
            json.dump(self.lock, f)
        self._commit_root()

        self.components = Components(
            images=(ImageSpec("img", "test:1", "linux/arm64", image_id),
                    ImageSpec(hako.CORE_IMAGE, HAKO_REF, "linux/arm64", hako_id)),
            models=(ModelSpec("m", "org/m", REVISION),),
            recipes=(RecipeSpec("r", "", commit, ("LICENSE", "map.json")),),
            notices=(
                NoticeSpec("nvidia/NGC-DL-CONTAINER-LICENSE", "image", "img", "NGC-DL-CONTAINER-LICENSE"),
                NoticeSpec("r/LICENSE", "recipe", "r", "LICENSE"),
                NoticeSpec("m/MODEL_CARD", "model", "m", "config.json"),
            ),
            review={"img": "pending", hako.CORE_IMAGE: "pending", "m": "pending", "r": "pending"},
        )
        self.store = Store(os.path.join(self.tmp, "store"), self.lock)

        sources = {"test:1": (img_src, image_id), HAKO_REF: (self.hako_src, hako_id)}

        def fake_save(ref, platform, out):
            with open(sources[ref][0], "rb") as a, open(out, "wb") as b:
                b.write(a.read())

        def fake_inspect(ref):
            return docker.LocalImage(sources[ref][1], "linux/arm64", 10, ())

        with mock.patch("hakobune.docker.inspect", side_effect=fake_inspect), \
             mock.patch("hakobune.docker.save", side_effect=fake_save), self.store.open():
            self.store.collect(Local(self.store.root, {"m": LocalSource(model_dir)}, {"r": repo}))
        self.out = os.path.join(self.tmp, "bundles")
        os.makedirs(self.out)

    def _commit_root(self):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", self.root, "commit", "-q", "--allow-empty", "-m", "x"], check=True, env=env)

    def build(self, release="2026.11.0-dev.1", components=None):
        return bundle.build(self.root, components or self.components, self.lock, self.store, release, self.out,
                            log=lambda *_: None)

    def test_dev_build_layout_and_verify(self):
        path = self.build()
        self.assertEqual(os.path.basename(path), "hakobune-2026.11.0-dev.1")
        manifest = bundle.verify_bundle(path, None, allow_unsigned=True, log=lambda *_: None)
        paths = {f["path"] for f in manifest["files"]}
        for p in ("images/img.tar", "models/m/model.safetensors", "recipes/r/map.json", "hakobune.pyz",
                  "notices/README.md", "notices/nvidia/NGC-DL-CONTAINER-LICENSE", "notices/r/LICENSE"):
            self.assertIn(p, paths)
        self.assertTrue(manifest["dev"])
        self.assertIn("third-party review of img is pending", manifest["release_blockers"])
        with open(os.path.join(path, "notices/nvidia/NGC-DL-CONTAINER-LICENSE"), "rb") as f:
            self.assertEqual(f.read(), NGC)
        with open(os.path.join(path, "notices/README.md")) as f:
            self.assertIn(bundle.NVIDIA_SOURCE_NOTICE, f.read())

    def test_bundle_carries_the_hako_contract_and_appliance_pages(self):
        manifest = bundle.verify_bundle(self.build(), None, allow_unsigned=True, log=lambda *_: None)
        paths = {f["path"] for f in manifest["files"]}
        for name in hako.REQUIRED_PAGES:
            self.assertIn(f"admin-guide/{name}", paths)
        self.assertEqual(manifest["hako"]["version"], "9.9.9")
        self.assertEqual(manifest["hako"]["alembic_heads"], ["0023_conversation_purpose"])
        self.assertEqual(manifest["hako"]["database_setup"]["grant_revision"], "0009_knowledge_erasure")
        self.assertFalse(any("Hako" in b or "appliance" in b for b in manifest["release_blockers"]))

    def _approved(self):
        return Components(self.components.images, self.components.models, self.components.recipes,
                          self.components.notices, {k: "approved" for k in self.components.review})

    def test_missing_appliance_page_blocks_a_release(self):
        os.unlink(os.path.join(self.root, hako.GUIDE_DIR, "appliance-upgrade.md"))
        self._commit_root()
        with self.assertRaisesRegex(HakobuneError, "appliance-upgrade.md is missing"):
            self.build("2026.11.0", self._approved())
        manifest = bundle.verify_bundle(self.build(), None, allow_unsigned=True, log=lambda *_: None)
        self.assertIn("appliance guide page admin-guide/appliance-upgrade.md is missing",
                      manifest["release_blockers"])

    def test_badly_named_or_unformatted_appliance_pages_are_refused(self):
        for name, data in (("upgrade.md", guide_page("x")), ("appliance-x.md", b"# No frontmatter\n")):
            path = os.path.join(self.root, hako.GUIDE_DIR, name)
            with open(path, "wb") as f:
                f.write(data)
            with self.assertRaisesRegex(HakobuneError, "admin-guide/"):
                self.build()
            os.unlink(path)

    def test_hako_image_without_a_release_manifest_blocks_a_release(self):
        image_id = make_image_archive(self.hako_src, [layer_tar({"bin/x": b"x"})])
        entry = next(e for e in self.lock["images"] if e["name"] == hako.CORE_IMAGE)
        with mock.patch.object(self.store, "image_path", return_value=self.hako_src):
            record, blockers = bundle.hako_contract(self.lock, self.store)
        self.assertIsNone(record)
        self.assertEqual(blockers, [f"{entry['ref']} has no Hako release manifest (Hako 0.4.0 or later is required)"])
        self.assertTrue(image_id)

    def test_hako_manifest_must_match_the_locked_images(self):
        problems = hako.check_release_manifest(json.loads(hako_manifest(version="9.9.8")), self.lock)
        self.assertIn("Hako manifest version '9.9.8' does not match the core image tag", problems)
        problems = hako.check_release_manifest(json.loads(hako_manifest(images={"core": "x:1"})), self.lock)
        self.assertTrue(any("core image" in p for p in problems))
        problems = hako.check_release_manifest(json.loads(hako_manifest(alembic_heads=[])), self.lock)
        self.assertIn("Hako manifest has no alembic_heads", problems)

    def test_large_files_are_hardlinked_from_the_store(self):
        path = self.build()
        a = os.stat(os.path.join(path, "models/m/model.safetensors"))
        b = os.stat(os.path.join(self.store.root, "models/m/model.safetensors"))
        self.assertEqual(a.st_ino, b.st_ino)

    def test_release_build_needs_approvals(self):
        with self.assertRaisesRegex(HakobuneError, "review of img is pending"):
            self.build("2026.11.0")
        self.assertEqual(os.listdir(self.out), [], "a refused build leaves nothing behind")

    def test_release_build_when_everything_is_approved(self):
        approved = Components(self.components.images, self.components.models, self.components.recipes,
                              self.components.notices, {k: "approved" for k in self.components.review})
        manifest = bundle.verify_bundle(self.build("2026.11.0", approved), None, allow_unsigned=True,
                                        log=lambda *_: None)
        self.assertFalse(manifest["dev"])
        self.assertEqual(manifest["release_blockers"], [])

    def test_pending_notice_blocks_release(self):
        comps = Components(self.components.images, self.components.models, self.components.recipes,
                           self.components.notices + (NoticeSpec("x/LICENSE", pending="not yet"),),
                           {k: "approved" for k in self.components.review})
        with self.assertRaisesRegex(HakobuneError, "notice x/LICENSE is pending"):
            self.build("2026.11.0", comps)

    def test_bad_release_numbers(self):
        for r in ("2026.13.0", "v2026.11.0", "2026.11", "2026.11.0-beta", "latest"):
            with self.assertRaises(HakobuneError, msg=r):
                bundle.parse_release(r)

    def test_bundles_are_immutable(self):
        self.build()
        with self.assertRaisesRegex(HakobuneError, "immutable"):
            self.build()

    def test_stale_lock_is_refused(self):
        comps = Components(self.components.images, (ModelSpec("m", "org/m", "b" * 40),), self.components.recipes,
                           self.components.notices, self.components.review)
        with self.assertRaisesRegex(HakobuneError, "hakobune lock"):
            self.build(components=comps)

    def test_tampering_and_extra_files_are_found(self):
        path = self.build("2026.11.0-dev.2")
        target = os.path.join(path, "recipes/r/map.json")
        os.unlink(target)  # replace the hardlink, so the store stays intact
        with open(target, "wb") as f:
            f.write(b"[]\n")  # same size, different content
        with open(os.path.join(path, "surprise"), "w") as f:
            f.write("x")
        with self.assertRaises(HakobuneError) as cm:
            bundle.verify_bundle(path, None, allow_unsigned=True, log=lambda *_: None)
        self.assertIn("recipes/r/map.json: content does not match", str(cm.exception))
        self.assertIn("surprise: not in the manifest", str(cm.exception))

    def test_sign_and_verify(self):
        path = self.build()
        key = os.path.join(self.tmp, "keys", "signing.key")
        fp = signing.keygen(key)
        self.assertTrue(fp.startswith("SHA256:"))
        self.assertEqual(os.stat(key).st_mode & 0o777, 0o600)
        signing.sign(os.path.join(path, "manifest.json"), key, os.path.join(path, "manifest.json.sig"))
        bundle.verify_bundle(path, key + ".pub", log=lambda *_: None)

        other = os.path.join(self.tmp, "keys", "other.key")
        signing.keygen(other)
        with self.assertRaisesRegex(HakobuneError, "does not verify"):
            bundle.verify_bundle(path, other + ".pub", log=lambda *_: None)
        with self.assertRaisesRegex(HakobuneError, "--pubkey"):
            bundle.verify_bundle(path, None, log=lambda *_: None)

    def test_signature_covers_the_manifest(self):
        path = self.build()
        key = os.path.join(self.tmp, "k")
        signing.keygen(key)
        manifest = os.path.join(path, "manifest.json")
        signing.sign(manifest, key, os.path.join(path, "manifest.json.sig"))
        os.chmod(manifest, 0o644)
        with open(manifest, "a") as f:
            f.write(" ")
        with self.assertRaisesRegex(HakobuneError, "does not verify"):
            bundle.verify_bundle(path, key + ".pub", log=lambda *_: None)

    def test_key_readable_by_others_is_refused(self):
        key = os.path.join(self.tmp, "k")
        signing.keygen(key)
        os.chmod(key, 0o644)
        with self.assertRaisesRegex(HakobuneError, "readable by others"):
            signing.sign(os.path.join(self.tmp, "x"), key, os.path.join(self.tmp, "x.sig"))

    def test_keygen_never_overwrites(self):
        key = os.path.join(self.tmp, "k")
        signing.keygen(key)
        with self.assertRaisesRegex(HakobuneError, "already exists"):
            signing.keygen(key)

    def test_installer_zipapp_is_reproducible_and_runs(self):
        pkg = os.path.join(os.path.dirname(bundle.__file__))
        a, b = os.path.join(self.tmp, "a.pyz"), os.path.join(self.tmp, "b.pyz")
        bundle.write_pyz(pkg, a)
        bundle.write_pyz(pkg, b)
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertEqual(fa.read(), fb.read())
        out = subprocess.run([sys.executable, "-I", a, "--version"], capture_output=True, text=True, check=True)
        self.assertIn("hakobune", out.stdout)


if __name__ == "__main__":
    unittest.main()
