# 시험 PC 준비

기준 SW 0.9.21 · 검토 2026-10-25

이 문서는 각 시험 PC에서 필요한 준비와 확인 순서다. PC별 경로·장치·업무 cfg·라이선스 자료는 문서에 저장하지 않는다. 앱 프로필은 설정 데이터이며 이 문서를 읽어 설정하지 않는다.

## 새 PC에서 시작하기

1. 배포 ZIP 전체를 쓰기 가능한 로컬 폴더에 풀고 `One Click Log.exe`를 실행한다. `_internal`·`tools`·문서·라이선스 폴더를 함께 유지한다. 사용자 PC에 Python/Git 설치는 필요 없다.
2. 메인 **사용법** 또는 EXE 옆 `One Click Log_User_Guide.html`을 연다. 인터넷 없이 한국어·영어·중국어로 볼 수 있다. 앱의 별도 환경 확인/설치 실행 창은 현재 제공하지 않는다.
3. Zipy는 Npcap 드라이버를 준비한다. 동봉 `tools/Wireshark/tshark.exe`가 기본이며 별도 Wireshark GUI 설치는 필수가 아니다. 다른 설치본을 쓸 때만 **설정 → Ethernet 연결 → 직접 선택**을 사용하고 같은 폴더의 dumpcap·capinfos도 확인한다.
4. 차량 장비에 연결된 실제 NIC를 이름·안정 식별자·포트로 확인하고 선택·연결 확인한다. 그래프는 어댑터 전체 트래픽이며 필수 차량 수신의 증거가 아니다. 사라진 NIC는 다른 항목으로 자동 대체하지 않는다.
5. CAN·Diag는 서로 다른 cfg와 BLF 블록 하나씩 연결한다. 전용 CANoe에서 컴파일·버스 옵션 라이선스·채널 매핑·F9·Trace를 확인한다. 같은 cfg·블록이면 F9 뒤 연결 확인을 반복할 필요는 없다.
6. 저장 폴더·prefix·번호와 실제 Zipy 규칙을 적용한다. 먼저 60초 단독·조합 기록을 보관하고 외부 reader에서 읽은 뒤 장시간으로 확장한다. [실차 TC](../testing/vehicle_test_plan.md)를 사용한다.

## PC별 확인 항목

| 항목 | 남길 정보와 판정 |
| --- | --- |
| OS·앱 | Windows 11 x64 빌드, 실제 EXE 버전·빌드 ID·배포 해시 |
| CANoe | 실행 버전·SP·옵션 라이선스·COM 등록·독립 창/cfg 대응 |
| CAN·Diag | cfg 별칭·BLF 블록·채널·DBC·ECU 버전·실제 수신 |
| Vector | 장비 별칭·드라이버·논리 CAN 번호와 물리 포트 대응. 조회 불가는 정상으로 단정하지 않음 |
| Zipy | 도구 버전·Npcap·NIC 식별자/포트·pcap 또는 pcapng |
| 규칙 | Source·평균 pps·유예·미수신·팝업. 기본 02:00:00·2초/2초·100pps |
| 저장 | 로컬 폴더·쓰기·여유·예상 속도·고유 prefix·다음 번호 |
| 결과 | 실제 기록 구간·파일별 읽기·누락 비교·정지/보관 시간·오류 |

CANoe가 열리지 않으면 사용할 버전의 공식 `Exec64/RegisterComponents.exe` 등록 복구 안내를 따른다. 앱은 COM 등록을 자동 수정하지 않는다. CAPL `.cbf` 쓰기 오류는 [컴파일 쓰기 거부](canoe_capl_compile_troubleshooting.md)를 확인한다. 기존 정책/도구를 임의 재설치하거나 보안 보호를 끄지 않는다.

## 저장과 종료

설정·번호·이력은 `%LOCALAPPDATA%\One Click Log`에 저장하며 이전 AutoLog/Auto_Log/VILLogging 프로필은 새 프로필이 없을 때 이행한다. 새 배포 폴더를 사용해도 PC별 설정·번호를 배포 파일로 덮어쓰지 않는다. 새 PC에서 다른 PC의 경로/NIC를 그대로 사용할 수 있다고 가정하지 않는다.

정상 파일은 **메인 정지·보관**으로 저장한다. X는 이번 실행의 전용 CANoe까지 종료하고 미완료 구간을 폐기하며 완료 파일·번호는 유지한다. 저장할 사용자 cfg 변경은 CANoe에서 직접 저장한다.

실제 수신/무손실·새 PC 설치·대표 부하·장시간은 [검증표](../testing/canoe_support_matrix.md)의 해당 버전·조합으로 확인한다. 오류 직후 TC 결과·ZIP·필요 원본을 [진단 안내](diagnostics.md)에 따라 보존한다.
