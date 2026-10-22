from dataclasses import replace
from pathlib import Path

import pytest

from vil_logging.contracts.models import AppSettings, Role
from vil_logging.storage.naming import (
    NamingError,
    build_plan,
    capture_prefix,
    find_collisions,
    parse_index,
    renamed_filename,
    validate_settings,
)


def settings_for(folder: Path, **changes) -> AppSettings:
    return replace(AppSettings(output_dir=str(folder)), **changes)


def test_exact_role_names_share_large_decimal_index(tmp_path):
    index = 10**60 + 987654321
    settings = settings_for(tmp_path, prefix="주행", next_index=index, ethernet_format="pcapng")
    plan = build_plan(settings, tuple(Role))
    assert [file.filename for file in plan.files] == [
        f"주행_{index}.blf", f"주행_Diag_{index}.blf", f"주행_{index}.pcapng",
    ]
    assert all(file.temp_path.name == file.final_path.name for file in plan.files)
    assert all(file.temp_path.parent == tmp_path / ".vil_work" / plan.session_id for file in plan.files)
    assert not list(tmp_path.iterdir())


def test_diag_only_retains_marker_and_zero_index(tmp_path):
    plan = build_plan(settings_for(tmp_path, next_index=0), (Role.DIAG,))
    assert [file.filename for file in plan.files] == ["One_Click_Log_Diag_0.blf"]


def test_capture_prefix_adds_one_separator_and_preserves_existing_separator():
    assert capture_prefix("Road") == "Road_"
    assert capture_prefix("Road_") == "Road_"


def test_previous_rename_uses_literal_name_without_index():
    assert renamed_filename("Road trip", Role.CAN, "blf") == "Road trip.blf"
    assert renamed_filename("Road trip", Role.DIAG, "blf") == "Road trip_Diag.blf"
    assert renamed_filename("Road trip", Role.ETHERNET, "pcapng") == "Road trip.pcapng"


@pytest.mark.parametrize("name", ["", "  ", "bad/name", "CON", "x" * 252])
def test_previous_rename_rejects_invalid_filename(name):
    with pytest.raises(NamingError):
        renamed_filename(name, Role.CAN, "blf")


@pytest.mark.parametrize("text", ["1.0", "1e9", "-1", " 1", "1 ", "", "１２", "1_000"])
def test_index_parser_rejects_non_decimal_input(text):
    with pytest.raises(NamingError):
        parse_index(text)


def test_decimal_parser_preserves_large_integer_and_normalizes_zeroes():
    text = "9" * 100
    assert str(parse_index(text)) == text
    assert parse_index("0000007") == 7
    assert parse_index("0" * 5000) == 0


@pytest.mark.parametrize("index", [-1, 1.0, True, "1"])
def test_settings_reject_non_integer_or_negative_index(tmp_path, index):
    with pytest.raises(NamingError):
        validate_settings(settings_for(tmp_path, next_index=index), (Role.CAN,))


@pytest.mark.parametrize("prefix", ["a/b", "a\\b", "a:b", 'a"b', "a<b", "a>b", "a|b", "a?b", "a*b", "a\n", "a\0", "a.", "a "])
def test_windows_filename_forbidden_characters(tmp_path, prefix):
    with pytest.raises(NamingError):
        build_plan(settings_for(tmp_path, prefix=prefix), (Role.CAN,))


def test_name_and_temporary_path_length_are_checked(tmp_path):
    with pytest.raises(NamingError):
        build_plan(settings_for(tmp_path, prefix="가" * 250), (Role.DIAG,))
    with pytest.raises(NamingError):
        build_plan(settings_for(tmp_path, next_index=10**300), (Role.CAN,))
    with pytest.raises(NamingError):
        build_plan(settings_for(tmp_path / ("d" * 180)), (Role.CAN,))


def test_output_preflight_does_not_leave_probe_file(tmp_path):
    validate_settings(settings_for(tmp_path), tuple(Role))
    assert not list(tmp_path.iterdir())
    with pytest.raises(NamingError):
        validate_settings(settings_for(tmp_path / "missing"), (Role.CAN,))
    build_plan(settings_for(tmp_path / "missing"), (Role.CAN,))


def test_collision_checks_final_files_and_directories(tmp_path):
    plan = build_plan(settings_for(tmp_path), tuple(Role))
    plan.files[0].final_path.write_bytes(b"existing")
    plan.files[1].final_path.mkdir()
    assert find_collisions(plan) == [plan.files[0].final_path, plan.files[1].final_path]
    assert plan.files[0].final_path.read_bytes() == b"existing"


def test_no_selection_can_be_saved_but_cannot_capture(tmp_path):
    validate_settings(settings_for(tmp_path), ())
    with pytest.raises(NamingError):
        build_plan(settings_for(tmp_path), ())


def test_duplicate_or_unknown_roles_and_traversal_uuid_rejected(tmp_path):
    settings = settings_for(tmp_path)
    for roles in ((Role.CAN, Role.CAN), ("can",)):
        with pytest.raises(NamingError):
            build_plan(settings, roles)
    with pytest.raises(NamingError):
        build_plan(settings, (Role.CAN,), session_id="../../outside")
