# 문서 목차

기준 SW **0.9.23** · 검토 **2026-10-25**

현재 동작은 아래 운영·설계·검증 문서를 기준으로 확인합니다. 버전별 수정과 초기 계획은 별도 폴더에 보관하며, 과거 시험 통과를 새 버전 실차 성공으로 승계하지 않습니다.

| 폴더 | 목적 | 시작 문서 |
| --- | --- | --- |
| reference | 현재 요구사항·구조·제어 정책·구현 범위 | [현재 구현 상태](reference/implementation_status.md), [요구사항](reference/requirements.md), [구조](reference/architecture.md), [제어 정책](reference/control_policy.md), [프로젝트 트리](reference/project_structure.md) |
| guides | 새 PC 준비·진단 보관·환경 오류 조치 | [시험 PC 준비](guides/test_pc_setup.md), [버그리포트](guides/diagnostics.md), [CANoe 19 등록 BAT](guides/canoe_registration_helper.md), [CAPL 쓰기 오류](guides/canoe_capl_compile_troubleshooting.md), [내부 Npcap 동봉](guides/npcap_internal_installer.md) |
| testing | 자동 검사·실차 TC·환경별 결과 구분 | [검증 계획](testing/validation_plan.md), [CANoe 준비](testing/licensed_canoe_validation.md), [환경별 검증표](testing/canoe_support_matrix.md) |
| testing | 실차 48 TC와 회차 기록 | [입력형 HTML](testing/One_Click_Log_Vehicle_Test_Plan.html), [Markdown 원본](testing/vehicle_test_plan.md), [텍스트 결과 양식](testing/vehicle_test_result_template.md) |
| updates | 버전별 변경·해당 시점의 배포/검증 근거 | [업데이트 목록](updates/README.md) |
| analysis | 제공 캡처와 환경 문제의 분석 근거 | [Diag 누락 분석](analysis/diag_log_analysis_2026_10_23.md), [BLF 시그널 확인](analysis/blf_replay_analysis_2026_10_22.md), [초기 cfg 호환성](analysis/cfg_compatibility_review.md) |
| archive | 초기 계획·설치 후보 조사·개발 단계 기록 | [과거 기록 안내](archive/README.md) |
| presentation | 발표 구성과 성과 측정 양식 | [발표 자료 안내](presentation/README.md) |

배포 사용자에게 제공하는 공식 가이드는 저장소 루트 [user_guide](../user_guide/README.md)에서 관리합니다. 소스·의존성·빌드·Git 작업은 [개발 안내](../CONTRIBUTING.md)를 따릅니다. 문서 생성·링크 검사 도구는 `tools`에 있습니다.

## 새 기록을 추가할 때

제품 변경은 현재 기준 문서와 사용자 가이드를 먼저 반영하고 `updates`에 버전별 검증 근거를 남깁니다. 과거 내용을 현재 기준처럼 문서 맨 위에 계속 누적하지 않습니다. 문서를 옮기거나 지우면 링크·실행 예제·생성 도구 경로도 고치고 `tools/check_docs.py`를 실행합니다.

실제 차량 캡처·진단 ZIP·업무 cfg·사용자 DB·장치 시리얼·개인 경로는 승인된 로컬 자료 위치에 보관하며 이 목차 아래에 추가하지 않습니다. 입력형 시험서의 결과 JSON도 별도 보관합니다.
