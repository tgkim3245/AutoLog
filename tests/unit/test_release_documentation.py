import base64
import hashlib
import importlib.util
import json
import re
import shutil
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

from vil_logging import __version__ as APP_VERSION

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("autolog_release_docs", ROOT / "packaging/build_release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "source"
    shutil.copytree(ROOT / "user_guide", root / "user_guide")
    (root / "tools").mkdir()
    shutil.copyfile(ROOT / "tools/Initial_Setup.bat", root / "tools/Initial_Setup.bat")
    return root


class GuideLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.assets = set(), [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids
            self.ids.add(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag in {"script", "img", "link", "iframe"}:
            self.assets.append((tag, attrs))


def test_offline_guide_renders_reviewed_version_and_has_working_internal_links(project):
    metadata, documents = release.load_user_documentation(project, "AutoLog", APP_VERSION)
    assert set(documents) == {"AutoLog_User_Guide.html", "START_HERE.txt"}
    for text in documents.values():
        assert "{{" not in text
        assert metadata["revision"] in text and APP_VERSION in text
        assert "CAPLcompExec.exe" in text and "CANoe64.exe" in text
    guide = GuideLinks()
    guide.feed(documents["AutoLog_User_Guide.html"])
    assert {link[1:] for link in guide.links if link.startswith("#")} <= guide.ids
    assert "defender" in guide.ids
    pictures = [attrs for tag, attrs in guide.assets if tag == "img" and "src" in attrs]
    assert len(pictures) >= 8
    for image in pictures:
        assert image["src"].startswith("data:image/png;base64,")
        assert base64.b64decode(image["src"].split(",", 1)[1], validate=True).startswith(b"\x89PNG\r\n\x1a\n")
        assert image.get("alt")
    # Photos, styles and interactions are embedded, with no online dependencies.
    assert all(tag in {"img", "script"} and (tag != "script" or "src" not in attrs)
               for tag, attrs in guide.assets)
    html = documents["AutoLog_User_Guide.html"]
    catalogs = json.loads(re.search(r'id="guide-translations">(.*?)</script>', html, re.S)[1])
    assert set(catalogs) == {"ko", "en", "zh"}
    assert all(entries.keys() == catalogs["ko"].keys() and all(entries.values())
               for entries in catalogs.values())
    assert catalogs["en"]["g002"] == "Your first recording"
    assert catalogs["zh"]["g002"] == "开始第一次记录"
    photos = json.loads(re.search(r'id="guide-images">(.*?)</script>', html, re.S)[1])
    assert set(photos) == {"en", "zh"} and all(len(items) == 14 for items in photos.values())
    for images in photos.values():
        for uri in images.values():
            assert uri.startswith("data:image/png;base64,")
            assert base64.b64decode(uri.split(",", 1)[1], validate=True).startswith(b"\x89PNG\r\n\x1a\n")
    annotations = json.loads(re.search(r'id="guide-annotations">(.*?)</script>', html, re.S)[1])
    assert set(annotations) == {"ko", "en", "zh"}
    for language, pictures in annotations.items():
        assert len(pictures) == 14
        assert [step["action"] for step in pictures["storage"]["steps"]] == ["click", "type", "click"]
        assert pictures["recording"]["steps"][0]["action"] == "click"
        assert pictures["bug-report"]["steps"][0]["action"] == "check"
        assert pictures["report-entry"]["steps"][0]["action"] == "click"
        assert all(photo["steps"] for photo in pictures.values())


@pytest.mark.parametrize("damage", ["missing", "invalid", "too_large"])
def test_missing_or_invalid_screenshot_blocks_build_before_reserving_output(project, tmp_path, damage):
    image = project / "user_guide/images/storage.png"
    if damage == "missing":
        image.unlink()
    else:
        image.write_bytes(b"not a PNG" if damage == "invalid" else b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises((FileNotFoundError, ValueError)):
        release.build(project, "AutoLog", APP_VERSION, {}, tmp_path / "releases")
    assert not (tmp_path / "releases").exists()


def test_stale_guide_blocks_build_before_creating_a_release(project, tmp_path):
    with pytest.raises(ValueError, match="Review the user guide"):
        release.build(project, "AutoLog", "unreviewed-version", {}, tmp_path / "releases")
    assert not (tmp_path / "releases").exists()


@pytest.mark.parametrize("change", [{"revision": "2026-10-19.1"}, {"updated": "2026-02-30"},
                                   {"revision": "2026-10-20.0"}, {"language": "unknown"},
                                   {"reviewed_app_version": 92}])
def test_invalid_guide_metadata_is_rejected(project, change):
    path = project / "user_guide/guide_metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**metadata, **change}), encoding="utf-8")
    with pytest.raises(ValueError):
        release.load_user_documentation(project, "AutoLog", APP_VERSION)


def test_missing_or_unresolved_notice_blocks_documentation(project):
    template = project / "user_guide/distribution_notice.template.txt"
    template.write_text(template.read_text(encoding="utf-8") + "\n{{UNKNOWN}}", encoding="utf-8")
    with pytest.raises(ValueError, match="Unresolved"):
        release.load_user_documentation(project, "AutoLog", APP_VERSION)
    template.unlink()
    with pytest.raises(FileNotFoundError):
        release.load_user_documentation(project, "AutoLog", APP_VERSION)


@pytest.mark.parametrize("internal", [False, True])
def test_release_zip_contains_guides_with_matching_hashes(project, tmp_path, monkeypatch, internal):
    class Packager:
        def __init__(self, command, **_kwargs):
            output = Path(command[command.index("--distpath") + 1]) / "AutoLog"
            (output / "_internal").mkdir(parents=True)
            (output / "AutoLog.exe").write_bytes(b"packager fixture; not an executable")
            self.stdout = iter([])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def wait(self):
            return 0

    monkeypatch.setattr(release.subprocess, "Popen", Packager)
    monkeypatch.setattr(release, "bundle_capture_tools", lambda *_args: {
        "version": "fixture", "directory": "tools/Wireshark", "drivers_included": False})
    monkeypatch.setattr(release, "git_state", lambda _root: {"commit": "fixture", "dirty": False})
    calls = []

    def installer(_root, package, _cache, _logger):
        calls.append(package)
        folder = package / "installers/Npcap"
        folder.mkdir(parents=True)
        (folder / "npcap-fixture.exe").write_bytes(b"installer fixture, never executed")
        return {"scope": "internal-single-pc", "path": "installers/Npcap/npcap-fixture.exe"}

    monkeypatch.setattr(release, "bundle_npcap_installer", installer)
    output = release.build(project, "AutoLog", APP_VERSION, {}, tmp_path / "releases",
                           include_npcap_internal=internal)
    info = json.loads((output / "build_info.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(output / info["archive"]) as archive:
        assert archive.testzip() is None
        embedded = json.loads(archive.read("AutoLog/build_info.json"))
        assert archive.read("AutoLog/Initial_Setup.bat") == (ROOT / "tools/Initial_Setup.bat").read_bytes()
        assert embedded["initial_setup"] == info["initial_setup"]
        assert hashlib.sha256(archive.read("AutoLog/Initial_Setup.bat")).hexdigest() == info["initial_setup"]["sha256"]
        assert embedded["documentation"] == info["documentation"]
        assert embedded["capture_tools"] == info["capture_tools"]
        assert embedded["npcap_installer"] == info["npcap_installer"]
        assert info["distribution_scope"] == ("internal-single-pc" if internal else "standard")
        assert bool(calls) == internal
        assert ("-internal_" in output.name) == internal
        assert ("AutoLog/installers/Npcap/npcap-fixture.exe" in archive.namelist()) == internal
        files = info["documentation"]["files"]
        assert {item["name"] for item in files} == {"START_HERE.txt", "AutoLog_User_Guide.html"}
        for item in files:
            packaged = archive.read("AutoLog/" + item["name"])
            assert packaged == (output / "AutoLog" / item["name"]).read_bytes()
            assert len(packaged) == item["bytes"]
            assert hashlib.sha256(packaged).hexdigest() == item["sha256"]


@pytest.mark.parametrize("damage", ["missing", "empty", "extra", "link", "markup", "placeholder", "source", "unmarked", "photo"])
def test_translation_damage_blocks_release_before_output_is_created(project, tmp_path, damage):
    folder = project / "user_guide"
    path = folder / "translations.en.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if damage == "missing":
        del catalog["g002"]
    elif damage == "empty":
        catalog["g002"] = " "
    elif damage == "extra":
        catalog["unexpected"] = "Extra"
    elif damage == "link":
        catalog["g018"] = catalog["g018"].replace("#defender", "https://example.invalid")
    elif damage == "markup":
        catalog["g002"] += "<script>alert(1)</script>"
    elif damage == "placeholder":
        catalog["g001"] = catalog["g001"].replace("{{APP_VERSION}}", "old-version")
    elif damage in {"source", "unmarked"}:
        template = folder / "AutoLog_User_Guide.template.html"
        text = template.read_text(encoding="utf-8")
        text = text.replace("처음 기록하기", "바뀐 사용법") if damage == "source" else text.replace("</header>", "<p>번역이 빠진 새 설명</p></header>")
        template.write_text(text, encoding="utf-8")
    elif damage == "photo":
        (folder / "images/storage-en.png").unlink()
    path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        release.build(project, "AutoLog", APP_VERSION, {}, tmp_path / "releases")
    assert not (tmp_path / "releases").exists()


@pytest.mark.parametrize("damage", ["missing", "outside", "step_order", "hash", "language"])
def test_inaccurate_screenshot_annotations_block_release(project, tmp_path, damage):
    path = project / "user_guide/images/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    image = next(row for row in manifest["screenshots"] if row["file"] == "storage.png")
    if damage == "missing":
        image.pop("annotations")
    elif damage == "outside":
        image["annotations"][0]["rect"] = [image["width"] + 10, 1, 20, 20]
    elif damage == "step_order":
        image["annotations"][0]["step"] = 99
    elif damage == "hash":
        image["sha256"] = "0" * 64
    else:
        image["language"] = "zh"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        release.build(project, "AutoLog", APP_VERSION, {}, tmp_path / "releases")
    assert not (tmp_path / "releases").exists()
