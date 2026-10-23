"""Prepare an unmodified, signed Npcap installer for the requested internal PC.

This does not run the installer, extract driver files or grant redistribution rights.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def verify_signature(path):
    command = (
        "$ErrorActionPreference='Stop';"
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
        "$s=Get-AuthenticodeSignature -LiteralPath $env:ONECLICKLOG_NPCAP_VERIFY;"
        "@{status=$s.Status.ToString();subject=$s.SignerCertificate.Subject;"
        "thumbprint=$s.SignerCertificate.Thumbprint}|ConvertTo-Json -Compress"
    )
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8", timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            env=dict(os.environ, ONECLICKLOG_NPCAP_VERIFY=str(path)))
    if result.returncode:
        raise ValueError("Npcap Authenticode verification failed: " + result.stderr[-1000:])
    signature = json.loads(result.stdout)
    if signature.get("status") != "Valid" or not re.search(
            r"(?:^|,\s*)CN=Nmap Software LLC(?:,|$)", signature.get("subject") or ""):
        raise ValueError("Npcap installer does not have a valid Nmap Software LLC signature")
    return signature


def bundle_npcap(root, package, cache, logger):
    spec = importlib.util.spec_from_file_location("autolog_npcap_download", root / "packaging/wireshark_bundle.py")
    downloads = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(downloads)
    lock = json.loads((root / "packaging/npcap.lock.json").read_text(encoding="utf-8"))
    if (lock.get("scope") != "internal-single-pc" or
            lock["installer"]["url"] != f"https://npcap.com/dist/npcap-{lock['version']}.exe" or
            lock["installer"]["name"] != f"npcap-{lock['version']}.exe"):
        raise ValueError("Invalid internal Npcap installer configuration")
    cache.mkdir(parents=True, exist_ok=True)
    installer = downloads.download(lock["installer"], cache, logger)
    license_file = downloads.download(lock["license"], cache, logger)
    signature = verify_signature(installer)
    destination = package / "installers/Npcap"
    destination.mkdir(parents=True, exist_ok=False)
    copied = destination / installer.name
    shutil.copy2(installer, copied)
    shutil.copy2(license_file, destination / "LICENSE.txt")
    shutil.copy2(root / "packaging/NPCAP_INSTALLATION.txt", destination / "READ_ME_FIRST.txt")
    if copied.stat().st_size != lock["installer"]["bytes"] or downloads.digest(copied) != lock["installer"]["sha256"]:
        raise ValueError("Npcap installer copy did not match the verified original")
    manifest = {"version": lock["version"], "scope": lock["scope"],
                "installer": lock["installer"], "license": lock["license"], "signature": signature,
                "installation_required_on_target": True, "installer_executed_by_build": False,
                "files": [{"path": str(path.relative_to(package)).replace("\\", "/"),
                           "bytes": path.stat().st_size, "sha256": downloads.digest(path)}
                          for path in sorted(destination.iterdir())]}
    (destination / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    logger.info("Included Npcap %s signed installer for one internal PC; installer NOT executed", lock["version"])
    return {"version": lock["version"], "scope": lock["scope"],
            "path": str(copied.relative_to(package)).replace("\\", "/"),
            "sha256": lock["installer"]["sha256"], "bytes": lock["installer"]["bytes"],
            "installer_executed_by_build": False,
            "manifest_sha256": downloads.digest(destination / "bundle_manifest.json")}
