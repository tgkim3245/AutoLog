# AutoLog 0.9.6 — 출력 자동 번호 복구와 강제 종료

2026-10-21. 새 현장 리포트와 실제 파일을 대조했다. 원본 캡처·cfg·개인 경로는 Git에서 제외한다.

## 확인한 원인과 실제 파일

리포트 JSONL은 550건, 591,442바이트, SHA256 `d9ffb46643fb2768ba65e893b4aa5ce28773ae92de3f140d623f5bb5c2e6a56b`이며 ZIP CRC와 manifest 크기/해시가 일치했다. 앞선 View Only 시도와 뒤의 측정/실제 기록 성공은 구분했다.

- CAN+Zipy는 실제 시작했다. CAN 정지는 약 69ms에 trigger 비활성까지 확인했다.
- 원래 경로 복구 후 `IncrementAfterTrigger=True`를 복구하는 과정에서 CANoe의 출력명이 같은 원래 이름의 `_T001.blf`로 변했다. AutoLog는 이를 외부 경로 수정으로 오인해 약 175ms 만에 정지 확인을 중단했다. 복구·다음 시작·X 종료가 같은 미완료 상태에 묶였다.
- 당시 독점 파일 접근도 WinError 32였으므로 trigger 비활성만으로 파일 닫힘을 단정하지 않는다. 경로 오인 판정을 수정한 뒤에도 실제 파일 닫힘 검사는 유지한다.
- 실제 BLF는 970,316바이트, 전체 컨테이너/압축 검사 후 Python CAN 리더로 CAN/CAN FD 프레임 30,787개·약 7.230초·채널 2개를 읽었다. 헤더 선언 object 수와 구조 검사 수는 3개 차이가 나며 리더의 비-CAN header version 경고 2개도 관측했다. 구조/프레임 확인과 모든 메시지의 무손실 보장은 구분한다.
- PCAP은 14,547,013바이트, capinfos 전체 읽기로 9,597패킷·약 7.409초를 확인했다. 화면 표시 큐 누락과 원본 PCAP 손실은 구분한다.
- 현장 AutoLog 본체 1개와 정확한 자식 worker 2개만 확인 후 종료하고, 외부 CANoe 창·측정은 유지했다. 실제 BLF를 기존 RecoveryService로 저장 폴더에 복구하고 원문 SHA256 `721ce955d483ac31891603b71b630295f753a3f3ff19367209792dd275324a22` 일치를 확인했다. DB를 사전 백업하고 해당 세션만 수동 검토 완료(실패 이력 보존) 처리했으며 다음 번호 667과 PCAP은 유지했다.

## CANoe 수정

파일 옵션을 먼저 복구하고 원래 파일명을 적용한다. 우리 출력 복구를 시작한 비활성 블록에서만, 같은 cfg·블록 구성/이름·같은 원래 폴더·같은 BLF 기본 이름·원래 trigger 증가 옵션에 한해 `_T<숫자>` 정규화를 인정한다. 지연된 COM 반영도 다음 검증에서 수용하고 실제 관측 경로를 선택 기준에 반영한다. 복구 전 외부 경로 변경·다른 폴더·다른 블록·활성 수동 기록은 계속 거부한다.

정상 출력 확인과 실제 파일 닫힘은 별개다. 독점 접근·구조 검사를 생략하거나 파일 잠금을 강제로 해제하지 않는다. 지연된 번호 적용과 파일 핸들 보유를 함께 재현해 3회 연속 구간을 검사했다. 실제 CANoe에서 정상 종료·다음 구간까지 완료되는지 현장 재시험은 필요하다.

