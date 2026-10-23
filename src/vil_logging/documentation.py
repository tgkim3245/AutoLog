"""One offline illustrated guide shared by source runs and release packaging."""

import base64
import hashlib
import json
import logging
import re
import struct
import sys
import tempfile
from collections import Counter
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from vil_logging import APP_NAME, __version__

log = logging.getLogger(__name__)


class _GuideSource(HTMLParser):
    """Read marked source fragments so a stale/missing translation blocks release."""

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source, self.fragments, self.stack = source, {}, []
        self.lines = [0, *(match.end() for match in re.finditer("\n", source))]

    def source_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def add(self, key, value):
        if key in self.fragments:
            raise ValueError(f"Duplicate guide translation key: {key}")
        self.fragments[key] = value

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name in ("alt", "aria-label"):
            if key := attrs.get("data-guide-" + name):
                self.add(key, attrs[name])
        if tag not in {"img", "meta", "br", "hr", "input", "link"}:
            self.stack.append((tag, attrs.get("data-guide-html"),
                               self.source_offset() + len(self.get_starttag_text()),
                               attrs.get("class") == "languages"))

    def handle_data(self, data):
        if (re.search(r"[가-힣]", data) and self.stack and
                self.stack[-1][0] not in {"script", "style"} and
                not any(key or language_picker for _tag, key, _start, language_picker in self.stack)):
            raise ValueError("Unmarked guide text: add reviewed translations before building.")

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError(f"Unbalanced guide markup: {tag}")
        _tag, key, start, _language_picker = self.stack.pop()
        if key:
            self.add(key, self.source[start:self.source_offset()])


class _TranslationMarkup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.markup = Counter()
        self.stack = []
        self.feed(text)
        if self.stack:
            raise ValueError("Unbalanced guide translation markup")

    def handle_starttag(self, tag, attrs):
        if tag not in {"b", "strong", "code", "br", "a", "span"} or any(
                key not in {"href", "class"} for key, _value in attrs):
            raise ValueError("Unsupported guide translation markup")
        self.markup[(tag, tuple(sorted(attrs)))] += 1
        if tag != "br":
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("Unbalanced guide translation markup")


def _guide_translations(source: Path, template: str) -> str:
    parser = _GuideSource(template)
    parser.feed(template)
    original = json.loads((source / "translations.json").read_text(encoding="utf-8"))
    if parser.fragments != original:
        raise ValueError("Guide source changed: review the guide translations and source fragments.")
    languages = {"ko": original}
    for language in ("en", "zh"):
        entries = json.loads((source / f"translations.{language}.json").read_text(encoding="utf-8"))
        if not isinstance(entries, dict) or entries.keys() != original.keys():
            raise ValueError(f"Incomplete guide translations: {language}")
        for key, text in entries.items():
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"Empty guide translation: {language}/{key}")
            if (set(re.findall(r"\{\{.*?\}\}", text)) !=
                    set(re.findall(r"\{\{.*?\}\}", original[key])) or
                    _TranslationMarkup(text).markup != _TranslationMarkup(original[key]).markup):
                raise ValueError(f"Guide translation changed links/markup/placeholders: {language}/{key}")
        languages[language] = entries
    # Keep translated HTML inert inside a JSON script, including literal </script>.
    return json.dumps(languages, ensure_ascii=False).replace("<", "\\u003c")


def _guide_annotations(source: Path, photos: list[str], app_version: str) -> str:
    manifest = json.loads((source / "images/manifest.json").read_text(encoding="utf-8"))
    if manifest.get("annotations_version") != 1 or manifest.get("app_version") != app_version:
        raise ValueError("Recapture reviewed guide annotations for this app version.")
    expected = {name + ("" if language == "ko" else "-" + language) + ".png"
                for name in photos for language in ("ko", "en", "zh")}
    records = manifest.get("screenshots", [])
    if ({row.get("file") for row in records} != expected or len(records) != len(expected)):
        raise ValueError("Missing or duplicate annotated guide screenshots.")
    result = {language: {} for language in ("ko", "en", "zh")}
    for row in records:
        language, filename = row.get("language"), row["file"]
        path = source / "images" / filename
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f"Guide screenshot is too large: {filename}")
        data = path.read_bytes()
        width, height = row["width"], row["height"]
        if (language not in result or hashlib.sha256(data).hexdigest() != row["sha256"] or
                len(data) < 24 or struct.unpack(">II", data[16:24]) != (width, height)):
            raise ValueError(f"Guide annotation does not match screenshot: {filename}")
        steps = row.get("annotations", [])
        if not steps or len(steps) > 5:
            raise ValueError(f"Missing guide click instructions: {filename}")
        for number, step in enumerate(steps, 1):
            rect = step.get("rect", [])
            if (step.get("step") != number or step.get("action") not in {"click", "type", "select", "check", "enter"}
                    or not isinstance(step.get("label"), str) or not 0 < len(step["label"].strip()) <= 80
                    or len(rect) != 4 or any(type(value) is not int for value in rect)):
                raise ValueError(f"Invalid guide click instruction: {filename}")
            x, y, w, h = rect
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
                raise ValueError(f"Guide click target outside screenshot: {filename}")
        suffix = ".png" if language == "ko" else "-" + language + ".png"
        if not filename.endswith(suffix):
            raise ValueError(f"Guide screenshot language mismatch: {filename}")
        result[language][filename[:-len(suffix)]] = {"width": width, "height": height, "steps": steps}
    return json.dumps(result, ensure_ascii=False).replace("<", "\\u003c")


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
        if filename == guide_name:
            text = text.replace("{{GUIDE_TRANSLATIONS}}", _guide_translations(source, text))
            photos = re.findall(r'data-guide-image="([a-z_-]+)"', text)
            text = text.replace("{{GUIDE_ANNOTATIONS}}", _guide_annotations(source, photos, app_version))
            localized_images = {language: {name: "{{IMAGE:" + name + "-" + language + ".png}}"
                                          for name in photos} for language in ("en", "zh")}
            text = text.replace("{{GUIDE_IMAGES}}", json.dumps(localized_images))
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


def open_user_guide(language: str = "ko") -> None:
    from PySide6.QtCore import QUrl, QUrlQuery
    from PySide6.QtGui import QDesktopServices

    path = user_guide_path()
    language = language if language in {"ko", "en", "zh"} else "ko"
    url = QUrl.fromLocalFile(str(path))
    query = QUrlQuery()
    query.addQueryItem("lang", language)
    url.setQuery(query)
    if not QDesktopServices.openUrl(url):
        raise OSError("The default browser could not open the user guide")
    log.info("user_guide.opened", extra={"path": str(path), "version": __version__, "language": language})
