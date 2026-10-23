"""Internal installer preparation must not install a driver or accept tampered files."""

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("autolog_test_npcap", ROOT / "packaging/npcap_bundle.py")
npcap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(npcap)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root, package, cache = (tmp_path / name for name in ("source", "package", "cache"))
    (root / "packaging").mkdir(parents=True)
    cache.mkdir()
    for name in ("wireshark_bundle.py", "NPCAP_INSTALLATION.txt", "npcap.lock.json"):
        shutil.copy2(ROOT / "packaging" / name, root / "packaging" / name)
    lock = json.loads((root / "packaging/npcap.lock.json").read_text(encoding="utf-8"))
    for name in ("installer", "license"):
        data = (name + " fixture; never executed").encode()
        item = lock[name]
        item.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        (cache / item["name"]).write_bytes(data)
    (root / "packaging/npcap.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    verified = []
    monkeypatch.setattr(npcap, "verify_signature", lambda path: verified.append(path) or {
        "status": "Valid", "subject": "CN=Nmap Software LLC", "thumbprint": "fixture"})
    return root, package, cache, lock, verified


def test_internal_bundle_contains_original_installer_license_guidance_and_hashes(bundle):
    root, package, cache, lock, verified = bundle
    result = npcap.bundle_npcap(root, package, cache, SimpleNamespace(info=lambda *_: None))
    assert result["scope"] == "internal-single-pc" and result["version"] == "1.90"
    assert not result["installer_executed_by_build"]
    assert verified == [cache / lock["installer"]["name"]]
    installer = package / result["path"]
    assert installer.read_bytes() == (cache / lock["installer"]["name"]).read_bytes()
    folder = installer.parent
    assert (folder / "LICENSE.txt").read_bytes() == (cache / lock["license"]["name"]).read_bytes()
    instructions = (folder / "READ_ME_FIRST.txt").read_text(encoding="utf-8")
    assert all(word in instructions for word in ("한국어", "English", "中文", "administrator", "already installed"))
    manifest = json.loads((folder / "bundle_manifest.json").read_text(encoding="utf-8"))
    assert manifest["installation_required_on_target"] and not manifest["installer_executed_by_build"]
    for item in manifest["files"]:
        data = (package / item["path"]).read_bytes()
        assert len(data) == item["bytes"] and hashlib.sha256(data).hexdigest() == item["sha256"]
    assert not list(package.rglob("*.sys"))


@pytest.mark.parametrize("damage", ["installer", "license", "signature", "url", "scope"])
def test_tampered_or_wrong_scope_installer_is_not_packaged(bundle, monkeypatch, damage):
    root, package, cache, lock, _verified = bundle
    if damage in {"installer", "license"}:
        (cache / lock[damage]["name"]).write_bytes(b"tampered")
    elif damage == "signature":
        def invalid(_path):
            raise ValueError("Invalid signature")
        monkeypatch.setattr(npcap, "verify_signature", invalid)
    else:
        if damage == "url":
            lock["installer"]["url"] = "https://example.invalid/npcap.exe"
        else:
            lock["scope"] = "external"
        (root / "packaging/npcap.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(ValueError):
        npcap.bundle_npcap(root, package, cache, SimpleNamespace(info=lambda *_: None))
    assert not package.exists()


@pytest.mark.parametrize("status,subject,valid", [
    ("Valid", "CN=Nmap Software LLC, O=Nmap Software LLC", True),
    ("NotSigned", "", False), ("HashMismatch", "CN=Nmap Software LLC", False),
    ("Valid", "CN=Other Publisher", False), ("Valid", "CN=Nmap Software LLC Fake", False),
])
def test_authenticode_requires_valid_nmap_signer_and_never_executes_installer(tmp_path, monkeypatch, status, subject, valid):
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"status": status, "subject": subject}), stderr="")

    monkeypatch.setattr(npcap.subprocess, "run", run)
    path = tmp_path / "한글 폴더 with spaces" / "npcap-1.90.exe"
    if valid:
        assert npcap.verify_signature(path)["status"] == "Valid"
    else:
        with pytest.raises(ValueError):
            npcap.verify_signature(path)
    assert len(commands) == 1
    command, kwargs = commands[0]
    assert Path(command[0]).name == "powershell.exe" and str(path) not in command[-1]
    assert "Get-AuthenticodeSignature -LiteralPath" in command[-1]
    assert kwargs["env"]["ONECLICKLOG_NPCAP_VERIFY"] == str(path)
    assert kwargs["timeout"] == 30
