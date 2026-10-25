"""Real Windows file locks and generated captures; no vehicle or network access."""

import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtTest import QSignalSpy

from vil_logging.contracts.models import AppSettings, Role, SessionPhase
from vil_logging.storage.capture_files import (
    cleanup_zip_source,
    prepare_capture_zip,
    publish_capture,
)
from vil_logging.storage.discard import discard_interrupted
from vil_logging.storage.file_access import observe
from vil_logging.storage.file_service import FileService
from vil_logging.storage.naming import NamingError, build_plan, find_collisions
from vil_logging.storage.recovery import RecoveryService
from vil_logging.storage.repository import Repository, RepositoryError
from vil_logging.ui.settings_dialog import SettingsDialog


@pytest.fixture
def recording(tmp_path):
    output = tmp_path / "captures"
    output.mkdir()
    repo = Repository(tmp_path / "state.sqlite3")
    settings = repo.load_settings(str(output))
    settings = repo.save_preferences({"ethernet_compression": "zip"})
    plan = build_plan(settings, (Role.ETHERNET,))
    repo.reserve(plan)
    file = plan.files[0]
    file.temp_path.parent.mkdir(parents=True)
    file.temp_path.write_bytes(b"generated capture fixture\0" * 120_000)
    inspection = {**observe(file.temp_path), "packet_count": 42, "actual_format": "pcap"}
    yield repo, plan, file, inspection
    repo.close()


def test_zip_stream_roundtrip_commits_archive_before_removing_raw(recording):
    repo, plan, file, inspection = recording
    raw = file.temp_path.read_bytes()
    persisted = []

    def journal(prepared):
        assert file.temp_path.exists() and not file.final_path.exists()
        persisted.append(dict(prepared))
        repo.update_capture_file(plan.session_id, file.role, "publishing", inspection=prepared)

    assert publish_capture(file, inspection, journal) == file.final_path
    assert persisted[0]["bytes"] < len(raw)
    assert inspection["zip_archive"]["source_bytes"] == len(raw)
    assert inspection["packet_count"] == 42
    with zipfile.ZipFile(file.final_path) as archive:
        assert archive.namelist() == [file.temp_path.name]
        assert archive.read(file.temp_path.name) == raw
        assert archive.testzip() is None
    assert file.temp_path.exists()  # DB publication not committed yet.
    repo.update_capture_file(
        plan.session_id,
        file.role,
        "published",
        actual_path=str(file.final_path),
        inspection=inspection,
    )
    repo.update_session(plan.session_id, SessionPhase.COMPLETED)
    cleanup_zip_source(file, inspection)
    assert not file.temp_path.exists()
    service = FileService(repo)
    assert service.history()[0]["can_rename"]
    assert service.rename_previous(plan.session_id, "renamed")["status"] == "completed"
    assert Path(service.history()[0]["files"][0]["path"]).name == "renamed.pcap.zip"
    assert service.delete_selected(service.history()[0]["files"])["status"] == "completed"


@pytest.mark.parametrize("format", ["pcap", "pcapng"])
def test_names_and_raw_default(format, tmp_path):
    setting = AppSettings(output_dir=str(tmp_path), ethernet_format=format)
    plain = build_plan(setting, (Role.ETHERNET, Role.CAN))
    zipped = build_plan(replace(setting, ethernet_compression="zip"), (Role.ETHERNET, Role.CAN))
    assert plain.files[0].filename.endswith("." + format)
    assert zipped.files[0].filename.endswith("." + format + ".zip")
    assert zipped.files[0].temp_path.name == plain.files[0].temp_path.name
    assert zipped.files[1].filename == plain.files[1].filename
    zipped.files[0].final_path.touch()
    assert find_collisions(zipped) == [zipped.files[0].final_path]
    with pytest.raises(NamingError):
        build_plan(replace(setting, ethernet_compression="gzip"), (Role.ETHERNET,))


