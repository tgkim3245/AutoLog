"""Build an offline, version-pinned Wireshark CLI distribution from official MSI."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

SYSTEM_DLLS = frozenset(name.casefold() for name in (
    "ADVAPI32.dll", "CRYPT32.dll", "DNSAPI.dll", "GDI32.dll", "IPHLPAPI.dll", "KERNEL32.dll",
    "PSAPI.dll", "SHELL32.dll", "SECUR32.dll", "USER32.dll", "WS2_32.dll", "BCRYPT.dll",
    "NCRYPT.dll", "OLE32.dll", "MSVCRT.dll",
))
DATA_DIRECTORIES = ("diameter", "dtds", "generic", "profiles", "protobuf", "radius", "snmp",
                    "tpncp", "wimaxasncp")
TOOLS = ("tshark.exe", "dumpcap.exe", "capinfos.exe")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download(item, cache, logger):
    """Reuse verified cache entries; never execute or accept a partial download."""
    path = cache / item["name"]
    if Path(item["name"]).name != item["name"] or not item["url"].startswith("https://"):
        raise ValueError("Invalid third-party download entry")
    if path.is_file():
        if path.stat().st_size == item["bytes"] and digest(path) == item["sha256"]:
            return path
        raise ValueError(f"Cached third-party file has changed; remove this cache file and rebuild: {path}")
    logger.info("Downloading %s (%s bytes)", item["name"], item["bytes"])
    temporary = path.with_name(path.name + "." + uuid4().hex + ".part")
    deadline, received = time.monotonic() + 300, 0
    try:
        with urllib.request.urlopen(item["url"], timeout=30) as response, temporary.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > item["bytes"] or time.monotonic() > deadline:
                    raise ValueError("Third-party download exceeded its size/time limit")
                output.write(chunk)
        if received != item["bytes"] or digest(temporary) != item["sha256"]:
            raise ValueError(f"Third-party SHA256 or size mismatch: {item['name']}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)  # Only this download's randomly named incomplete file.
    return path


def runtime_files(root, system):
    """Follow normal/delayed PE imports, including stock plugins and VC runtime."""
    import pefile

    queue = [root / name for name in TOOLS] + list((root / "plugins").rglob("*.dll"))
    selected = {}
    while queue:
        path = queue.pop()
        relative = path.relative_to(root) if path.is_relative_to(root) else Path(path.name)
        key = str(relative).casefold()
        if key in selected:
            continue
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"Required capture dependency is missing: {path}")
        selected[key] = (path, relative)
        with pefile.PE(str(path), fast_load=True) as pe:
            if pe.FILE_HEADER.Machine != 0x8664:
                raise ValueError(f"Capture dependency is not Windows x64: {path}")
            pe.parse_data_directories(directories=[1, 13])
            for entry in [*getattr(pe, "DIRECTORY_ENTRY_IMPORT", []),
                          *getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])]:
                name = entry.dll.decode("ascii")
                if Path(name).name != name:
                    raise ValueError("Invalid PE dependency path")
                if name.casefold() in SYSTEM_DLLS or name.casefold().startswith("api-ms-win-"):
                    continue
                dependency = root / name
                queue.append(dependency if dependency.is_file() else system / name)
    return list(selected.values())


def copy_licenses(archive, destination):
    """Read license texts directly; source archives are also supplied unmodified."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        for member in source:
            path = Path(member.name)
            if (not member.isfile() or member.size > 250_000 or len(path.parts) > 3
                    or not re.match(r"^(COPYING|COPYRIGHT|LICEN[CS]E|AUTHORS)(?:[._-].*)?$", path.name, re.I)):
                continue
            # Flatten archive paths. Never extract links or arbitrary member names.
            name = path.name
            if Path(name).name != name:
                raise ValueError("Invalid source license name")
            data = source.extractfile(member).read()
            if (destination / name).exists() and (destination / name).read_bytes() != data:
                name = hashlib.sha256(member.name.encode()).hexdigest()[:8] + "_" + name
            (destination / name).write_bytes(data)


