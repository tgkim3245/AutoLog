import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy

from vil_logging.diagnostics.network_activity import ActivityHistory, ReceiveCounter
from vil_logging.ui.network_combo import ACTIVITY_ROLE
from vil_logging.ui.settings_dialog import SettingsDialog


def counter(packets, identity=1, status=1):
    return ReceiveCounter(packets, identity, status)


def test_rates_counter_resets_gaps_and_adapter_replacement_are_not_spikes():
    history = ActivityHistory(length=3)
    assert history.update(10, {"nic": counter(100)})["nic"]["pps"] is None
    assert history.update(12, {"nic": counter(160)})["nic"]["pps"] == 30
    for when, value in [(13, counter(5)), (14, counter(500, identity=2)),
                        (15, counter(600, identity=2, status=2)), (25, counter(1000))]:
        assert history.update(when, {"nic": value})["nic"]["pps"] is None
    assert len(history.history["nic"]) == 3
    history.reset_baseline()
    assert history.update(26, {"nic": counter(1200)})["nic"]["pps"] is None
    for when in range(27, 30):
        history.update(when, {})
    assert not history.history and not history.previous and not history.missing


def test_graph_updates_do_not_change_selection_and_sampling_stops_when_hidden(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    nic = dialog.nic_input
    nic.addItem("Ethernet", "nic")
    nic.setCurrentIndex(1)
    nic._activity = {"nic": {"pps": 12, "history": [None, 1, 12]}}
    nic.refresh_activity()
    assert nic.currentData() == "nic"
    assert nic.itemData(1, ACTIVITY_ROLE)["pps"] == 12
    dialog.open_section("ethernet")
    assert nic._timer.isActive()
    dialog.tabs.setCurrentIndex(0)
    assert not nic._timer.isActive()
    dialog.tabs.setCurrentIndex(2)
    assert nic._timer.isActive()
    dialog.hide()
    assert not nic._timer.isActive()


def test_inventory_updates_wait_until_picker_closes(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.nic_input.addItem("Existing", "old")
    dialog.nic_input.setCurrentIndex(1)
    dialog.nic_input.popup_open = True
    dialog.set_connection_discovery({"interfaces": [{"id": "new", "name": "New NIC"}]})
    assert dialog.nic_input.currentData() == "old"
    assert dialog.nic_input.findData("new") < 0
    dialog.nic_input.hidePopup()
    qtbot.waitUntil(lambda: dialog.nic_input.findData("new") >= 0)
    assert dialog.nic_input.currentData() == "old"


@pytest.mark.parametrize("input_method", ["mouse", "keyboard"])
def test_selection_survives_popup_close_and_inventory_refresh(qtbot, input_method):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    report = {"interfaces": [{"id": "wifi", "name": "Wi-Fi"}, {"id": "vehicle", "name": "Ethernet"}]}
    dialog.set_connection_discovery(report)
    dialog.open_section("ethernet")
    nic = dialog.nic_input
    nic.set_sampling(False)
    nic.setCurrentIndex(nic.findData("wifi"))
    spy = QSignalSpy(dialog.preferences_changed)
    nic.showPopup()
    qtbot.waitUntil(lambda: nic.view().isVisible())
    dialog.set_connection_discovery({"interfaces": list(reversed(report["interfaces"]))})
    index = nic.model().index(nic.findData("vehicle"), 0)
    if input_method == "mouse":
        qtbot.mouseClick(nic.view().viewport(), Qt.MouseButton.LeftButton, pos=nic.view().visualRect(index).center())
    else:
        qtbot.keyClick(nic.view(), Qt.Key.Key_Down)
        qtbot.keyClick(nic.view(), Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not nic.view().isVisible())
    qtbot.wait(10)
    assert nic.currentData() == "vehicle"
    assert spy.count() == 1 and spy.at(0)[0] == {"nic_id": "vehicle"}
