# 설치 프로그램과 개발 의존성

> 과거 기록: 이 문서는 작성 당시의 변경·검증 근거를 보존합니다. 현재 동작과 남은 확인 사항은 [현재 구현 상태](../../reference/implementation_status.md)를 따릅니다.

문서 구분: 설치 후보를 조사한 초기 기록이다. 현재 준비 절차는 [시험 PC 안내](../../guides/test_pc_setup.md), 구현·검증 상태는 [전체 검토](../../updates/project_audit_0_8_6.md)를 우선한다. 앱의 설치/복구 및 설치 링크 버튼은 제거됐다.

최신 갱신: 현재 개발 PC에는 Python 3.14.7 x64와 AppData 가상환경·앱/개발 의존성을 준비했다. 아래 3.14.8 표기는 최초 후보이며 실제 설치 조합은 [1단계 개발 결과](../development/development_stage_1.md)와 [버전 고정 자료](../../../requirements.lock)를 따른다. 실제 시험 PC 도구·드라이버 설치와 취득 검증은 남아 있다.

기준일: 2026-10-17 (Asia/Seoul)
대상: 개발/빌드 PC와 Windows 11 64비트 시험 PC. 이번 검토에서는 설치·업그레이드·패키지 다운로드를 수행하지 않았다.
최신 요구사항과 배포 검토: [개발 착수 전 검토](development_readiness_review.md), [개발·검증·배포 순서](development_delivery_plan.md).

## 1. 설치 범위

개발 PC는 Python으로 작성·검증·패키징한다. 시험 PC는 배포된 실행 파일을 사용한다. 시험 PC에 Python 개발 환경을 별도로 설치하는 것을 전제로 하지 않는다.

CAN/Diag는 CANoe 1·2의 화면 이름, Zipy는 Wireshark 계열 Ethernet 캡처의 화면 이름이다. Zipy라는 별도 캡처 프로그램이나 SDK를 추가 설치하는 요구가 아니다.

인터넷은 설치 파일·의존성 준비 때 사용할 수 있다. 배포 앱은 캡처·설정·패킷 보기·결과 저장에 인터넷을 요구하지 않는다. 사용자 설명상 CANoe는 연결한 VN 장비로 라이선스를 인증하며, 실제 PC에서 오프라인 측정 가능 상태를 확인한다.

## 2. 프로그램 설치 목록

