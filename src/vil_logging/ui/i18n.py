"""Small explicit translation catalog; tool error originals are always retained."""

from datetime import datetime

from vil_logging.contracts.models import AppEvent

TEXT = {
    "title": ("로그 캡처", "Log capture"),
    "subtitle": ("CAN · Diag · Zipy 통합 제어", "CAN · Diag · Zipy controls"),
    "settings": ("설정", "Settings"),
    "packets": ("패킷 보기", "Packets"),
    "environment": ("환경 확인", "Check environment"),
    "exit": ("프로그램 종료", "Exit program"),
    "show": ("창 열기", "Show window"),
    "next_files": ("다음 캡처 파일명", "Next capture filenames"),
    "current_files": ("현재 기록 파일", "Currently recording"),
    "previous_files": ("직전 기록 파일", "Previous capture files"),
    "incomplete_files": ("확인 필요 파일", "Files requiring review"),
    "previous_name": ("직전 파일 새 이름 (확장자 제외)", "New filename for previous logs (without extension)"),
    "rename": ("이름 변경", "Rename"),
    "delete": ("직전 로그 지우기", "Delete previous"),
    "file_manager": ("파일 관리", "Capture files"),
    "file_operations": ("작업 이력", "Operation history"),
    "file_kind_rename": ("이름 변경", "Rename"),
    "file_kind_delete": ("삭제", "Delete"),
    "file_item_pending": ("처리 미확인", "Pending"),
    "file_item_renamed": ("이름 변경됨", "Renamed"),
    "file_item_deleted": ("삭제됨", "Deleted"),
    "file_item_unchanged": ("변경 없음", "Unchanged"),
    "file_item_failed": ("실패", "Failed"),
    "file_item_recovered_rename": ("변경 경로 확인됨", "Renamed path recovered"),
    "file_item_not_applied": ("미실행 확인됨", "Not applied"),
    "file_item_review": ("결과 확인 필요", "Review required"),
    "file_manager_help": ("최근 100개 세션 · 체크한 보관 완료 파일만 삭제합니다. 다음 저장 번호는 유지됩니다.",
                          "Latest 100 sessions · delete checked published files. The next capture index is preserved."),
    "file_ops_help": ("입력한 이름 그대로 변경하고 인덱스는 붙이지 않습니다. 확장자는 유지합니다. Diag는 _Diag가 붙습니다. 다음 번호는 유지됩니다.",
                      "Use the entered name as the filename without an index. Extensions stay the same; Diag keeps _Diag. The next index is preserved."),
    "file_operation_busy": ("파일을 처리하고 있습니다…", "Processing capture files…"),
    "capture_number": ("번호 · 대상", "Index · Target"),
    "filename": ("파일명", "Filename"),
    "file_state": ("상태", "Status"),
    "full_path": ("전체 경로", "Full path"),
    "refresh": ("새로 고침", "Refresh"),
    "open_folder": ("폴더 열기", "Open folder"),
    "delete_selected": ("선택 파일 삭제", "Delete selected"),
    "cancel": ("취소", "Cancel"),
    "delete_permanently": ("영구 삭제", "Delete permanently"),
    "delete_confirm_title": ("캡처 파일 삭제 확인", "Confirm capture file deletion"),
    "delete_confirm_help": ("아래 {count}개 파일을 영구 삭제합니다. 휴지통으로 이동하지 않습니다. 전체 경로를 확인하세요.",
                            "Permanently delete these {count} files without using the Recycle Bin. Review the full paths."),
    "file_state_published": ("보관 완료", "Published"),
    "file_state_deleted": ("삭제됨", "Deleted"),
    "file_state_missing": ("파일 없음", "Missing"),
    "file_state_changed": ("파일 변경됨", "Changed"),
    "file_state_unavailable": ("접근 불가", "Unavailable"),
    "file_state_review": ("작업 확인 필요", "Review operation"),
    "file_state_planned": ("기록 예약", "Reserved"),
    "file_state_writing": ("기록 중", "Writing"),
    "file_state_closed": ("검사 전", "Closed"),
    "file_state_publishing": ("보관 확인 필요", "Publication unconfirmed"),
    "file_state_failed": ("실패 파일 보존", "Failed · preserved"),
    "file_state_unknown": ("닫힘 미확인", "Closure unconfirmed"),
    "file_state_not_created": ("파일 미생성", "Not created"),
    "file_result_completed": ("파일 처리 완료 · 다음 번호 유지", "File operation completed · index preserved"),
    "file_result_partial": ("일부 파일 처리 실패 · 파일별 결과를 확인하세요.", "Partial result · review each file."),
    "file_result_blocked": ("파일을 변경하지 못했습니다. 파일별 원인을 확인하세요.", "No files changed. Review each file's error."),
    "file_result_error": ("파일 작업 실패 · 상세 내용을 확인하세요.", "File operation failed. Review details."),
    "file_result_review": ("중단된 파일 작업의 결과를 확인해야 합니다.", "An interrupted file operation needs review."),
    "file_result_recovered": ("파일 식별 정보로 변경 경로를 회수했습니다.", "Recovered renamed paths using file identity."),
    "demo_file_ops": ("모의 실행은 실제 파일을 만들지 않아 이름 변경·삭제를 사용할 수 없습니다.",
                      "Simulation creates no capture files, so renaming and deleting are unavailable."),
    "events": ("최근 활동", "Recent activity"),
    "event_count": ("{count} / 500", "{count} / 500"),
    "capture_targets": ("로깅 대상", "Capture targets"),
    "selected_count": ("{count}개 선택", "{count} selected"),
    "action_unprepared": ("설정에서 연결을 준비한 뒤 logging을 누르세요.",
                          "Prepare connections in Settings, then press logging."),
    "action_no_targets": ("기록할 대상을 하나 이상 선택하세요.", "Select at least one target to capture."),
    "action_ready": ("선택한 대상이 준비되었습니다. logging으로 기록을 시작하세요.",
                     "Selected targets are ready. Press logging to start."),
    "action_preparing": ("선택한 대상의 기록 준비 상태를 확인하고 있습니다.", "Checking capture readiness for selected targets."),
    "action_starting": ("기록을 시작하고 있습니다. 다시 누르면 취소를 요청합니다.", "Starting capture. Press again to request cancellation."),
    "action_recording": ("선택한 대상의 기록을 유지하고 있습니다. logging을 누르면 정지합니다.",
                         "Selected captures are running. Press logging to stop."),
    "action_partial": ("일부 대상에 문제가 있습니다. 나머지 기록은 계속됩니다.", "Some targets need attention. Other captures continue."),
    "action_stopping": ("기록을 정지하고 파일 상태를 확인하고 있습니다.", "Stopping capture and verifying file status."),
    "action_completed": ("기록을 종료하고 파일 보관을 확인했습니다.", "Capture ended and file storage was verified."),
    "action_failed": ("기록 또는 파일 처리에 문제가 있습니다. 최근 활동과 실제 파일 경로를 확인하세요.",
                      "Capture or file processing failed. Review recent activity and the actual file path."),
    "action_incomplete": ("상태를 확인할 수 없습니다. 최근 활동과 개발자 로그를 확인하세요.",
                          "State is unconfirmed. Review recent activity and developer logs."),
    "ethernet_stage": ("CAN·Diag 구간 기록 · Zipy 패킷 캡처", "CAN/Diag segment recording · Zipy packet capture"),
    "phase_short_idle": ("대기", "Idle"),
    "phase_short_preparing": ("준비 중", "Preparing"),
    "phase_short_starting": ("시작 중", "Starting"),
    "phase_short_recording": ("기록 중", "Recording"),
    "phase_short_partial": ("일부 기록 중", "Partial"),
    "phase_short_stopping": ("정지 중", "Stopping"),
    "phase_short_completed": ("종료", "Ended"),
    "phase_short_failed": ("실패", "Failed"),
    "phase_short_incomplete": ("확인 필요", "Unconfirmed"),
    "events_empty": ("기록된 알림이 없습니다.", "No events recorded."),
    "debug_folder": ("로그 폴더", "Log folder"),
    "bug_report": ("버그리포트", "Bug report"),
    "bug_report_title": ("버그리포트", "Bug report"),
    "bug_report_saved": (
        "바탕화면에 개발자 로그를 저장했습니다.\n파일명: {filename}\n"
        "이 파일을 Taegon.Kim에게 이메일로 보내 주세요.",
        "The developer log was saved to your Desktop.\nFilename: {filename}\n"
        "Please email this file to Taegon.Kim.",
    ),
    "bug_report_failed": (
        "개발자 로그를 저장하지 못했습니다.\n{error}",
        "Could not save the developer log.\n{error}",
    ),
    "debug_help": ("개발자 로그를 항상 순환 저장합니다. 버그리포트를 눌러 최근 로그를 바탕화면에 저장하세요.",
                   "Developer diagnostics are always saved in a rolling log. Use Bug report to export recent logs."),
    "debug_off": ("개발자 로그 저장 경로가 없습니다", "Developer log path is unavailable"),
    "debug_on": ("개발자 로그 저장 중", "Developer log is being saved"),
    "demo": ("모의 데모 · 실제 로그 파일을 만들지 않습니다", "Simulation · no capture files are created"),
    "demo_files": ("모의 예정/결과 · 파일 미생성", "Simulated filenames / results · no files created"),
    "demo_completed": ("모의 종료 · 파일 미생성", "Simulation ended · no files created"),
    "demo_recording": ("모의 기록 중 · 누르면 정지", "Simulation running · click to stop"),
    "demo_partial": ("일부 모의 기록 중 · 누르면 정지", "Partial simulation · click to stop"),
    "real": ("X를 누르면 기록을 정리하고 프로그램을 종료합니다", "X stops capture cleanly, then exits the program"),
    "output": ("저장 위치", "Output folder"),
    "unset": ("미설정", "Not configured"),
    "prefix": ("파일 prefix", "Filename prefix"),
    "next_index": ("다음 저장 인덱스", "Next capture index"),
    "format": ("Ethernet 저장 형식", "Ethernet file format"),
    "tshark": ("TShark 실행 파일", "TShark executable"),
    "nic": ("NIC 식별자", "NIC identifier"),
    "browse": ("찾기", "Browse"),
    "prepare": ("연결 준비", "Prepare"),
    "apply": ("적용", "Apply"),
    "close": ("닫기", "Close"),
    "save_first": ("변경한 설정을 적용한 뒤 연결 준비를 실행하세요.",
                   "Apply changed settings before preparing a connection."),
    "invalid_index": ("다음 인덱스에 0 이상의 정수를 입력하세요.",
                      "Enter a non-negative integer for the next index."),
    "locked": ("기록 처리 중에는 대상과 설정을 바꿀 수 없습니다.",
               "Targets and settings are locked during capture operations."),
    "ready_tip": ("연결 준비와 로깅 선택은 독립적입니다.",
                  "Connection preparation and capture selection are independent."),
    "pause": ("화면 일시 정지", "Pause display"),
    "filter": ("표시 필터", "Display filter"),
    "packet_hint": ("최근 1,000건 · 표시 필터/일시 정지/닫기는 원본 기록에 영향을 주지 않습니다.",
                    "Latest 1,000 · filtering, pausing and closing do not affect capture."),
    "packet_counts": ("최근 {count} / 1,000건", "Latest {count} / 1,000 packets"),
    "packet_filter_placeholder": ("IP, MAC 또는 프로토콜로 검색", "Search by IP, MAC or protocol"),
    "time": ("수신 시각", "Received"),
    "source": ("출처 IP / MAC", "Source IP / MAC"),
    "destination": ("목적지 IP / MAC", "Destination IP / MAC"),
    "protocol": ("프로토콜", "Protocol"),
    "length": ("길이", "Length"),
    "idle": ("대기", "Idle"),
    "preparing": ("준비 중 · 누르면 취소 요청", "Preparing · click to cancel"),
    "starting": ("시작 중 · 누르면 취소 요청", "Starting · click to cancel"),
    "recording": ("기록 중 · 누르면 정지", "Recording · click to stop"),
    "partial": ("일부 기록 중 · 누르면 정지", "Partially recording · click to stop"),
    "stopping": ("정지·파일 확인 중", "Stopping · checking files"),
    "completed": ("보관 완료", "Completed"),
    "failed": ("실패", "Failed"),
    "incomplete": ("미완료 · 로그 확인 필요", "Incomplete · review events"),
    "disconnected": ("미연결", "Disconnected"),
    "connecting": ("연결 중", "Connecting"),
    "ready": ("준비 완료", "Ready"),
    "error": ("오류", "Error"),
    "unknown": ("확인 불가", "Unknown"),
    "not_monitored": ("감시 안 함", "Not monitored"),
    "not_configured": ("감시 미설정", "Monitor not set"),
    "normal": ("수신 정상", "Receiving"),
    "warning": ("관측 경고", "Observation warning"),
    "stopped": ("정지됨", "Stopped"),
}

