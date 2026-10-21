"""Desktop entry point and UI-to-background service wiring."""

import argparse
import json
import logging
import os
import queue
import sys
import threading
from pathlib import Path
from uuid import uuid4

from vil_logging import APP_NAME, __version__


def default_data_dir(demo: bool = False) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / APP_NAME
    return base / "demo" if demo else base


def legacy_data_dirs(demo: bool = False) -> tuple[Path, ...]:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    suffix = ("demo",) if demo else ()
    return tuple(base.joinpath(name, *suffix) for name in ("Auto_Log", "VILLogging"))


def developer_log_directory(data_dir: Path, *, use_data_dir: bool = False,
                            executable: Path | None = None, frozen: bool | None = None) -> Path:
    """Place packaged logs beside the executable; isolate test logs by data-dir."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        program_dir = Path(executable or sys.executable).resolve().parent
    elif use_data_dir:
        program_dir = Path(data_dir)
    else:
        program_dir = Path(__file__).resolve().parents[2]
    return program_dir / "developer_logs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} capture control panel")
    parser.add_argument("--demo", action="store_true", help="Simulation; never creates capture files")
    parser.add_argument("--data-dir", type=Path, help="Override the local application data folder")
    parser.add_argument("--diagnose", action="store_true", help="Print read-only environment checks as JSON")
    parser.add_argument("--smoke-test", action="store_true", help="Run a short offscreen simulation and exit")
    parser.add_argument("--smoke-debug-log", action="store_true",
                        help="Verify always-on developer logging during --smoke-test")
    parser.add_argument("--smoke-discovery", action="store_true",
                        help="Verify read-only tool/NIC discovery reaches the UI during --smoke-test")
    parser.add_argument("--verify-ethernet", action="store_true",
                        help="Explicit real capture verification using only generated localhost packets")
    parser.add_argument("--verify-file-management", action="store_true",
                        help="Verify native file management using only generated capture fixtures")
    parser.add_argument("--verify-recovery", action="store_true",
                        help="Verify recovery using generated offline BLF/PCAP/PCAPNG files only")
    parser.add_argument("--verify-monitoring", action="store_true",
                        help="Verify monitoring with generated localhost packets only")
    parser.add_argument("--verify-load", action="store_true", help="Numbered localhost load test; never opens a physical NIC")
    parser.add_argument("--tshark", default="", help="Explicit tshark.exe path for --verify-* commands")
    parser.add_argument("--load-duration", type=int, default=10, help="Load duration in seconds (default 10)")
    parser.add_argument("--load-pps", type=int, default=1000, help="Generated packets per second (default 1000)")
    parser.add_argument("--load-payload", type=int, default=512, help="UDP payload bytes (default 512)")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    if any((args.verify_load, args.verify_monitoring, args.verify_recovery, args.verify_ethernet)) and not args.tshark:
        parser.error("Capture verification requires --tshark <full path to tshark.exe>")
    if args.verify_load:
        if any((args.demo, args.smoke_test, args.diagnose, args.verify_monitoring, args.verify_ethernet,
                args.verify_file_management, args.verify_recovery, args.smoke_debug_log, args.smoke_discovery)):
            parser.error("--verify-load requires a separate verification run")
        from vil_logging.diagnostics.load_test import validate_load, verify_load
        try:
            validate_load(args.load_duration, args.load_pps, args.load_payload)
        except ValueError as error:
            parser.error(str(error))
        folder = args.data_dir or default_data_dir() / "development" / "load-verification" / uuid4().hex
        report = verify_load(folder, duration=args.load_duration, pps=args.load_pps,
                             payload_size=args.load_payload, tshark_path=args.tshark)
        print(json.dumps({key: value for key, value in report.items() if key != "samples"}, ensure_ascii=False))
        return 0 if report["passed"] else 2
    if args.verify_monitoring:
        if args.demo or args.smoke_test or args.verify_ethernet or args.verify_file_management or args.verify_recovery:
            parser.error("--verify-monitoring requires a separate verification run")
        from vil_logging.verification import verify_monitoring
        folder = args.data_dir or default_data_dir() / "development" / "monitor-verification" / uuid4().hex
        report = verify_monitoring(folder, tshark_path=args.tshark)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["passed"] else 2
    if args.verify_recovery:
        if args.demo or args.smoke_test or args.verify_ethernet or args.verify_file_management:
            parser.error("--verify-recovery requires a separate verification run")
        from vil_logging.verification import verify_recovery
        folder = args.data_dir or default_data_dir() / "development" / "recovery-verification" / uuid4().hex
        report = verify_recovery(folder, tshark_path=args.tshark)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["passed"] else 2
    if args.verify_file_management:
        if args.demo or args.smoke_test or args.verify_ethernet:
            parser.error("--verify-file-management requires a separate verification run")
        from vil_logging.verification import verify_file_management
        folder = args.data_dir or default_data_dir() / "development" / "file-verification" / uuid4().hex
        report = verify_file_management(folder)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["passed"] else 2
    if args.verify_ethernet:
        if args.demo or args.smoke_test:
            parser.error("--verify-ethernet cannot be combined with simulation flags")
        from vil_logging.verification import verify_ethernet
        folder = args.data_dir or default_data_dir() / "development" / "ethernet-verification" / uuid4().hex
        report = verify_ethernet(folder, tshark_path=args.tshark)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["passed"] else 2
    if args.smoke_debug_log and not args.smoke_test:
        parser.error("--smoke-debug-log requires --smoke-test")
    if args.smoke_discovery and not args.smoke_test:
        parser.error("--smoke-discovery requires --smoke-test")
    if args.diagnose:
        from vil_logging.diagnostics.environment import collect_environment
        print(json.dumps(collect_environment(), ensure_ascii=False, indent=2))
        return 0
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        args.demo = True
        if args.data_dir is None:
            args.data_dir = default_data_dir() / "development" / "smoke" / uuid4().hex
    from PySide6.QtCore import QStandardPaths, QTimer, QUrl
    from PySide6.QtGui import QDesktopServices, QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    from vil_logging.contracts.models import AppEvent, SessionPhase
    from vil_logging.diagnostics.debug_log import DebugLogService
    from vil_logging.diagnostics.readiness import missing_dependencies
    from vil_logging.instance import SingleInstance
    from vil_logging.runtime import Runtime
    from vil_logging.ui import MainWindow
    from vil_logging.ui.environment_dialog import EnvironmentDialog
    from vil_logging.ui.i18n import tr

    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setFont(QFont("Malgun Gothic", 9))
    app.setQuitOnLastWindowClosed(False)
    explicit_data_dir = args.data_dir is not None
    data_dir = args.data_dir or default_data_dir(args.demo)
    legacy_instances = []
    try:
        if args.data_dir is None:
            old_profiles = legacy_data_dirs(args.demo)
            for legacy_dir in old_profiles:
                legacy_instance = SingleInstance(legacy_dir, name_prefix=legacy_dir.name)
                if not legacy_instance.acquire(activate_existing=False):
                    for acquired in legacy_instances:
                        acquired.close()
                    QMessageBox.information(
                        None,
                        APP_NAME,
                        f"기존 {legacy_dir.name} 프로그램이 실행 중입니다.\n\n"
                        "작업 중인 내용을 저장한 뒤 기존 프로그램을 완전히 종료하고 "
                        f"{APP_NAME}를 다시 실행해 주세요. 설정과 기록을 안전하게 옮기려면 "
                        "이전 프로그램이 종료되어야 합니다.",
                    )
                    return 0
                legacy_instances.append(legacy_instance)
            from vil_logging.storage.profile_migration import migrate_legacy_profile
            for legacy_dir in old_profiles:
                if migrate_legacy_profile(legacy_dir, data_dir):
                    break
        instance = SingleInstance(data_dir)
        if not instance.acquire():
            for legacy_instance in legacy_instances:
                legacy_instance.close()
            return 0
    except Exception as error:
        for legacy_instance in legacy_instances:
            legacy_instance.close()
        QMessageBox.critical(None, APP_NAME, str(error))
        return 1
    window = MainWindow(demo=args.demo)
    window.set_initializing(True)
    instance.activated.connect(window.restore_window)
    log_dir = developer_log_directory(
        data_dir, use_data_dir=explicit_data_dir or args.smoke_test,
    )
    debug = DebugLogService(data_dir, log_dir=log_dir)
    last_debug_error = ""
    try:
        debug_path = debug.enable()
        debug.log("app.startup", app_data_dir=str(data_dir), demo=args.demo)
    except Exception as error:
        last_debug_error = str(error)
        debug_path = debug.log_path
    developer_log_default = debug.enabled
    window.set_debug_status(str(debug_path or ""), last_debug_error)
    runtime = Runtime(data_dir, demo=args.demo)
    from vil_logging.exit_guard import ExitGuard
    exit_guard = ExitGuard(runtime.force_abort)
    exiting = False
    saved_excepthook = sys.excepthook
    saved_thread_hook = threading.excepthook

    def record_ui_event(code: str, *, level: str = "INFO", original: str = "", **params):
        runtime._submit(runtime._event, code, level=level, original=original, **params)

    def export_bug_report():
        try:
            desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
            if not desktop:
                raise OSError("바탕화면 저장 위치를 확인할 수 없습니다.")
            debug.log("bug_report.export_requested", selected_roles=[role.value for role in window.selected_roles()],
                      phase=runtime.phase.value, demo=args.demo)
            report = debug.export_report(Path(desktop))
            window.add_event(AppEvent("BUG_REPORT_EXPORTED", params={"filename": report.name}))
            QMessageBox.information(
                window, tr("bug_report_title", window._language),
                tr("bug_report_saved", window._language).format(filename=report.name),
            )
        except Exception as error:
            debug.exception("bug_report.export_failed", error)
            QMessageBox.warning(
                window, tr("bug_report_title", window._language),
                tr("bug_report_failed", window._language).format(error=str(error)),
            )

    def request_exit():
        nonlocal exiting
        exit_guard.request()
        if not exiting:
            exiting = True
            debug.log("app.exit_requested", phase=runtime.phase.value)
            window.set_exiting(True)
            window.set_phase(SessionPhase.STOPPING)
            runtime.request_exit()

    def open_log_folder():
        output = window._settings.output_dir.strip()
        if not output:
            window.settings_dialog.open_section("storage")
            return
        try:
            folder = Path(output).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                raise OSError("Could not open the capture output folder")
        except OSError as error:
            debug.exception("capture_folder.open_failed", error, output_dir=output)
            QMessageBox.warning(window, tr("debug_folder", window._language), str(error))

    def exception_hook(error_type, error, traceback):
        debug.exception("app.uncaught_exception", error)
        runtime._publish("event", AppEvent("OPERATION_ERROR", "ERROR", original=str(error)))
        saved_excepthook(error_type, error, traceback)

    def thread_exception_hook(args):
        debug.exception("thread.uncaught_exception", args.exc_value, thread=args.thread.name)
        runtime._publish("event", AppEvent("OPERATION_ERROR", "ERROR", original=str(args.exc_value)))
        saved_thread_hook(args)

    sys.excepthook = exception_hook
    threading.excepthook = thread_exception_hook
    window.bug_report_requested.connect(export_bug_report)
    window.settings_applied.connect(lambda settings: runtime.apply_naming(settings, window.selected_roles()))
    window.preferences_changed.connect(runtime.save_preferences)
    window.prepare_requested.connect(runtime.prepare)
    window.discovery_requested.connect(runtime.discover)
    window.exit_requested.connect(request_exit)
    window.open_debug_folder_requested.connect(open_log_folder)
    window.rename_requested.connect(runtime.rename_previous)
    window.delete_files_requested.connect(runtime.delete_files)
    window.files_refresh_requested.connect(runtime.refresh_file_history)
    window.recovery_requested.connect(runtime.recover)
    environment_dialog = EnvironmentDialog(window)
    environment_state = {"environment": {}, "connections": {}, "pending": False, "discovering": False,
                         "error": "", "startup_checked": args.demo}

    def show_environment():
        environment_dialog.set_language(window._language)
        environment_dialog.set_roles(window.selected_roles())
        environment_dialog.show()
        environment_dialog.raise_()
        environment_dialog.activateWindow()
        environment_state["pending"] = True
        window.set_environment_checking(True)
        environment_state["error"] = ""
        environment_dialog.set_busy(True)
        runtime.diagnose()
        runtime.discover()

    def toggle_capture():
        if (not args.demo and runtime.phase in {SessionPhase.IDLE, SessionPhase.COMPLETED, SessionPhase.FAILED}
                and missing_dependencies(environment_state["environment"], environment_state["connections"],
                                         window.selected_roles())):
            show_environment()
            window.set_phase(runtime.phase)
            return
        runtime.toggle(window.selected_roles())
        window.set_phase(runtime.phase)

    window.logging_requested.connect(toggle_capture)
    window.environment_requested.connect(show_environment)
    environment_dialog.refresh_requested.connect(show_environment)
    environment_dialog.settings_requested.connect(window.settings_dialog.open_section)

    def update_environment():
        window.set_environment_checking(environment_state["pending"] or environment_state["discovering"])
        environment_dialog.set_roles(window.selected_roles())
        environment_dialog.set_report(environment_state["environment"], environment_state["connections"])
        environment_dialog.set_busy(environment_state["pending"] or environment_state["discovering"])
        if environment_state["error"]:
            environment_dialog.set_error(environment_state["error"])
            if not environment_state["startup_checked"]:
                environment_state["startup_checked"] = True
                environment_dialog.show()
        if (not environment_state["startup_checked"] and environment_state["environment"]
                and environment_state["connections"]):
            environment_state["startup_checked"] = True
            missing = missing_dependencies(environment_state["environment"], environment_state["connections"],
                                           window.selected_roles())
            debug.log("readiness.startup_checked", missing=sorted(missing))
            if missing:
                environment_dialog.show()
                environment_dialog.raise_()
                environment_dialog.activateWindow()

    def drain():
        nonlocal last_debug_error, exiting
        if window._initializing and initialization.done():
            window.set_initializing(False, failed=not runtime._ready)
        for _ in range(256):
            try:
                kind, value = runtime.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "settings":
                window.set_settings(value)
                environment_dialog.set_language(value.language)
            elif kind == "phase":
                # A click already reflects the latest runtime phase immediately.
                # Delayed queued notifications must not undo that newer state.
                window.set_phase(runtime.phase)
            elif kind == "capture_step":
                window.set_capture_step(value)
            elif kind == "target":
                window.set_target(value)
            elif kind == "event":
                window.add_event(value)
            elif kind == "events":
                for event in value:
                    window.add_event(event)
            elif kind == "files":
                window.set_files(*value)
            elif kind == "capture_history":
                window.set_capture_history(value)
            elif kind == "capture_quality":
                window.set_capture_quality(value)
            elif kind == "file_operations":
                window.file_manager.set_operations(value)
            elif kind == "file_busy":
                window.set_file_busy(value)
            elif kind == "file_result":
                window.set_file_result(value)
            elif kind == "recovery":
                window.set_recovery(value)
            elif kind == "recovery_result":
                window.recovery_dialog.set_result(value)
            elif kind == "packets_clear":
                window.packet_window.clear_session()
            elif kind == "connections":
                window.set_connection_discovery(value)
                environment_state["connections"] = value
                update_environment()
            elif kind == "discovery_busy":
                window.settings_dialog.set_discovery_busy(value)
                environment_state["discovering"] = value
                update_environment()
            elif kind == "discovery_error":
                window.settings_dialog.set_error(value)
                window.settings_dialog.set_discovery_error(value)
                environment_state["error"] = value
                update_environment()
            elif kind == "preparation":
                window.set_preparation_report(value)
            elif kind == "environment" and not args.smoke_test:
                environment_state["environment"] = value
                environment_state["pending"] = False
                update_environment()
            elif kind == "environment_error":
                environment_state["pending"] = False
                environment_state["error"] = value
                update_environment()
            elif kind == "exit_ready":
                if value:
                    # Leave the UI event loop only after orderly shutdown is verified.
                    app.exit(0)
                    return
                else:
                    exit_guard.force("cleanup_failed")
                    return
        for packet in runtime.drain_packets():
            window.add_packet(packet)
        window.check_monitor_freshness()
        if debug.enabled:
            try:
                debug.check_health()
            except Exception as error:
                if str(error) != last_debug_error:
                    last_debug_error = str(error)
                    window.set_debug_status(str(debug.log_path or ""), last_debug_error)
                    record_ui_event("DEBUG_LOG_ERROR", level="ERROR", original=last_debug_error)

    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(drain)
    timer.start()
    health_timer = QTimer()
    health_timer.setInterval(700)
    health_timer.timeout.connect(runtime.poll_workers)
    health_timer.start()
    initialization = runtime.initialize()
    if not args.smoke_test or args.smoke_discovery:
        runtime.discover()
    if not args.demo:
        environment_state["pending"] = True
        runtime.diagnose()
    window.show()
    smoke = {"started": False, "stopped": False, "passed": False, "button_actions": [],
             "discovery_passed": not args.smoke_discovery}
    if args.smoke_test:
        smoke_timer = QTimer()
        smoke_timer.setInterval(100)

        def smoke_step():
            if not smoke["discovery_passed"]:
                report = window._discovery_report
                settings_view = window.settings_dialog
                if not report or settings_view._discovering:
                    return
                if any(settings_view.nic_input.findData(item["id"]) < 0 for item in report.get("interfaces", [])):
                    return
                if settings_view.tool_status.text() == settings_view._t("finding"):
                    return
                smoke["discovery_passed"] = True
            if runtime._ready and not smoke["started"]:
                if not window.logging_button.isEnabled():
                    return
                smoke["started"] = True
                if args.smoke_debug_log:
                    debug.log("smoke.debug_log_verified", phase=runtime.phase.value)
                window.logging_button.click()
                smoke["button_actions"].append("start")
            elif runtime.phase == SessionPhase.RECORDING and not smoke["stopped"]:
                if window._phase != SessionPhase.RECORDING or not window.logging_button.isEnabled():
                    return
                smoke["stopped"] = True
                window.logging_button.click()
                smoke["button_actions"].append("stop")
            elif runtime.phase == SessionPhase.COMPLETED:
                if window._phase != SessionPhase.COMPLETED:
                    return
                smoke["passed"] = True
                smoke_timer.stop()
                window.close()
                smoke["button_actions"].append("exit")
        smoke_timer.timeout.connect(smoke_step)
        smoke_timer.start()
        QTimer.singleShot(30000 if args.smoke_discovery else 15000, lambda: app.exit(2))
    try:
        result = app.exec()
    finally:
        timer.stop()
        health_timer.stop()
        sys.excepthook = saved_excepthook
        threading.excepthook = saved_thread_hook
        if not runtime._closed:
            # Process/OS termination cannot be certified as normal recorder shutdown.
            logging.getLogger(__name__).warning("app.event_loop_ended_before_orderly_shutdown")
        runtime.close_for_test()  # Abnormal teardown preserves partial files and session evidence.
        try:
            debug.close()
        except Exception as error:
            print(f"Developer log close failed: {error}", file=sys.stderr)
        instance.close()
        for legacy_instance in legacy_instances:
            legacy_instance.close()
        exit_guard.finish()
    if args.smoke_test:
        print(json.dumps({"smoke_passed": smoke["passed"], "data_dir": str(data_dir),
                          "capture_button_actions": smoke["button_actions"],
                          "developer_log_default": developer_log_default,
                          "developer_log_path": str(debug.log_path or ""),
                          "discovery_ui_verified": smoke["discovery_passed"] if args.smoke_discovery else None,
                          "discovered_interfaces": len(window._discovery_report.get("interfaces", [])),
                          "npcap_status": window._discovery_report.get("npcap", {}).get("status", "unchecked")},
                         ensure_ascii=False))
        return 0 if smoke["passed"] else 2
    return result
