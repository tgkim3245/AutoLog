# 초기설정: CANoe 19 등록과 Npcap 설치

기준 SW 0.9.22 · 작성 2026-10-25

배포 EXE 옆 [Initial_Setup.bat](../../tools/Initial_Setup.bat)는 Windows 기본 PowerShell로 CANoe 19 공식 COM 등록과 Npcap 관리자 설치를 순서대로 수행한다. Python은 필요 없다. 일반·내부 배포 모두 BAT를 포함하며, Npcap 공식 설치 파일은 확인된 회사 내부 PC 1대용 배포에만 포함한다.

CAN·Diag는 **CANoe 19(64비트)를 사용해야 한다.** CANoe 19 프로그램·라이선스·Vector 드라이버는 먼저 설치·준비한다. BAT는 설치된 CANoe 19의 기본 COM 등록과 Npcap 설치를 진행한다. 배포 가이드 첫 화면의 **0. 초기설정**에서 같은 순서를 안내한다.

1. 배포 ZIP 전체를 로컬 폴더에 푼다. 앱과 모든 CANoe 작업을 저장·종료한다.
2. Initial_Setup.bat를 더블클릭한다. 설치 폴더와 Vector 레지스트리에서 CANoe64.exe 버전 19와 짝인 RegisterComponents.exe를 찾는다. 후보가 여러 개면 번호를 선택한다.
3. Vector 서명을 확인한 공식 등록 도구의 Windows 관리자 요청을 승인한다. 완료 후 선택한 CANoe 19가 64비트 COM 대상으로 등록됐는지 확인한다. 다른 자동화도 이 기본 대상의 영향을 받는다.
4. Npcap 드라이버와 두 DLL이 있으면 설치를 건너뛴다. 없으면 BAT 옆 installers/Npcap/npcap-1.90.exe의 고정 크기·SHA256·Nmap Software LLC 서명을 확인해 관리자 실행한다. 공식 설치창에서 라이선스·옵션을 검토한다. 재부팅 요청 시 먼저 완료한다.
5. 각 단계 결과를 확인한다. 한 단계가 실패해도 다른 단계 결과는 따로 표시한다. 앱에서 cfg·NIC를 선택하고 연결·짧은 기록을 확인한다. 설치/등록 확인은 측정·라이선스·실차 기록 성공과 별개다.

설치 파일이 없는 일반 배포에서는 Npcap을 PC 관리자 또는 공식 경로로 준비한다. BAT는 도구를 내려받거나 CANoe 15로 대체하지 않는다. 앱/다른 프로세스를 강제 종료하거나 레지스트리를 직접 쓰지 않는다. 관리자 승인을 취소하거나 도구·서명·해시·버전 확인이 실패하면 성공으로 처리하지 않는다. CANoe 후보 선택에서 빈 입력은 등록 취소이며 Npcap 단계는 계속 확인한다.

검색·검증만 하려면 다음을 실행한다. 설치·등록은 실행하지 않는다. 로그는 `%TEMP%\OneClickLog-InitialSetup`에 저장한다. 로그에는 실제 경로가 있으므로 Git에 넣지 않는다.

```powershell
.\Initial_Setup.bat --check
```

검증은 개발 PC의 실제 검색/서명 확인 및 시스템 동작을 대체한 설치·등록 취소/오류 회귀 검사 범위다. 실차 PC에서 실제 등록/설치는 별도 확인한다. [시험 PC 준비](test_pc_setup.md)를 함께 따른다.
