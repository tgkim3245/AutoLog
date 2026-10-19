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
