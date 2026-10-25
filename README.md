# One Click Log

Windows 11 x64에서 CANoe의 CAN·Diag BLF와 Zipy Ethernet 캡처를 제어하는 로컬 앱입니다. 현재 소스 버전은 **1.0.0**입니다. 배포 EXE 옆 Initial_Setup.bat에서 설치 CANoe 검색·버전 선택 후 COM 등록과 Npcap 관리자 설치를 진행합니다. Ethernet 설정에서 원본/정지 후 ZIP 보관을 선택합니다. 문서 검토일은 **2026-10-25**이며 문서 정리만으로 실차 검증 범위를 확대하지 않습니다.

배포 사용자는 EXE 옆 `START_HERE.txt`와 `One Click Log_User_Guide.html`, 또는 메인 상단 **사용법**을 먼저 읽으세요. 개발 문서는 [문서 목차](docs/README.md), 환경별 실제 확인 범위는 [검증표](docs/testing/canoe_support_matrix.md)에 있습니다.

## 기본 사용

1. 배포 ZIP 전체를 로컬 폴더에 풀고 앱/모든 CANoe를 저장·종료한 뒤 **Initial_Setup.bat**를 실행합니다. CANoe 설치본을 선택하면 COM 등록과 Npcap 준비를 함께 진행합니다. Npcap이 없으면 동봉 설치기를 자동 관리자 실행하며 권한 승인·설치창 동의는 사용자가 합니다. 결과 확인 후 `One Click Log.exe`를 실행합니다. 동봉 폴더를 함께 유지합니다.
2. 설정에서 저장 폴더·prefix·다음 번호를 적용하고 사용할 대상만 선택합니다. 기본 선택은 CAN·Zipy입니다.
3. CAN·Diag는 서로 다른 cfg와 BLF 블록 하나씩 연결합니다. 전용 CANoe에서 라이선스·컴파일·채널 매핑과 **F9 측정·Trace 수신**을 확인합니다. 같은 cfg·블록이면 측정 후 연결 확인을 반복할 필요는 없습니다.
4. Zipy는 동봉 TShark와 실제 캡처 NIC를 확인합니다. Npcap은 초기설정 BAT가 설치 또는 기설치 상태를 확인합니다. Wireshark GUI 별도 설치는 캡처 실행의 필수 조건이 아닙니다.
5. 메인의 상태별 **기록 시작·정지** 버튼으로 구간을 제어하고 보관 결과를 확인합니다. 정상 정지는 CANoe 측정·다른 블록을 유지합니다.

CAN은 `prefix_N.blf`, Diag는 `prefix_Diag_N.blf`, Zipy는 `prefix_N.pcap` 또는 `.pcapng`입니다. 세션의 번호를 공유하고 예약한 번호는 실패·삭제로 되돌리지 않습니다. 기본 prefix는 `One_Click_Log`입니다.

## 정지와 종료

**메인 정지**는 기록을 끝내고 파일을 검사·보관합니다. **메인 X**는 이번 실행의 전용 CANoe·도구를 종료하고 미완료 소유 구간을 폐기합니다. 완료 파일·설정·다음 번호는 유지합니다. X 정리가 지연되면 약 1초 guard로 강제 종료를 요청하며 반복 X는 즉시 요청합니다. 원본 cfg를 자동 저장하지 않으므로 사용자 변경은 미리 직접 저장하세요.

재실행은 이전 중단 구간을 자동 폐기·정리합니다. 같은 번호를 재사용하거나 미완료 파일을 성공으로 승격하지 않습니다. 현재 실행에서 파일을 살리려면 X 전에 정지·보관 재시도를 완료하세요.

## 수신 감시와 한계

Zipy 기본 규칙은 Source MAC 접두사 `02:00:00`, 시작 유예 2초, 미수신 제한 2초, 2초 평균 최소 100pps입니다. 설정의 **zipy 유효성검사**에서 실제 장비에 맞게 변경·삭제·기본 복원합니다. 다른 Source도 원본에 저장하며 규칙은 캡처 필터가 아닙니다.

선택 NIC 단절·수신 규칙 위반·기록 도구 오류가 확인되면 **선택한 모든 기록을 정지**하고 닫힌 파일의 보관을 시도합니다. Zipy 관측 확인 불가가 5초 지속돼도 정지합니다. CAN·Diag는 측정/기록 도구 상태를 확인하지만 **실제 CAN 프레임·신호의 미수신 감지는 현재 미지원**입니다. 팝업이 없다는 사실로 정상 통신을 판단하지 말고 Trace와 원본을 확인하세요.

0.9.9의 실제 조합별 자동 보관과 0.9.16 제공 BLF의 진단 왕복을 확인한 근거가 있습니다. 같은 0.9.16 표본 한 건에는 Diag에서 약 39ms·155프레임 누락이 관측됐고 원인은 미확정입니다. 새 버전 실차 재시험, 실제 VN·물리 분리·대표 부하·60분/1 GiB 초과 확인은 별도로 수행해야 합니다. [현재 구현과 남은 검증](docs/reference/implementation_status.md)을 따릅니다.

## 저장과 버그리포트

| 저장물 | 위치와 보관 방식 |
| --- | --- |
| 캡처 원본 | 사용자가 고른 폴더. 진단의 25 MiB 한도와 별개 |
| 설정·번호·이력 DB | `%LOCALAPPDATA%\One Click Log\state.sqlite3` |
| 진단 JSONL | 배포 EXE 옆 `developer_logs`, 약 5 MiB 현재 파일과 백업 4개로 순환 |
| 내보낸 ZIP | 버그리포트 버튼을 누른 시점의 로그를 Windows 바탕화면에 저장. 자동 전송·수량/기간 정리 없음 |

같은 실행 폴더에서 재실행하면 진단에 이어 쓰며 오래된 내용은 용량 기준으로 교체합니다. 진단 저장 기간은 보장하지 않습니다. 이전 짧은 실사용 표본으로 환산한 연속 기록 보관량은 약 10~20분이며 0.9.21 장시간 실측값은 아닙니다. **오류 직후 ZIP과 TC 결과를 저장**하세요. 실제 누락 분석에는 해당 BLF·PCAP도 별도로 필요합니다. [진단·이력 보관 설명](docs/guides/diagnostics.md)을 참고하세요.

## 개발과 배포

```powershell
.\run.cmd
.\run_demo.cmd
.\build.cmd --no-pause --check
```

개발에는 Python 3.14 x64와 [고정 의존성](requirements.lock)을 사용합니다. 사용자 실행에는 Python/Git 설치가 필요 없습니다. 빌드는 `packaging/build_release.py`와 `packaging/app.spec`를 사용합니다. Documents 작업 폴더의 기본 산출물은 `%USERPROFILE%\Downloads\OneClickLog_Builds`에 생성합니다. 자세한 준비·검사·빌드·Git 절차는 [개발 안내](CONTRIBUTING.md)에 있습니다.

- [실차 48 TC와 결과 입력 문서](docs/testing/One_Click_Log_Vehicle_Test_Plan.html)
- [시험 PC 준비](docs/guides/test_pc_setup.md)
- [구조·요구사항·현재 구현](docs/README.md)
- [버전별 업데이트](docs/updates/README.md)
- [공식 배포용 사용자 가이드 관리](user_guide/README.md)

실제 소스는 `src/vil_logging`입니다. [과거 개발 기록](docs/archive/README.md)은 당시 근거이며 현재 사용 지침이 아닙니다. 실제 캡처·진단 ZIP·업무 cfg·PC별 경로와 빌드 산출물은 Git에 넣지 않습니다.
