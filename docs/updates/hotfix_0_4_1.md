# 0.4.1 — X 종료와 파일명 규칙

> 과거 기록: 이 문서는 작성 당시의 변경·검증 근거를 보존합니다. 현재 동작과 남은 확인 사항은 [현재 구현 상태](../reference/implementation_status.md)를 따릅니다.

2026-10-18 · VIL Logging 0.4.1

[실행 파일](../../outputs/hotfix-0.4.1/VILLogging/VILLogging.exe). 0.4.0 앱을 업데이트한다면 **설정 → 프로그램 종료**를 사용한다. 0.4.1부터는 X가 정상 종료한다. 실행 파일과 `_internal` 폴더를 함께 유지한다. 사용자 설정·번호 DB는 로컬 앱 데이터에 보존된다.

## 변경 사항

- 메인 창의 X와 **프로그램 종료**가 같은 정상 종료를 실행한다. 기록 중이면 정지와 파일 확인을 마친 뒤 앱을 종료한다. 정지나 파일 확인이 완료되지 않으면 창과 오류 상태를 유지한다. CANoe 측정은 종료하지 않는다.
- 새 기록 prefix가 `VIL`이면 `VIL_7.blf`, `VIL_Diag_7.blf`, `VIL_7.pcap` 형식으로 저장한다. 입력값이 이미 `_`로 끝나면 구분자를 중복하지 않는다. 새 설치의 기본 prefix는 `VIL`이다. 기존에 저장한 설정과 이미 만든 파일명은 바꾸지 않는다.
- 직전 기록 이름 변경 입력값은 인덱스 없이 그대로 기본 파일명으로 쓴다. 예를 들어 `Road test`는 `Road test.blf` 또는 `Road test.pcap`이 된다. 확장자와 폴더는 유지한다. CAN과 Diag를 함께 기록한 경우 이름 충돌을 막기 위해 Diag에만 `_Diag`가 붙는다. 다음 기록 번호와 새 기록 prefix는 바뀌지 않는다.

## 검증

- 기본 자동 검사 202개, Ruff, 의존성 검사를 통과했다.
- Windows 배타 파일 작업 검증 5개를 통과했다. 직전 파일을 인덱스 없이 `renamed.pcap`으로 바꾸고 재실행 후 경로·다음 번호를 보존하는 것을 확인했다.
- 빌드된 폴더 EXE에서 localhost UDP/오프라인 ARP 검증 6개 캡처 세션과 파일 검증 5개가 통과했다. 물리 차량 NIC는 열지 않았다.
- 소스 UI에서 loopback 패킷 8개 표시, `UI_renamed.pcap` 변경, 삭제 취소/확정, 번호 유지, 종료를 확인했다.
- 배포 EXE 전체 폴더 크기·해시와 검사 결과는 [빌드 정보](../../outputs/hotfix-0.4.1/VILLogging/build_info.json), [Ethernet 검증](../../outputs/hotfix-0.4.1/ethernet_verification.json), [파일 검증](../../outputs/hotfix-0.4.1/file_verification.json), [UI 검증](../../outputs/hotfix-0.4.1/ui_result.json)에 기록한다.

고속·장시간 취득, 시험 PC의 차량 NIC, 실제 CANoe BLF 기록은 이 변경의 검증 범위가 아니다.