EVENTS = {
    "APP_READY": ("프로그램 준비 완료", "Application ready"),
    "DEBUG_LOG_ENABLED": ("개발자 로그 파일 저장 시작", "Developer log file enabled"),
    "DEBUG_LOG_DISABLED": ("개발자 로그 파일 저장 종료", "Developer log file disabled"),
    "DEBUG_LOG_ERROR": ("개발자 로그 파일 오류", "Developer log file error"),
    "SETTINGS_SAVED": ("설정 저장 완료", "Settings saved"),
    "PREFERENCES_SAVED": ("선택한 경로·환경 저장 완료", "Connection and location choices saved"),
    "SETTINGS_ERROR": ("설정 적용 실패", "Settings could not be applied"),
    "TARGET_READY": ("대상 연결 준비 완료", "Target preparation complete"),
    "TARGET_ATTENTION": ("연결 설정 확인 필요", "Connection settings need attention"),
    "TARGET_ERROR": ("대상 연결 오류", "Target preparation error"),
    "SESSION_PREPARING": ("캡처 준비 중", "Preparing capture"),
    "SESSION_STARTING": ("캡처 시작 중", "Starting capture"),
    "SESSION_RECORDING": ("기록 중", "Recording"),
    "SESSION_PARTIAL": ("일부 대상 실패 · 나머지 기록 유지", "Some targets failed · others continue"),
    "SESSION_STOPPING": ("캡처 정지·파일 확인 중", "Stopping capture and checking files"),
    "SESSION_CANCELLED": ("시작 취소 · 번호 예약 전", "Start cancelled before index reservation"),
    "FILE_CHECKING": ("종료 파일 형식·읽기 검사 중", "Checking the closed capture file"),
    "FILE_PUBLISHED": ("캡처 파일 보관 완료", "Capture file saved"),
    "BLF_PUBLISHED": ("BLF 파일 보관 완료", "BLF file saved"),
    "FILE_ERROR": ("파일 검사·보관 실패 · 작업 파일 유지", "File verification or storage failed · working file preserved"),
    "FILE_OPERATION_STARTED": ("파일 처리 중", "Processing capture files"),
    "FILE_OPERATION_COMPLETED": ("파일 처리 완료 · 다음 번호 유지", "File operation completed · index preserved"),
    "FILE_OPERATION_PARTIAL": ("파일 처리 일부 실패 · 파일별 결과 확인", "File operation partial or blocked · review details"),
    "FILE_MANAGEMENT_ERROR": ("파일 관리 오류", "Capture file management error"),
    "FILE_OPERATIONS_RECOVERED": ("중단된 파일 작업 경로 확인 · 이력 검토 필요", "Interrupted file operations reconciled · review history"),
    "OBSERVATION_LOSS": ("패킷 요약 누락 · 관측 확인 필요", "Packet summaries lost · observation unconfirmed"),
    "SESSION_COMPLETED": ("캡처 보관 완료", "Capture completed"),
    "SESSION_FAILED": ("캡처 실패", "Capture failed"),
    "SESSION_INCOMPLETE": ("캡처 미완료 · 상세 확인 필요", "Capture incomplete · review details"),
    "OPERATION_ERROR": ("작업 오류", "Operation error"),
    "ENVIRONMENT_READY": ("환경 확인 완료", "Environment check completed"),
    "NO_TARGETS": ("로깅 대상을 하나 이상 선택하세요.", "Select at least one capture target."),
    "REAL_ADAPTER_UNAVAILABLE": ("실제 장비 연동은 아직 구현되지 않았습니다.",
                                 "Real hardware adapters are not implemented yet."),
    "DEMO_NOTICE": ("모의 데모 · 실제 로그 파일을 만들지 않습니다", "Simulation · no capture files are created"),
}