@pytest.mark.parametrize(
    "fault", ["collision", "write", "crc", "journal", "changed", "staging_exists"]
)
def test_zip_failures_preserve_raw_and_foreign_outputs(recording, monkeypatch, fault):
    repo, plan, file, inspection = recording
    raw = file.temp_path.read_bytes()
    if fault == "collision":
        file.final_path.write_bytes(b"foreign")
    if fault == "write":

        def disk_full(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(zipfile.ZipFile, "open", disk_full)
    if fault == "crc":
        original = zipfile.ZipFile.open

        def corrupt(self, *args, **kwargs):
            if self.mode == "r":
                raise zipfile.BadZipFile("CRC failed")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(zipfile.ZipFile, "open", corrupt)
    if fault == "changed":
        file.temp_path.write_bytes(raw + b"change")
    if fault == "staging_exists":
        file.temp_path.with_name(file.filename).write_bytes(b"foreign stage")

    def journal(_inspection):
        if fault == "journal":
            raise RepositoryError("commit failed")

    with pytest.raises((OSError, ValueError, RepositoryError, zipfile.BadZipFile)):
        publish_capture(file, inspection, journal)
    assert file.temp_path.read_bytes() == raw + (b"change" if fault == "changed" else b"")
    assert not file.final_path.exists() or file.final_path.read_bytes() == b"foreign"
    if fault == "staging_exists":
        assert file.temp_path.with_name(file.filename).read_bytes() == b"foreign stage"


def test_no_raw_cleanup_if_identity_or_archive_changed(recording):
    _, _, file, inspection = recording
    publish_capture(file, inspection)
    file.final_path.write_bytes(b"changed output")
    with pytest.raises((OSError, ValueError)):
        cleanup_zip_source(file, inspection)
    assert file.temp_path.exists()


@pytest.mark.parametrize("moved", [False, True])
def test_interrupted_archive_manual_publication_uses_persisted_identity(
    recording, monkeypatch, moved
):
    repo, plan, file, inspection = recording
    from vil_logging.storage import recovery

    def inspect(path, extension, _tool):
        if extension == "zip":
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None
        return {**observe(path), "packet_count": 42}

    monkeypatch.setattr(recovery, "inspect_recovery_file", inspect)
    prepare_capture_zip(
        file,
        inspection,
        lambda value: repo.update_capture_file(
            plan.session_id, file.role, "publishing", inspection=value
        ),
    )
    if moved:
        publish_capture(file, inspection)
    repo.update_session(plan.session_id, SessionPhase.INCOMPLETE)
    service = RecoveryService(repo)
    service.publish(plan.session_id, "ethernet", service.report()["sessions"][0]["token"], True)
    assert file.final_path.exists() and not file.temp_path.exists()


def test_interrupted_zip_stage_is_owned_cleanup_and_completed_output_survives(recording):
    repo, plan, file, _ = recording
    file.temp_path.with_name(file.filename).write_bytes(b"partial stage")
    file.final_path.write_bytes(b"foreign final")
    repo.update_session(plan.session_id, SessionPhase.INCOMPLETE)
    discard_interrupted(repo, reason="test interrupted compression")
    assert not file.temp_path.exists()
    assert not file.temp_path.with_name(file.filename).exists()
    assert file.final_path.read_bytes() == b"foreign final"


def test_preference_restart_and_older_settings_document_compatibility(tmp_path):
    db = tmp_path / "settings.sqlite3"
    repo = Repository(db)
    assert repo.load_settings(str(tmp_path)).ethernet_compression == "none"
    repo.save_preferences({"ethernet_compression": "zip"})
    document = json.loads(repo._connection.execute("SELECT document FROM settings").fetchone()[0])
    assert "ethernet_compression" not in document
    with pytest.raises(RepositoryError):
        repo.save_preferences({"ethernet_compression": "rar"})
    repo.close()
    repo = Repository(db)
    assert repo.load_settings().ethernet_compression == "zip"
    repo.close()


def test_settings_selection_saves_and_locks_without_language_side_effects(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.set_settings(AppSettings(output_dir="C:/captures"))
    spy = QSignalSpy(dialog.preferences_changed)
    dialog.compression_input.setCurrentIndex(1)
    assert spy.at(0)[0] == {"ethernet_compression": "zip"}
    for language in ("ko", "en", "zh"):
        dialog.set_language(language)
        assert dialog.compression_input.currentData() == "zip"
    assert spy.count() == 1
    dialog.set_busy(True)
    assert not dialog.compression_input.isEnabled()
