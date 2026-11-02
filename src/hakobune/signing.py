"""Ed25519 signatures of manifest.json through the system `openssl` (ADR-001 §6).

The private key never passes through Hakobune: openssl reads it from its file. Its
contents are never printed or logged. Signing refuses a key file that others can
read.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess

from hakobune.errors import HakobuneError


def _openssl(args: list[str], what: str) -> bytes:
    try:
        proc = subprocess.run(["openssl", *args], capture_output=True, check=False)
    except FileNotFoundError:
        raise HakobuneError("openssl not found") from None
    if proc.returncode != 0:
        raise HakobuneError(f"{what} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def fingerprint(pubkey_path: str) -> str:
    der = _openssl(["pkey", "-pubin", "-in", pubkey_path, "-outform", "DER"], "reading the public key")
    return "SHA256:" + hashlib.sha256(der).hexdigest()


def keygen(key_path: str) -> str:
    """Create an Ed25519 key (mode 0600) and key_path.pub. Returns the fingerprint."""
    pub_path = key_path + ".pub"
    for p in (key_path, pub_path):
        if os.path.exists(p):
            raise HakobuneError(f"{p} already exists; not overwriting a key")
    os.makedirs(os.path.dirname(os.path.abspath(key_path)), mode=0o700, exist_ok=True)
    old = os.umask(0o077)
    try:
        _openssl(["genpkey", "-algorithm", "ed25519", "-out", key_path], "key generation")
    finally:
        os.umask(old)
    os.chmod(key_path, 0o600)
    _openssl(["pkey", "-in", key_path, "-pubout", "-out", pub_path], "public key export")
    os.chmod(pub_path, 0o644)
    return fingerprint(pub_path)


def sign(manifest_path: str, key_path: str, sig_path: str) -> None:
    mode = os.stat(key_path).st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise HakobuneError(f"{key_path} is readable by others (mode {stat.S_IMODE(mode):o}); chmod 600 it")
    _openssl(
        ["pkeyutl", "-sign", "-inkey", key_path, "-rawin", "-in", manifest_path, "-out", sig_path], "signing"
    )


def verify(manifest_path: str, sig_path: str, pubkey_path: str) -> None:
    if not os.path.exists(sig_path):
        raise HakobuneError("bundle is not signed (manifest.json.sig missing)")
    try:
        proc = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", pubkey_path, "-rawin",
             "-in", manifest_path, "-sigfile", sig_path],
            capture_output=True, check=False,
        )
    except FileNotFoundError:
        raise HakobuneError("openssl not found") from None
    if proc.returncode != 0:
        raise HakobuneError("manifest signature does not verify with the given public key")