참고: Vector 공식 [파일명 옵션](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/COMInterface/Objects/COMObjectLoggingFileNameOptions.htm), [Logging](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/COMInterface/Objects/COMObjectLogging.htm), [Trigger](https://help.vector.com/CANoeDEFamily/19/en/Help/Content/Topics/COMInterface/Objects/COMObjectTrigger.htm). 이 문서의 `_T001` 변환은 공식 문서만의 추정이 아니라 현장 COM 관측 근거다.

## X 종료 정책

사용자가 진행 중이어도 X로 항상 종료하라고 명시했다. X는 정상 정리를 요청하되 실패하면 즉시, 약 3초가 지나도 끝나지 않으면 강제 종료한다. 두 번째 X는 즉시 강제 종료한다. 별도 감시 스레드는 coordinator·DB·COM·로그 정리와 독립적이고, 강제 정리 자체도 0.5초 뒤 최종 프로세스 종료 제한을 둔다.

강제 종료는 추적된 worker 핸들과 Ethernet Windows Job의 dumpcap/해석 자식만 종료한다. 프로세스 이름 전체나 무관한 앱은 종료하지 않는다. 외부 CANoe 서버는 해당 Job 밖에 있으며 사용자 창·측정은 유지한다. 캡처·임시 파일은 삭제하거나 성공으로 승격하지 않는다. 강제 종료 사유/세션/파일 경로의 작은 notice를 남기고 다음 실행에서 진단 이력에 반영한다. SQLite의 예약·진행 상태는 기존 미완료 복구로 회수한다.

실착 재시험: CAN+Zipy 3구간의 시작→정지→파일 보관→다음 시작, 원래 옵션과 CANoe 자동 번호, 실제 BLF 프레임/PCAP 패킷을 확인한다. 강제 종료는 파일 완결을 보장하지 않으므로 별도 짧은 시험에서 X와 재실행의 미완료 상태·파일 보존을 확인한다.

소스 전체 자동 검사 527개(56.14초)를 통과했다. 새 검사는 지연된 자동 번호 2가지의 3회 연속 구간·복구 전 외부 번호 거부, 독립 종료 감시 3가지, 실제 별도 앱 프로세스의 초기화/기록 정지/진단 정체와 반복 X 종료 4가지, 소유 job 종료/이미 사라진 job 처리 2가지를 포함한다. 기록 중 강제 종료 후 같은 프로필의 재실행·미완료 보존·notice 회수도 확인했다.

## 배포 검증

- 깨끗한 소스 `ed65b19b40c607e7edff7bb7d6f51d9d779359b3`에서 `AutoLog-0.9.6_20261021_180128`을 빌드했다. ZIP 52,960,708바이트, SHA256 `228daf49bf2749c757d2eef4be9aca5c46fd2bfb70867c00a8b6e3bcf7dcf745`. EXE SHA256 `a2325cdca0f78e3d41c98069cf8ad1da8c5bde9ef4df96b9869ef0943f26d3b2`.
- 압축 해제 EXE의 CRC/해시/버전, 중국어 설정·실제 메인 버튼을 통한 모의 시작/정지·완료 표시·X 정상 종료·NIC 조회와 오류 없는 진단 101개를 확인했다. EXE에서 추출한 CAN 복구/파일 닫힘 대역 4개와 ExitGuard 3개를 개발 Python에서 통과했다.
- 같은 EXE의 실제 localhost PCAP/PCAPNG 각 0패킷·5패킷·재시작 6구간과 오프라인 ARP를 확인했다. 실제 CANoe 장비의 새 구간 시험은 수행하지 않았다.
- 가이드 2026-10-21.3을 8개 뷰포트로 렌더링했다. HTML 25,718바이트·START_HERE 3,783바이트의 ZIP/EXE 폴더/압축 해제본/미리보기와 build_info 개정·크기·해시가 일치한다. Ruff·의존성·diff 검사를 통과했다.
- 최종 빌드 폴더의 `verification/result.json`, `verification/frozen-core/result.json`, `verification/ethernet/result.json`, `documentation_verification.json`에 근거를 남겼다. 실제 캡처 복구 근거와 사전 DB 백업은 로컬 빌드 저장소의 `field-recovery-0.9.6/`에 보관하고 Git에는 포함하지 않는다.