| 항목 | 개발/빌드 PC | 시험 PC | 설치·확인 기준 |
| --- | --- | --- | --- |
| CPython 3.14 64비트 일반 빌드 | 필수 | 별도 설치 불필요 | 3.14.8을 초기 검증 후보로 선택. free-threaded/ARM/32비트 빌드를 혼용하지 않고 검증 후 정확한 버전 고정. [Python Windows](https://www.python.org/downloads/windows/) |
| Git for Windows | 이 프로젝트의 버전 관리에 필요 | 불필요 | 로컬 소스·변경·릴리스 이력 관리. 원격 저장소 업로드는 별도 결정. [공식 설치](https://git-scm.com/install/windows) |
| Visual Studio Code 또는 다른 Python 편집기 | 권장 | 불필요 | VS Code를 쓰면 Python 확장과 인터프리터를 프로젝트 가상환경으로 지정. [Windows 설치](https://code.visualstudio.com/docs/setup/windows) |
| CANoe 19 | 실제 CANoe 연동을 개발 PC에서 시험할 때 필요 | CAN/Diag 사용에 필수 | 기존 설치를 우선 사용. 에디션·SP·빌드·COM 등록과 각 .cfg 실행을 확인. 기존 환경을 일괄 재설치하지 않음. [Vector 제품](https://www.vector.com/en/product/canoe/) |
| Vector CAN 인터페이스 드라이버 | 장비를 연결해 시험할 때 필요 | CAN/Diag 사용에 필수 | 사용하는 VN 장비와 CANoe 19에 맞는 Vector Driver Setup. 현장 검증 버전을 유지하며 최신판으로 임의 교체하지 않음. [Vector 릴리스 정보](https://www.vector.com/en/services/release-information/) |
| Vector 라이선스 도구/구성 | 실제 연동 때 확인 | 기존 구성 확인, 필요 시에만 설치/설정 | 사용자 환경은 VN 장비 인증. Vector License Client 등의 필요 여부는 설치된 라이선스 체계에 따름. 별도 구매/서버 설치를 기본 요구로 두지 않음. [Vector License FAQ](https://support.vector.com/kb?NaVkF=I16nWjJZPgYn&id=kb_article_view&sysparm_article=KB0012035) |
| Wireshark Windows x64 패키지 | Ethernet 연동·파일 검증 때 필수 | Zipy 사용에 필수 | TShark 구성요소와 dumpcap·capinfos 존재 및 버전 확인. 현재 버전이 기준을 통과하면 유지. [공식 설치 안내](https://www.wireshark.org/docs/wsug_html_chunked/ChBuildInstallWinInstall.html) |
| Npcap 드라이버 | 실제 Ethernet 취득 때 필수 | Zipy 사용에 필수 | 보통 Wireshark 설치 과정에서 설치. 설치돼 있어도 NIC 열기를 확인. admin-only 설정을 기록. [Npcap 가이드](https://npcap.com/guide/npcap-users-guide.html) |
| Ethernet NIC 드라이버 | 실제 취득용 NIC 사용 시 | 실제 취득용 NIC 사용 시 | Windows 또는 제조사의 해당 장치 드라이버. 이미 동작 중이면 추가 설치 불필요. USB LAN 장비는 해당 모델 지원을 확인 |
| Microsoft Visual C++ x64 재배포 패키지 | 조건부 | 조건부 | 깨끗한 PC의 실제 배포물에서 런타임 누락이 확인되면 공식 패키지로 해결. 모든 PC에 중복 설치하는 기본 항목으로 잡지 않음. [Microsoft 공식](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170) |
| 통합 패널 배포 폴더 | 빌드 결과로 생성 | 필수 | EXE만 따로 복사하지 않고 검증된 폴더 전체 배포. Python·PySide6·pywin32 등 앱 런타임 포함 |
| PowerPoint 또는 PPTX 열람/편집 도구 | 향후 발표 작성 시 선택 | 앱 실행에는 불필요 | 현재 로깅 앱의 의존성에 포함하지 않음. 발표 자료 생성 방식은 후속 작업에서 결정 |

Wireshark의 TShark는 선택 구성요소이므로 GUI만 설치됐다고 완료로 판단하지 않는다. Npcap이 없으면 파일 열기는 가능해도 라이브 캡처를 못 한다. 무인 Wireshark 설치만으로 Npcap까지 설치됐다고 가정하지 않는다. [설치 구성 근거](https://www.wireshark.org/docs/wsug_html_chunked/ChBuildInstallWinInstall.html)

미디어 컨버터 자체에 설정 도구가 필요한지는 모델에 따른다. 일반적인 Ethernet 변환 장비라는 이유만으로 추가 SDK를 요구하지 않는다.

## 3. Python 가상환경에 설치할 패키지

아래는 개발 PC의 프로젝트 가상환경에 설치한다. 시험 PC 사용자가 각각 설치할 항목이 아니다.

| 패키지 | 구분 | 용도 / 관리 |
| --- | --- | --- |
| PySide6 | 실행 의존성 | Qt Widgets 화면·트레이·패킷 표. 관련 Qt 바이너리·Shiboken 등 의존성은 패키지 해석 결과와 함께 버전 고정 |
| pywin32 | 실행 의존성 | Windows COM·프로세스/시스템 연동. CPython 3.14 x64용 wheel 제공을 확인. 실제 CANoe 참조 생성은 별도 검증 |
| PyInstaller | 빌드 도구 | Windows 실행 파일 포함 폴더 빌드. 빌드 의존성·hooks도 함께 고정 |
| pytest | 개발 검증 도구 | 이름 생성·번호 예약·상태 전이·파일 작업 실패·가상 연동 검증 |
| pytest-qt | UI 자동 검증을 작성하는 경우 | Qt 이벤트·중요 사용자 흐름 검사에 한정. 필수가 되면 개발 의존성으로 고정 |
| Ruff | 개발 도구로 권장 | 문법·정적 검사·포맷. 설치하지 않아도 앱 실행에는 영향 없음 |

[PySide6 시작 안내](https://doc.qt.io/qtforpython-6/gettingstarted.html), [pywin32 공식 패키지](https://pypi.org/project/pywin32/), [PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html), [pytest](https://docs.pytest.org/en/stable/getting-started.html).

sqlite3·json·logging·pathlib·subprocess 등은 Python 표준 라이브러리를 사용한다. 별도 SQLite 서버, Node.js, Docker, 전체 Qt SDK, Visual Studio C++ 개발 도구, CAPL 전용 별도 IDE는 현재 설계의 필수 설치 항목이 아니다. 필요한 경우에만 추가하고 의존성 목록을 변경한다.

## 4. 버전 고정 기준

| 항목 | 초기 기준 | 고정 시점 |
| --- | --- | --- |
| 운영체제 | Windows 11 x64 | 대표 시험 PC와 같은 사용자 실행 환경으로 빌드·실행 확인 |
| Python | 3.14.8 일반 x64 후보 | 의존성 설치·COM·Qt·패키징 실증 후 패치 버전까지 고정 |
| PySide6/pywin32 | Python 3.14 x64 wheel이 있는 안정판 후보 | 전체 의존성 해석과 GUI/COM 실증 후 버전·해시 고정 |
| PyInstaller | 안정판 후보 | 동일 빌드 재현 및 새 PC 실행 후 고정 |
| CANoe | 기존 19의 실제 SP·빌드 | 각 시험 PC 환경표에 기록하고 지원 조합 목록으로 관리 |
| Wireshark/TShark·Npcap·Vector 드라이버 | 기존 시험 PC 버전 우선 | 정상 정지·실제 취득·부하 검증 통과 조합만 지원 |

현재 공식 Python 페이지에서 3.14.8을 확인했다. PySide6와 PyInstaller 패키지 메타데이터는 Python 3.14를 지원 범위에 포함하며 pywin32에는 cp314 win_amd64 wheel이 있다. **이것은 버전 후보의 설치 가능성 확인이며 우리 앱의 호환성 통과 결과가 아니다.** [Python](https://www.python.org/downloads/windows/), [PySide6](https://pypi.org/project/PySide6/), [pywin32](https://pypi.org/project/pywin32/), [PyInstaller](https://pypi.org/project/pyinstaller/).

## 5. 현재 개발 PC의 실제 점검 결과

실제 실행 파일·버전과 Python 패키지까지 확인했다. 시험 PC 점검과 구분하며 자세한 근거와 제한은 [개발 PC 점검](development_pc_audit.md)에 기록한다.

| 항목 | 확인 결과 | 필요한 조치 |
| --- | --- | --- |
| Python | 3.9.2 x64/x86 실행 확인 | 기존 환경 유지, 프로젝트용 3.14 x64와 .venv 준비 |
| PySide6·pywin32·PyInstaller·pytest | 확인한 전역/기본 사용자 환경에 없음 | 새 프로젝트 가상환경에 설치·고정 |
| Git | 2.55.0.windows.3 설치·실행 확인 | 프로젝트 Git 저장소는 초기화 전 |
| VS Code | Code.exe 1.142.0 확인 | 기본 확장 경로의 Python/Pylance 확장은 미확인 |
| CANoe | CANoe64.exe 19.3.118 확인 | 라이선스·COM·VN 연결은 별도 실증 |
| Vector 드라이버 | vcanv.sys 25.40.10.0 파일 확인 | 실제 VN 모델/채널 지원·동작은 미검증 |
| Wireshark 도구·Npcap | PATH/기본 경로에서 못 찾음 | 비표준 설치가 있는지 또는 개발 PC 설치 필요 여부 확인 |
| Visual C++ 런타임 | v14 x64 14.51.36247 설치 등록 확인 | 실제 앱/외부 도구 DLL 호환은 패키징 후 확인 |
| 프로젝트 환경/정의 | .venv·pyproject.toml·app.spec·.git 없음 | 개발 착수 단계에서 생성 |

이번 점검으로 설치·업그레이드·환경 설정을 변경하지 않았다. 일부 설치 등록정보는 읽기 제한이 있어 전체 설치 프로그램의 완전한 목록이라고 주장하지 않는다.

Python 3.9는 공식 지원이 종료됐다. 기존 환경을 삭제하지 않고 새 프로젝트 환경을 추가하는 방식을 권장한다. [Python 지원 상태](https://devguide.python.org/versions/).

## 6. 설치·배포 순서

1. 개발 PC에 Python x64와 프로젝트 가상환경을 준비하고 실행/개발 의존성을 분리한다.
2. Git 저장소·기본 제외 규칙·버전 고정 자료를 준비한다. 업무 로그와 PC별 실경로는 배포물에 포함하지 않는다.
3. 대표 시험 PC에서 기존 CANoe·VN 장비·Wireshark/TShark·Npcap 상태를 기록한다.
4. CANoe와 Ethernet의 최소 실증으로 지원 버전·정상 정지·파일 대응을 확인한다.
5. Windows x64에서 앱을 빌드하고 Python이 없는 깨끗한 PC에서 실행한다.
6. 대표 시험 PC 1대에서 로컬 파일 취득·오프라인·장시간 시험을 통과한다.
7. 버전·해시·의존성·지원 도구 조합·사용 안내·복구 안내를 포함한 폴더를 팀 PC에 배포한다.
8. 각 PC는 도구 경로·.cfg·NIC·저장 폴더를 자기 환경으로 설정하고 짧은 정상 취득으로 확인한다.

온라인으로 준비하더라도 실행 중 자동 패키지 설치·업데이트·다운로드는 하지 않는다. 필요 시 wheel·설치 파일을 별도로 보관해 재현 가능하게 한다.

## 7. 여러 PC 배포 시 이용 조건

PyInstaller 폴더에는 앱과 앱 런타임만 포함하고 CANoe·Wireshark·Npcap 설치 프로그램을 자동 재배포하지 않는다. 외부 프로그램은 각 PC에서 관리하는 공식 설치본을 사용한다.

Npcap의 공식 조건에는 일반 무료판의 시스템 수 제한과 Wireshark 등 사용의 예외, 별도의 재배포/무인 설치 조건이 있다. **팀의 여러 PC라는 이유만으로 유료 또는 무료라고 단정하지 않는다.** 직접 SDK를 쓰거나 설치 프로그램에 묶는 설계로 바꾸면 해당 조건을 다시 검토한다. PC 대수는 현재 기능 개발의 차단 조건이 아니다. [Npcap 공식 조건](https://npcap.com/), [OEM 조건](https://npcap.com/oem/).

PySide6/Qt의 사용 모듈과 LGPL 등 조건을 기록하고 배포물에 고지·라이선스 자료·해당 소스 제공 방식 등 필요한 자료를 준비한다. 폴더 배포만으로 모든 조건이 자동 충족됐다고 보지 않는다. [Qt 공식 LGPL 안내](https://www.qt.io/development/open-source-lgpl-obligations).

코드 서명은 필수 구매로 잡지 않는다. 팀 파일 배포의 출처·무결성은 버전과 해시로 확인하고, 실제 실행 정책에서 서명이 필요할 때 그 방식으로 보완한다. 사용자 답변상 현재 보안 예외 등록은 필요하지 않을 것으로 본다.
