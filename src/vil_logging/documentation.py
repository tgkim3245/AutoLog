"""One offline illustrated guide shared by source runs and release packaging."""

import base64
import json
import logging
import re
import struct
import sys
import tempfile
from datetime import date
from pathlib import Path

from vil_logging import APP_NAME, __version__

log = logging.getLogger(__name__)


def load_user_documentation(root: Path, app_name: str, app_version: str) -> tuple[dict, dict[str, str]]:
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

    def embed_image(match):
        path = source / "images" / match[1]
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f"Guide screenshot is too large: {path.name}")
        data = path.read_bytes()
        if (len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR" or
                not all(0 < size <= 8192 for size in struct.unpack(">II", data[16:24]))):
            raise ValueError(f"Invalid guide screenshot: {path.name}")
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii")

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
        text = re.sub(r"\{\{IMAGE:([a-z0-9_-]+\.png)\}\}", embed_image, text)
        if re.search(r"\{\{.*?\}\}", text, flags=re.S):
            raise ValueError(f"Unresolved user guide placeholder in {template}.")
        documents[filename] = text
    return metadata, documents


def user_guide_path() -> Path:
    """Frozen builds use the EXE's guide, independent of the current directory."""
    name = f"{APP_NAME}_User_Guide.html"
    if getattr(sys, "frozen", False):
        path = Path(sys.executable).resolve().parent / name
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    root = Path(__file__).resolve().parents[2]
    _metadata, documents = load_user_documentation(root, APP_NAME, __version__)
    cache = Path(tempfile.gettempdir()) / "OneClickLog-Guide" / __version__
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / name
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache, delete=False) as stream:
            pending = Path(stream.name)
            stream.write(documents[name])
        pending.replace(path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return path


def open_user_guide() -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    path = user_guide_path()
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        raise OSError("The default browser could not open the user guide")
    log.info("user_guide.opened", extra={"path": str(path), "version": __version__})
