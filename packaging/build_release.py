"""Build a versioned One Click Log folder and ZIP from any working directory."""

import argparse
import ast
import hashlib
import importlib.util
import json
import logging
import os
import re
import struct
import subprocess
import sys
import tomllib
import zipfile
from datetime import date, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def read_app_metadata(root: Path) -> tuple[str, str]:
    tree = ast.parse((root / "src/vil_logging/__init__.py").read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    app_name = values.get("APP_NAME")
    app_version = values.get("__version__")
    if not isinstance(app_name, str) or app_name != app_name.strip() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,79}", app_name):
        raise ValueError("APP_NAME must be a safe folder name.")
    if not isinstance(app_version, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+(?:[A-Za-z0-9.-]+)?", app_version
    ):
        raise ValueError("__version__ must start with major.minor.patch.")
    parts = tuple(map(int, re.match(r"(\d+)\.(\d+)\.(\d+)", app_version).groups()))
    if any(part > 65535 for part in parts):
        raise ValueError("Windows version numbers must be between 0 and 65535.")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if project["tool"]["setuptools"]["dynamic"]["version"]["attr"] != (
        "vil_logging.__version__"
    ):
        raise ValueError("pyproject.toml must read its version from vil_logging.__version__.")
    return app_name, app_version


def windows_version_info(app_name: str, app_version: str):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = tuple(map(int, re.match(r"(\d+)\.(\d+)\.(\d+)", app_version).groups()))
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=(*numbers, 0), prodvers=(*numbers, 0), mask=0x3F, flags=0,
            OS=0x40004, fileType=1, subtype=0, date=(0, 0),
        ),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("FileDescription", f"{app_name} capture control panel"),
                StringStruct("FileVersion", app_version),
                StringStruct("InternalName", app_name),
                StringStruct("OriginalFilename", f"{app_name}.exe"),
                StringStruct("ProductName", app_name),
                StringStruct("ProductVersion", app_version),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )


