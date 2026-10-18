"""Read-only Ethernet acquisition evidence, with explicit limits and freshness."""

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QPushButton, QVBoxLayout

from .theme import apply_theme, refresh_style


def quantity(value, *, rate=False):
    if value is None:
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:,.1f} {unit}" + ("/s" if rate else "")
        value /= 1024


class QualityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.report = {}
        self.language = "ko"
        self.setObjectName("captureQualityDialog")
        self.setMinimumWidth(540)
        apply_theme(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(14)
        self.heading = QLabel()
        self.heading.setProperty("variant", "title")
        outer.addWidget(self.heading)
        self.status = QLabel()
        self.status.setProperty("variant", "status")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        form = QFormLayout()
        form.setSpacing(11)
        self.labels, self.values = {}, {}
        for key in ("elapsed", "size", "growth", "parsed", "delay", "display", "errors", "free", "buffer", "counts", "loss"):
            self.labels[key], self.values[key] = QLabel(), QLabel()
            self.values[key].setWordWrap(True)
            form.addRow(self.labels[key], self.values[key])
        outer.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty("variant", "helper")
        outer.addWidget(self.note)
        self.path = QLabel()
        self.path.setWordWrap(True)
        self.path.setProperty("variant", "helper")
        outer.addWidget(self.path)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        outer.addWidget(self.close_button)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.render)
        self.timer.start()
        self.render()

    def set_report(self, report):
        self.report = report or {}
        self.render()

    def set_language(self, language):
        self.language = language
        self.render()

    def render(self):
        ko = self.language != "en"
        title = "Ethernet 기록 품질" if ko else "Ethernet capture quality"
        self.setWindowTitle(title)
        self.heading.setText(title)
        self.close_button.setText("닫기" if ko else "Close")
        names = {
            "elapsed": ("기록 시간", "Recording duration"), "size": ("파일 크기", "File size"),
            "growth": ("파일 증가 속도", "File growth"), "parsed": ("요약 해석 속도", "Summary decoding"),
            "delay": ("해석 지연 · 현재 / 최대", "Decode delay · last / max"),
            "display": ("화면 큐 누락", "Display queue drops"), "errors": ("해석 / 읽기 오류", "Decode / reader errors"),
            "free": ("저장 공간 여유", "Free disk space"), "buffer": ("요청한 캡처 버퍼", "Requested capture buffer"),
            "counts": ("파일 / 해석 패킷 수", "File / decoded packets"),
            "loss": ("드라이버 / OS 누락", "Driver / OS drops"),
        }
        for key, texts in names.items():
            self.labels[key].setText(texts[0 if ko else 1])
            self.values[key].setText("—")
        report, metrics = self.report, self.report.get("metrics", {})
        state = report.get("state")
        stale = state == "recording" and time.time() - (report.get("sampled_epoch") or 0) > 6
        tone = "neutral"
        text = "아직 Ethernet 기록이 없습니다." if ko else "No Ethernet capture yet."
        if state:
            text = ({"recording": "기록 중 · 최근 관측값", "archived": "보관 완료 · 종료 시 관측값",
                     "historical": "이전 실행의 종료 기록", "unknown": "기록 상태 확인 필요 · 마지막 관측값"}
                    if ko else {"recording": "Recording · latest sample", "archived": "Archived · final sample",
                                "historical": "Previous run · final sample", "unknown": "State unknown · last sample"}).get(state, state)
            tone = "ready" if state in {"recording", "archived"} else "neutral"
        if stale:
            text, tone = ("갱신 지연 · 마지막 관측값" if ko else "Updates delayed · last sample"), "attention"
        loss = report.get("capture_loss", {})
        mismatch = report.get("summary_consistency") and not report["summary_consistency"].get("same_count")
        if metrics.get("low_space") or loss.get("status") == "loss_reported" or metrics.get("error") or state == "unknown":
            tone = "attention"
        if loss.get("status") == "loss_reported":
            text += " · 원본 누락 보고됨" if ko else " · packet drops reported"
        if mismatch:
            text += " · 패킷 수 차이" if ko else " · packet counts differ"
            tone = "attention"
        self.status.setText(text)
        self.status.setProperty("tone", tone)
        refresh_style(self.status)
        if report:
            elapsed = metrics.get("elapsed_seconds")
            self.values["elapsed"].setText(f"{elapsed:,.1f} s" if elapsed is not None else "—")
            self.values["size"].setText(quantity(metrics.get("file_bytes")))
            self.values["growth"].setText(quantity(metrics.get("file_growth_bps"), rate=True))
            pps = metrics.get("parsed_pps")
            self.values["parsed"].setText(f"{pps:,.0f} packets/s" if pps is not None else "—")
            delays = [metrics.get(key) for key in ("last_processing_delay_ms", "max_processing_delay_ms")]
            self.values["delay"].setText(" / ".join(f"{value:,.1f}" if value is not None else "—" for value in delays) + " ms")
            self.values["display"].setText(f"{report.get('display_drops', 0):,}")
            self.values["errors"].setText(f"{report.get('parse_errors', 0):,} / {len(report.get('reader_errors', []))}")
            self.values["free"].setText(quantity(metrics.get("disk_free_bytes")) +
                (" · 1 GiB 이하" if ko else " · ≤1 GiB") if metrics.get("low_space") else quantity(metrics.get("disk_free_bytes")))
            buffer = report.get("binding", {}).get("requested_buffer_mib")
            self.values["buffer"].setText(f"{buffer} MiB" if buffer is not None else "—")
            count = report.get("packet_count")
            self.values["counts"].setText((f"{count:,}" if count is not None else "—") + f" / {report.get('parsed_packets', 0):,}")
            unknown = "확인 불가" if ko else "Unknown"
            self.values["loss"].setText(" / ".join(f"{loss[key]:,}" if loss.get(key) is not None else unknown
                                                       for key in ("driver_dropped", "os_dropped")))
        notes = [
            "파일 크기·속도는 주기 관측값입니다. 해석 속도는 수신 회선 속도와 다르며, 해석 지연에는 시계 오차가 포함됩니다. "
            "화면 큐 누락은 화면용 요약 누락입니다. 원본 누락은 종료 파일이 제공한 선택 통계만 표시하며, 확인 불가를 0으로 간주하지 않습니다. "
            "패킷 수가 같거나 파일 보관이 완료되어도 전체 무손실을 보장하지 않습니다.",
            "Size and rates are sampled. Decode rate is not wire rate; delay includes clock error. Display drops affect summaries. "
            "Original drops use optional counters from the closed file; unknown does not mean zero. Equal counts or successful archival do not prove lossless capture.",
        ]
        text = notes[0 if ko else 1]
        if report.get("error") or metrics.get("error"):
            text += "\n" + str(report.get("error") or metrics["error"])
        if metrics.get("low_space"):
            text += "\n" + ("저장 공간이 부족합니다. 저장 위치를 확인하세요." if ko else "Low disk space. Check the output location.")
        self.note.setText(text)
        self.path.setText(report.get("path", ""))
