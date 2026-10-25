# 현재 구현과 남은 확인

기준 SW 0.9.22 · 코드/기존 근거 검토 2026-10-25

구현 여부, 자동 검사, 이전 현장 확인, 현재 버전의 실차 검증을 구분한다. 검증 숫자는 해당 실행 시점 기록으로 남기며 새 검사 결과 없이 과거 숫자를 현재 결과로 치환하지 않는다.

## 구현 범위

| 영역 | 현재 동작 | 주요 구현과 검사 |
| --- | --- | --- |
| 준비 UI | 설정/연결 부족 안내·F9 측정 재확인·상태별 시작/정지 | ui/capture_button.py, tests/unit/test_readiness.py |
| CAN·Diag | 독립 cfg/BLF 블록·수동 측정 유지·원본 cfg 무저장 | adapters/canoe.py, tests/unit/test_canoe_capture.py |
| 초기설정 | 배포 Initial_Setup.bat로 CANoe 19 COM 등록·Npcap 관리자 설치 | tools/Initial_Setup.bat, tests/unit/test_canoe_registration_helper.py |
| COM 진단 | 독립 모드 준비·등록 누락/손상과 복구 도구 안내 | diagnostics/canoe_setup.py, tests/unit/test_canoe_registration.py |
| 채널 기준 | 읽을 수 있는 로컬 시리얼/포트 기준 비교 | diagnostics/canoe_hardware.py, tests/unit/test_improvements.py |
| Zipy 기록 | dumpcap 원본·TShark 후행 해석·pcap/pcapng·64 MiB 버퍼·정지 후 ZIP 선택 | adapters/tshark.py, tests/unit/test_tshark_capture.py |
| Zipy 수신 기준 | 기본 02:00:00·2초/2초·100pps, 규칙 수정/삭제/복원 | monitors/, tests/unit/test_zipy_default_restore.py |
| 이상 처리 | 오류·단절·확인된 규칙 위반 시 전체 정지·파일별 보관 | runtime.py, tests/unit/test_capture_safety.py |
| 파일과 번호 | 영구 예약·충돌 방지·완결·이름 변경·직전 삭제·중단 폐기 | storage/, tests/integration/test_file_management.py |
| X·재실행 | 전용 도구/CANoe 종료·미완료 폐기·완료/번호 보존 | exit_guard.py, tests/integration/test_force_exit.py |
| 진단 | 상시 JSONL·약 25 MiB 순환·바탕화면 ZIP 스냅샷 | diagnostics/debug_log.py, tests/unit/test_debug_log.py |
| 가이드/배포 | 세 언어 오프라인 사진·버전/해시 검증·동봉 도구 | documentation.py, tests/unit/test_release_documentation.py |

위 구현 경로는 `src/vil_logging/`, 검사 경로는 저장소 루트 기준이다. 전체 구조는 [설계](architecture.md), 완료 기준은 [요구사항 55개](requirements.md)를 따른다.

## 확인된 실제 근거

- 0.9.9에서 조합별 9구간·세 대상 연속 3회 보관을 확인했다. 뒤 구간의 AppHang/재실행 문제는 별도 실패로 남겼다. [0.9.10 분석](../updates/capture_fixes_0_9_10.md).
- 0.9.10의 현장 4구간 보관과 이후 AppHang/미완료 이력 근거가 있다. [종료 정책 변경 근거](../updates/shutdown_policy_0_9_11.md).
- 0.9.16 제공 Diag BLF 두 건에서 진단 요청/응답을 확인했다. 한 표본은 동시 CAN 대비 약 39ms·155프레임 누락, 다른 표본은 비교 구간 내 누락 0이다. [분석](../analysis/diag_log_analysis_2026_10_23.md).
- 0.9.21에서 실제 CANoe 19 등록 복구와 별도 COM 창 두 개 생성/종료를 확인했다. 해당 확인은 업무 cfg 측정·차량 취득 성공이 아니다. [등록 복구 근거](../updates/canoe_registration_0_9_21.md).

현재 버전의 시험 조합·최장 시간·최대 파일·무손실은 위 사실만으로 자동 승계하지 않는다. [환경별 표](../testing/canoe_support_matrix.md)에 버전과 수행 범위를 남긴다.

## 미지원과 미검증

| 항목 | 현재 상태와 다음 확인 |
| --- | --- |
| CAN·Diag 실제 프레임/신호 미수신 자동 감지 | 미지원. CANoe 측정·trigger 정상이어도 무수신일 수 있어 Trace/원본 필요 |
| 0.9.16 Diag 프레임 누락 원인 | 미확정. 동일 버스 매핑·공통 구간·시간차 보정·기준 logger로 TC-20 수행 |
| 실제 VN/채널·물리 링크 분리·새 PC/다른 CANoe 조합 | 현장별 재시험 필요. localhost·대역 검사로 대체하지 않음 |
| 실차 60분·1 GiB 초과·대표 부하의 무손실/자원 상한 | 별도 실측 필요. TC-41의 시간·용량·원본 확인을 개별 판정 |
| 모든 과거 파일 검색·페이지 이동 UI | 미구현. 직전 작업·최근 읽기 전용 이력과 구분 |
| ZIP의 별도 환경/DB/원본 캡처 자동 첨부 | 미구현. 운영 진단·manifest만 자동 포함 |
| 정확한 동시 취득/시간 동기화 | 보장하지 않음. 실제 파일의 공통 구간을 확인 |

## 다음 시험

정차에서 단독 → 7조합 → 측정 유지 10회 → 진단 왕복/누락 비교 → 안전한 이상 처리 → 종료/재실행 → 장시간 순서로 [48 TC](../testing/vehicle_test_plan.md)를 수행한다. 결과 JSON·오류 직후 ZIP·관련 원본을 함께 남기며 아직 미실행인 항목을 통과로 채우지 않는다.

이번 문서/폴더 정리는 앱의 취득·정지 정책 변경이 아니다. 현재 코드에서 참조되는 모듈·검증/복구 경로는 유지하고, 제거된 화면의 미사용 문구·중복 안내·옛 시안만 정리한다.
