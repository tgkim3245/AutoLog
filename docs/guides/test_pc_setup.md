# 시험 PC 준비

기준 SW 1.0.1 · 검토 2026-10-26

이 문서는 각 시험 PC에서 필요한 준비와 확인 순서다. PC별 경로·장치·업무 cfg·라이선스 자료는 문서에 저장하지 않는다. 앱 프로필은 설정 데이터이며 이 문서를 읽어 설정하지 않는다.

## 새 PC에서 시작하기

1. CAN·Diag는 **RBS 구성(.cfg)의 작성·검증 버전에 맞는 CANoe를 선택한다.** 해당 프로그램·측정 라이선스·Vector 장비/드라이버와 업무 cfg 전체를 먼저 준비한다.
2. 배포 ZIP 전체를 쓰기 가능한 로컬 폴더에 푼다. `_internal`·`tools`·문서·라이선스 폴더를 함께 유지한다. 사용자 PC에 Python/Git 설치는 필요 없다.
3. 앱과 모든 CANoe 작업을 저장·종료하고 EXE 옆 **Initial_Setup.bat**를 더블클릭한다. 공식 도구의 Windows 관리자 요청을 승인한다. BAT에서 검색된 64비트 CANoe의 버전·경로를 확인하고 사용할 목록 번호를 입력한다. 하나만 있어도 직접 선택한다. BAT는 선택한 설치본을 기본 COM 대상으로 등록하고, Npcap이 있으면 건너뛰며 없으면 내부 동봉 설치기를 관리자 실행한다. 공식 라이선스/옵션을 확인하고 재부팅 요청 시 재부팅한 뒤 BAT를 다시 실행한다. [초기설정 상세](canoe_registration_helper.md)를 따른다.
4. 사용할 기능의 단계 결과(CAN·Diag: CANoe: 0, Zipy: Npcap: 0)를 확인하고 `One Click Log.exe`를 실행한다. 메인 **사용법** 또는 EXE 옆 HTML에서 첫 화면 **0. 초기설정**과 이후 5단계를 확인한다. 일반 배포에 없는 Npcap 설치기는 별도로 준비한다.
5. Zipy는 동봉 `tools/Wireshark/tshark.exe`가 기본이며 별도 Wireshark GUI 설치는 필수가 아니다. 다른 설치본이 필요할 때만 **설정 → Ethernet 연결 → 직접 선택**으로 같은 폴더의 dumpcap·capinfos까지 확인한다. 차량에 연결된 실제 NIC를 이름·안정 식별자·포트로 확인하고 선택·연결 확인한다. 그래프는 어댑터 전체 트래픽이며 차량 수신의 증거가 아니다.
6. CAN·Diag는 서로 다른 cfg와 BLF 블록 하나씩 연결한다. 선택한 전용 CANoe에서 컴파일·버스 옵션 라이선스·채널 매핑·F9·Trace를 확인한다. 같은 cfg·블록이면 F9 뒤 연결 확인을 반복할 필요는 없다.
7. 저장 폴더·prefix·번호와 실제 Zipy 규칙을 적용한다. 먼저 60초 단독·조합 기록을 보관하고 외부 reader에서 읽은 뒤 장시간으로 확장한다. [실차 TC](../testing/vehicle_test_plan.md)를 사용한다.

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

CANoe가 열리지 않으면 선택한 CANoe의 공식 `Exec64/RegisterComponents.exe` 등록 복구 안내를 따른다. 앱은 COM 등록을 자동 수정하지 않는다. CAPL `.cbf` 쓰기 오류는 [컴파일 쓰기 거부](canoe_capl_compile_troubleshooting.md)를 확인한다. 기존 정책/도구를 임의 재설치하거나 보안 보호를 끄지 않는다. EXE 옆 [초기설정 BAT](canoe_registration_helper.md)는 설치 CANoe 버전 선택 후 공식 등록과 Npcap 관리자 설치를 통합한다. 앱·CANoe 작업을 저장·종료하고 실행한다. 이미 있는 Npcap은 건너뛰며, 일반 배포에는 설치 파일이 없어 별도 준비한다.

## 저장과 종료

설정·번호·이력은 `%LOCALAPPDATA%\One Click Log`에 저장하며 이전 AutoLog/Auto_Log/VILLogging 프로필은 새 프로필이 없을 때 이행한다. 새 배포 폴더를 사용해도 PC별 설정·번호를 배포 파일로 덮어쓰지 않는다. 새 PC에서 다른 PC의 경로/NIC를 그대로 사용할 수 있다고 가정하지 않는다.

정상 파일은 **메인 정지·보관**으로 저장한다. X는 이번 실행의 전용 CANoe까지 종료하고 미완료 구간을 폐기하며 완료 파일·번호는 유지한다. 저장할 사용자 cfg 변경은 CANoe에서 직접 저장한다.

실제 수신/무손실·새 PC 설치·대표 부하·장시간은 [검증표](../testing/canoe_support_matrix.md)의 해당 버전·조합으로 확인한다. 오류 직후 TC 결과·ZIP·필요 원본을 [진단 안내](diagnostics.md)에 따라 보존한다.
