import hashlib
import importlib.util
import json
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
            self.assets.append(attrs)


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
    assert not guide.assets  # No online script, stylesheet or image is needed to read it.


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


def test_release_zip_contains_guides_with_matching_hashes(project, tmp_path, monkeypatch):
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
    monkeypatch.setattr(release, "git_state", lambda _root: {"commit": "fixture", "dirty": False})
    output = release.build(project, "AutoLog", APP_VERSION, {}, tmp_path / "releases")
    info = json.loads((output / "build_info.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(output / info["archive"]) as archive:
        assert archive.testzip() is None
        embedded = json.loads(archive.read("AutoLog/build_info.json"))
        assert embedded["documentation"] == info["documentation"]
        files = info["documentation"]["files"]
        assert {item["name"] for item in files} == {"START_HERE.txt", "AutoLog_User_Guide.html"}
        for item in files:
            packaged = archive.read("AutoLog/" + item["name"])
            assert packaged == (output / "AutoLog" / item["name"]).read_bytes()
            assert len(packaged) == item["bytes"]
            assert hashlib.sha256(packaged).hexdigest() == item["sha256"]