def check_environment() -> dict[str, str]:
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("Build on 64-bit Windows with 64-bit Python.")
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError("This project requires Python 3.14.")
    packages = {}
    for name in ("PyInstaller", "PySide6", "pywin32", "python-can", "wrapt"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError as error:
            raise RuntimeError("Install requirements.lock in the development environment.") from error
    return packages


def git_state(root: Path) -> dict:
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": None, "dirty": None}
    return {
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(status.stdout) if status.returncode == 0 else None,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_user_documentation(root: Path, app_name: str, app_version: str) -> tuple[dict, dict[str, str]]:
    """Require reviewed documentation before reserving/building a release."""
    source = root / "user_guide"
    metadata = json.loads((source / "guide_metadata.json").read_text(encoding="utf-8"))
    required = {"reviewed_app_version", "revision", "updated", "language"}
    if not isinstance(metadata, dict) or set(metadata) != required or any(
            not isinstance(value, str) for value in metadata.values()):
        raise ValueError("Invalid user guide metadata.")
    if metadata["reviewed_app_version"] != app_version:
        raise ValueError(f"Review the user guide for {app_name} {app_version} and update guide_metadata.json.")
    updated = date.fromisoformat(metadata["updated"])
    if (metadata["language"] != "ko" or updated.isoformat() != metadata["updated"] or
            not re.fullmatch(re.escape(metadata["updated"]) + r"\.[1-9][0-9]*", metadata["revision"])):
        raise ValueError("Invalid user guide revision/date/language.")
    guide_name = f"{app_name}_User_Guide.html"
    variables = {"APP_NAME": app_name, "APP_VERSION": app_version,
                 "GUIDE_REVISION": metadata["revision"], "UPDATED_DATE": metadata["updated"],
                 "GUIDE_FILENAME": guide_name}
    documents = {}
    for template, filename in (("AutoLog_User_Guide.template.html", guide_name),
                               ("distribution_notice.template.txt", "START_HERE.txt")):
        text = (source / template).read_text(encoding="utf-8")
        for key in ("APP_VERSION", "GUIDE_REVISION", "UPDATED_DATE"):
            if "{{" + key + "}}" not in text:
                raise ValueError(f"The user guide template {template} must include {key}.")
        for key, value in variables.items():
            text = text.replace("{{" + key + "}}", value)
        if re.search(r"\{\{.*?\}\}", text, flags=re.S):
            raise ValueError(f"Unresolved user guide placeholder in {template}.")
        documents[filename] = text
    return metadata, documents


def write_user_documentation(package: Path, metadata: dict, documents: dict[str, str]) -> dict:
    files = []
    for filename, text in documents.items():
        path = package / filename
        path.write_text(text, encoding="utf-8")
        files.append({"name": filename, "bytes": path.stat().st_size, "sha256": sha256(path)})
    return {**metadata, "files": files}


def bundle_capture_tools(root, package, cache, work, logger):
    spec = importlib.util.spec_from_file_location("autolog_wireshark_bundle", root / "packaging/wireshark_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bundle_wireshark(root, package, cache, work, logger)


def new_output_directory(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for suffix in range(1000):
        output = root / (name if suffix == 0 else f"{name}_{suffix:02d}")
        try:
            output.mkdir()
            return output
        except FileExistsError:
            continue
    raise RuntimeError("Unable to reserve a new build folder.")


def build(
    root: Path, app_name: str, app_version: str, packages: dict,
    output_root: Path | None = None,
) -> Path:
    guide_metadata, documents = load_user_documentation(root, app_name, app_version)
    built_at = datetime.now().astimezone()
    build_id = f"{app_name}-{app_version}_{built_at:%Y%m%d_%H%M%S}"
    location_note = None
    if output_root is not None:
        output = new_output_directory(output_root.expanduser().resolve(), build_id)
    elif root.is_relative_to(Path.home() / "Documents"):
        location_note = "Source is in Documents; building in Downloads/OneClickLog_Builds."
        output = new_output_directory(Path.home() / "Downloads/OneClickLog_Builds", build_id)
    else:
        try:
            output = new_output_directory(root / "outputs", build_id)
        except OSError as error:
            if getattr(error, "winerror", None) not in (2, 3, 5) or not (root / "outputs").is_dir():
                raise
            location_note = (
                "Project outputs could not be written. Using Downloads/OneClickLog_Builds "
                "without changing Windows security settings. "
                f"Original error: {error}"
            )
            output = new_output_directory(Path.home() / "Downloads/OneClickLog_Builds", build_id)
    logger = logging.getLogger("autolog.build")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handlers = [logging.FileHandler(output / "build.log", encoding="utf-8"),
                logging.StreamHandler(sys.stdout)]
    for handler in handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
    info = {
        "app_name": app_name,
        "version": app_version,
        "build_id": output.name,
        "built_at": built_at.isoformat(),
        "status": "building",
        "python": sys.version.split()[0],
        "packages": packages,
        "git": git_state(root),
    }
    try:
        write_json(output / "build_info.json", info)
        work = output.parent / "build" / output.name
        work.mkdir(parents=True, exist_ok=False)
        command = [
            sys.executable, "-m", "PyInstaller", "--noconfirm",
            "--workpath", str(work), "--distpath", str(output),
            str(root / "packaging/app.spec"),
        ]
        environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        logger.info("Building %s %s", app_name, app_version)
        if location_note:
            logger.info("%s", location_note)
        logger.info("Output: %s", output)
        with subprocess.Popen(
            command, cwd=root, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        ) as process:
            for line in process.stdout:
                logger.info("%s", line.rstrip())
            if process.wait() != 0:
                raise RuntimeError("PyInstaller failed. See build.log in the output folder.")
        package = output / app_name
        executable = package / f"{app_name}.exe"
        if not executable.is_file() or not (package / "_internal").is_dir():
            raise RuntimeError("The build did not produce the expected EXE and _internal folder.")
        documentation = write_user_documentation(package, guide_metadata, documents)
        capture_tools = bundle_capture_tools(root, package, output.parent / "tool-cache", work, logger)
        package_info = dict(info, status="succeeded", exe_sha256=sha256(executable),
                            documentation=documentation, capture_tools=capture_tools)
        write_json(package / "build_info.json", package_info)
        archive = output / f"{output.name}.zip"
        logger.info("Creating %s", archive.name)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
            for path in sorted(package.rglob("*")):
                if path.is_file():
                    compression = zipfile.ZIP_STORED if path.is_relative_to(package / "third_party_sources") else zipfile.ZIP_DEFLATED
                    zip_file.write(path, path.relative_to(output), compress_type=compression)
        info.update(package_info, archive=archive.name, archive_sha256=sha256(archive))
        (output / f"{archive.name}.sha256.txt").write_text(
            f"{info['archive_sha256']}  {archive.name}\n", encoding="utf-8"
        )
        write_json(output / "build_info.json", info)
        logger.info("BUILD SUCCEEDED")
        logger.info("EXE: %s", executable)
        logger.info("ZIP: %s", archive)
        logger.info("Version/Git/hash: %s", output / "build_info.json")
        return output
    except BaseException as error:
        info.update(status="failed", error=str(error))
        write_json(output / "build_info.json", info)
        logger.exception("BUILD FAILED. Log: %s", output / "build.log")
        raise
    finally:
        for handler in handlers:
            handler.close()
            logger.removeHandler(handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a versioned One Click Log EXE folder and ZIP.")
    parser.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--check", action="store_true", help="Check version and tools without building.")
    parser.add_argument("--output-root", type=Path, help="Choose the parent folder for build results.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        app_name, app_version = read_app_metadata(root)
        packages = check_environment()
        if args.check:
            guide_metadata, _documents = load_user_documentation(root, app_name, app_version)
            print(json.dumps({"app_name": app_name, "version": app_version, "packages": packages,
                              "python": sys.executable, "documentation": guide_metadata}, indent=2))
            return 0
        build(root, app_name, app_version, packages, args.output_root)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f"Build error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