def verify_tools(directory, version):
    environment = dict(os.environ)
    environment["PATH"] = os.pathsep.join((str(Path(os.environ["SystemRoot"]) / "System32"),
                                          os.environ["SystemRoot"]))
    for key in tuple(environment):
        if key.startswith(("WIRESHARK_", "PYTHON")) or key in {"QT_PLUGIN_PATH", "VIRTUAL_ENV"}:
            environment.pop(key)
    versions = {}
    for name in TOOLS:
        result = subprocess.run([str(directory / name), "--version"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                env=environment, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        line = result.stdout.splitlines()[0] if result.stdout else ""
        if result.returncode or not re.search(r"\b" + re.escape(version) + r"\b", line):
            raise RuntimeError(f"Bundled {name} did not run correctly: {line} {result.stderr[-1000:]}")
        versions[name] = line
    return versions


def bundle_wireshark(root, package, cache, work, logger):
    lock = json.loads((root / "packaging/wireshark.lock.json").read_text(encoding="utf-8"))
    cache = cache / ("wireshark-" + lock["version"])
    cache.mkdir(parents=True, exist_ok=True)
    installer = download(lock["installer"], cache, logger)
    sources = [(item, download(item, cache, logger)) for item in lock["sources"]]
    image = Path(tempfile.mkdtemp(prefix="wireshark-image-", dir=work))
    logger.info("Extracting verified Wireshark MSI (no product/driver installation)")
    result = subprocess.run(["msiexec.exe", "/a", str(installer), "/qn", f"TARGETDIR={image}",
                             "/L*v", str(image.parent / "wireshark-extract.log")],
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=120)
    if result.returncode:
        raise RuntimeError(f"Wireshark administrative extraction failed ({result.returncode})")
    original = image / "Wireshark"
    destination = package / "tools/Wireshark"
    destination.mkdir(parents=True, exist_ok=False)
    for source, relative in runtime_files(original, image / "System64"):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for directory in DATA_DIRECTORIES:
        if (original / directory).is_dir():
            shutil.copytree(original / directory, destination / directory)
    for source in original.iterdir():
        if source.is_file() and source.suffix.lower() not in {".exe", ".dll", ".msi", ".sys"}:
            shutil.copy2(source, destination / source.name)
    # Npcap/USBPcap are independent drivers and must never enter this bundle.
    if any(path.suffix.lower() == ".sys" or path.name.lower().startswith(("npcap", "usbpcap"))
           or path.name.lower() in {"wpcap.dll", "packet.dll", "wireshark.exe"}
           for path in destination.rglob("*") if path.is_file()):
        raise ValueError("A GUI or separately licensed capture driver entered the CLI bundle")
    version_checks = verify_tools(destination, lock["version"])
    source_dir = package / "third_party_sources/Wireshark"
    source_dir.mkdir(parents=True, exist_ok=False)
    for item, source in sources:
        shutil.copy2(source, source_dir / item["name"])
        label = ("vendor-build-recipes" if item["name"].startswith("wireshark-vcpkg-scripts-")
                 else item["name"].split(".tar")[0])
        copy_licenses(source, package / "licenses/Wireshark" / label)
    shutil.copy2(root / "packaging/WIRESHARK_BUNDLE_NOTICE.txt", destination / "ONE_CLICK_LOG_BUNDLE_NOTICE.txt")
    manifest = {"version": lock["version"], "installer": lock["installer"], "sources": lock["sources"],
                "drivers_included": False, "version_checks": version_checks,
                "files": [{"path": str(path.relative_to(package)).replace("\\", "/"),
                           "bytes": path.stat().st_size, "sha256": digest(path)}
                          for path in sorted(destination.rglob("*")) if path.is_file()]}
    (destination / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    logger.info("Bundled Wireshark %s: %s runtime/resource files; %s source archives; no drivers",
                lock["version"], len(manifest["files"]), len(sources))
    return {"version": lock["version"], "directory": "tools/Wireshark", "drivers_included": False,
            "manifest_sha256": digest(destination / "bundle_manifest.json"),
            "runtime_bytes": sum(item["bytes"] for item in manifest["files"]),
            "source_bytes": sum(item["bytes"] for item in lock["sources"])}