DEMO_EVENTS = {
    "SESSION_STARTING": ("모의 캡처 시작 중", "Starting simulated capture"),
    "SESSION_RECORDING": ("모의 기록 중 · 실제 파일 미생성", "Simulation running · no capture files created"),
    "SESSION_PARTIAL": ("일부 모의 대상 실패 · 나머지 모의 기록 유지",
                        "Some simulated targets failed · others continue"),
    "SESSION_COMPLETED": ("모의 캡처 종료 · 실제 파일 미생성", "Simulation ended · no capture files created"),
    "SESSION_FAILED": ("모의 캡처 실패 · 실제 파일 미생성", "Simulation failed · no capture files created"),
    "SESSION_INCOMPLETE": ("모의 상태 미확인 · 상세 확인 필요", "Simulation state unconfirmed · review details"),
}


def tr(key: str, language: str = "ko") -> str:
    pair = TEXT.get(key)
    return pair[language == "en"] if pair else key


def render_event(event: AppEvent, language: str, *, include_details: bool = True) -> str:
    """Re-render structured messages on language changes, retaining unknown originals."""
    pair = DEMO_EVENTS.get(event.code) if event.params.get("demo") is True else None
    pair = pair or EVENTS.get(event.code)
    description = pair[language == "en"] if pair else (event.original or event.code)
    if event.code == "FILE_PUBLISHED" and "packets" in event.params:
        count = event.params["packets"]
        description += f" · {count} packets" if language == "en" else f" · {count}패킷"
    if event.code == "BLF_PUBLISHED" and "objects" in event.params:
        count = event.params["objects"]
        description += f" · {count} objects" if language == "en" else f" · {count}객체"
    if event.code.startswith("FILE_OPERATION_") and "kind" in event.params:
        description = tr("file_kind_" + event.params["kind"], language) + " · " + description
    details = " · ".join(f"{key}={value}" for key, value in event.params.items())
    if details and include_details:
        description += " · " + details
    if event.original and event.original != description and event.original != (pair or (None,))[0]:
        if pair:
            original = event.original
            if not include_details:
                original = next((line for line in reversed(original.splitlines()) if line.strip()), "")
                if len(original) > 180:
                    original = original[:177] + "…"
            description += "\n" + original
    try:
        display_time = datetime.fromisoformat(event.timestamp).astimezone().strftime("%H:%M:%S")
    except ValueError:
        display_time = event.timestamp[11:23] or event.timestamp
    target = {"app": "프로그램" if language == "ko" else "App", "can": "CAN", "diag": "Diag", "ethernet": "Zipy"}.get(event.target, event.target)
    return f"{display_time}  {event.level}  {target} · {description}"
