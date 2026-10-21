"""A successful COM connection is distinct from readiness to start a segment."""


def readiness_stage(details):
    if details.get("view_only"):
        return "license_required"
    if not details.get("selected_block") or details.get("selection_error"):
        return "block_required"
    if details.get("hardware", {}).get("status") == "mismatch":
        return "hardware_mismatch"
    if details.get("hardware", {}).get("reference_required") and details["hardware"]["status"] == "unavailable":
        return "hardware_unavailable"
    if not details.get("measurement_running"):
        return "measurement_waiting"
    if details.get("trigger_active"):
        return "block_recording"
    return "segment_ready"


STAGES = {
    "license_required": ("cfg 열림 · 라이선스 필요", "Configuration open · License required", "配置已打开 · 需要许可证"),
    "block_required": ("cfg 열림 · 기록 블록 선택", "Configuration open · Select block", "配置已打开 · 选择记录块"),
    "hardware_mismatch": ("cfg 열림 · 채널 매핑 불일치", "Configuration open · Channel mismatch", "配置已打开 · 通道映射不匹配"),
    "hardware_unavailable": ("cfg 열림 · 기준 채널 확인 불가", "Configuration open · Cannot verify reference", "配置已打开 · 无法验证基准通道"),
    "measurement_waiting": ("cfg 열림 · 측정 시작 대기", "Configuration open · Start measurement", "配置已打开 · 等待开始测量"),
    "block_recording": ("측정 중 · 기존 블록 기록 중", "Measurement running · Block already recording", "正在测量 · 记录块已在记录"),
    "segment_ready": ("측정 중 · 구간 기록 준비", "Measurement running · Ready for segment", "正在测量 · 已准备好分段记录"),
}


def stage_text(stage, language):
    return STAGES.get(stage, ("", "", ""))[{"ko": 0, "en": 1, "zh": 2}.get(language, 0)]


GUIDES = {
    "license_required": (
        "CANoe가 View Only 상태입니다. 시험 PC에서 이 cfg에 필요한 버스 옵션의 라이선스를 확인하세요.",
        "CANoe is in View Only mode. Check the licenses for all bus options required by this cfg on the test PC.",
        "CANoe 处于 View Only 模式。请在测试电脑上检查此 cfg 所需的全部总线选项许可证。"),
    "block_required": (
        "위 목록에서 사용할 BLF 기록 블록을 선택한 뒤 연결 확인을 누르세요.",
        "Select the intended BLF logging block above, then check the connection again.",
        "请在上方选择要使用的 BLF 记录块，然后重新检查连接。"),
    "hardware_mismatch": (
        "저장한 장치·포트 기준과 다릅니다. 아래 채널 정보와 CANoe의 채널 매핑을 확인하세요.",
        "The device/port differs from the saved reference. Review the channels below and CANoe's channel mapping.",
        "设备或端口与已保存的基准不同。请检查下方通道信息和 CANoe 的通道映射。"),
    "hardware_unavailable": (
        "저장한 장치·포트 기준을 확인하지 못했습니다. 아래 채널 정보와 장치 연결을 확인하세요.",
        "The saved device/port reference could not be verified. Review the channels below and the device connection.",
        "无法验证已保存的设备和端口基准。请检查下方通道信息和设备连接。"),
    "measurement_waiting": (
        "AutoLog가 연 이 CANoe 창에서 채널 매핑과 cfg에 필요한 버스 옵션 라이선스를 확인한 뒤 F9로 측정을 시작하세요. "
        "실패하면 CANoe Write 창의 오류를 확인하세요. Trace의 CAN 수신을 확인한 뒤 메인의 기록 시작을 누르세요. 측정 상태는 시작할 때 다시 확인합니다.",
        "In this CANoe window opened by AutoLog, check channel mapping and licenses for the bus options required by the cfg, "
        "then start measurement with F9. If it fails, review CANoe's Write window. Confirm CAN reception in Trace, then press Start recording; measurement is checked automatically.",
        "请在 AutoLog 打开的此 CANoe 窗口中检查通道映射和 cfg 所需的总线选项许可证，然后按 F9 开始测量。"
        "若失败，请查看 CANoe Write 窗口的错误。确认 Trace 中收到 CAN 消息后，点击开始记录；程序会自动检查测量状态。"),
    "block_recording": (
        "선택한 기록 블록이 이미 기록 중입니다. CANoe에서 해당 블록의 기록을 끝낸 뒤 다시 확인하세요.",
        "The selected logging block is already recording. Stop that block in CANoe, then check again.",
        "所选记录块已在记录。请先在 CANoe 中停止该块的记录，然后重新检查。"),
    "segment_ready": (
        "측정 실행과 기록 블록을 확인했습니다. 기록 시작을 누르세요. Trace의 실제 CAN 수신도 확인하세요.",
        "Measurement and logging block found. Press Start recording. Also confirm actual CAN reception in Trace.",
        "已确认测量运行和记录块。请点击开始记录，并确认 Trace 中实际收到 CAN 消息。"),
}


def stage_guidance(stage, language):
    return GUIDES.get(stage, ("", "", ""))[{"ko": 0, "en": 1, "zh": 2}.get(language, 0)]


def option_history_text(diagnostics, language):
    missing = ", ".join(diagnostics.get("missing_options", []))
    if not missing:
        return ""
    return {
        "ko": f"CANoe Write 창의 옵션 누락 기록: {missing}. 이전 측정 시도의 기록일 수 있습니다. 현재 라이선스는 CANoe에서 확인하세요.",
        "en": f"CANoe Write history reports missing options: {missing}. This may be an earlier attempt. Check current licenses in CANoe.",
        "zh": f"CANoe Write 历史记录报告缺少选项：{missing}。这可能是先前测量的记录。请在 CANoe 中检查当前许可证。",
    }.get(language, "")
