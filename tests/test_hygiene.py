"""Committed manifests must not carry anything about a particular machine or site."""

import os
import re
import unittest

from helpers import ROOT

FILES = ["components.json", "hakobune.lock"]
FORBIDDEN = [
    (re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"), "IPv4 address"),
    (re.compile(r'"(?:/home/|/root/|/Users/|~/)'), "home path"),
    (re.compile(r'"/(?:tmp|var|opt|etc|srv|mnt|media)/'), "absolute host path"),
    (re.compile(r"\.(?:local|lan|internal|corp|home\.arpa)\b"), "local host name"),
    (re.compile(r"thinkstation|pgx", re.I), "build machine name"),
    (re.compile(r"BEGIN [A-Z ]*PRIVATE KEY|api[_-]?key|password|secret", re.I), "secret"),
]


class HygieneTest(unittest.TestCase):
    def test_manifests_are_machine_neutral(self):
        for name in FILES:
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for pattern, what in FORBIDDEN:
                m = pattern.search(text)
                self.assertIsNone(m, f"{name} contains a {what}: {m and m.group(0)!r}")

    def test_local_sources_file_is_ignored(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            ignored = f.read().split()
        for entry in ("/store/", "/bundles/", "hakobune.local.json", "*.partial"):
            self.assertIn(entry, ignored)


if __name__ == "__main__":
    unittest.main()
