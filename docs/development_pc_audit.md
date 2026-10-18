# 현재 개발 PC 환경 점검

이 문서는 2026-10-17 설치 전 읽기 점검의 과거 기록이다. 아래에 적힌 미준비 항목은 당시 상태이며 현재 개발 절차는 [개발 안내](../CONTRIBUTING.md), 구현·준비 결과는 [1단계 개발 결과](development_stage_1.md)를 참고한다. 시험 PC·실제 장비/취득은 별도 검증이 필요하다.

점검일: 2026-10-17 (Asia/Seoul)
대상: 현재 개발 PC. 별도의 실제 시험 PC 점검 결과가 아니다.
방식: 실행 파일/버전·등록된 Python·설치 패키지 메타데이터·기본 경로·프로젝트 파일 읽기. 프로그램 설치·업그레이드·드라이버 변경·CANoe 실행·COM 접속·실제 캡처는 하지 않았다.

## 1. 결론

점검 당시에는 개발 환경이 모두 준비되지 않았다. Git·VS Code·CANoe 19 실행 파일은 확인했지만 프로젝트용 Python 3.14 x64 환경과 PySide6·pywin32·PyInstaller·pytest, 프로젝트 정의와 Git 저장소를 아직 준비하지 않은 상태였다.

Wireshark/TShark와 Npcap은 PATH/기본 설치 경로에서 찾지 못했다. 비표준 경로·portable 설치까지 없다고 단정하지는 않는다. 실제 Ethernet 개발 검증에는 해당 도구와 드라이버 준비가 필요하다.

## 2. 실제 확인 결과

| 항목 | 결과 | 근거 / 다음 처리 |
| --- | --- | --- |
| 64비트 Windows | 확인 | OS 버전 문자열 10.0.26200.0, Is64BitOperatingSystem=True |
| Python x64 | 3.9.2 실행 확인 | C:\Program Files\Python39\python.exe. 현재 선정한 개발 기준 3.14 x64는 프로젝트용으로 추가 준비 |
| Python x86 | 3.9.2 실행 확인 | C:\Program Files (x86)\Python39-32\python.exe. 새 x64 프로젝트에 혼용하지 않음 |
| pip | 두 Python에 20.2.3 | 기존 환경을 변경하지 않음. 새 프로젝트 가상환경에서 별도 관리 |
| PySide6 | 확인한 두 환경에 없음 | 기본 전역 패키지와 사용자별 Python39 경로 검사 |
| pywin32 | 확인한 두 환경에 없음 | COM 라이브러리 import 검증 단계에는 진입하지 못함 |
| PyInstaller | 확인한 두 환경에 없음 | EXE 제작 도구 추가 필요 |
| pytest | 확인한 두 환경에 없음 | 핵심 검증 도구 추가 필요 |
| pytest-qt·Ruff | 확인한 두 환경에 없음 | 선택 개발 도구, 채택할 때 추가 |
| SQLite | 표준 모듈 사용 가능 | Python39의 sqlite3 3.34.0 확인. 별도 서버 설치 필요 없음 |
| Git | 설치·실행 확인 | 2.55.0.windows.3 |
| VS Code | 실행 파일 확인 | Code.exe 파일 버전 1.142.0 |
| VS Code Python/Pylance 확장 | 기본 확장 경로에서 못 찾음 | 기본 .vscode/extensions 폴더는 존재. 다른 사용자 지정 확장 경로는 검사하지 않음 |
| CANoe | 실행 파일 확인 | C:\Program Files\Vector CANoe 19\Exec64\CANoe64.exe, ProductVersion=19.3, FileVersion=19.3.118 |
| Vector 드라이버 | 파일 일부 확인 | System32/drivers/vcanv.sys 25.40.10.0. 실제 VN 모델 지원·연결·인증은 미검증 |
| Wireshark·TShark·dumpcap | 확인 범위에서 못 찾음 | PATH와 Program Files의 일반 Wireshark 폴더 없음. 비표준 설치는 미확인 |
| Npcap | 확인 범위에서 못 찾음 | System32/Npcap 및 drivers/npcap.sys 없음. 실제 드라이버 로드/취득 시험은 하지 않음 |
| Visual C++ x64 런타임 | 설치 등록 확인 | v14 Redistributable x64 14.51.36247. 실제 앱의 DLL 호환은 빌드 후 확인 |

WindowsApps의 python/python3 실행 별칭은 발견했지만 실제 프로젝트 인터프리터가 설치됐다는 증거로 사용하지 않았다.

## 3. 현재 프로젝트 준비 상태

| 항목 | 결과 |
| --- | --- |
| .venv / venv | 없음 |
| pyproject.toml | 없음 |
| requirements.txt | 없음. 최종 의존성 관리 형식은 pyproject.toml과 버전 고정 자료로 구성 예정 |
| packaging/app.spec | 없음 |
| .git 저장소 | 없음. Git 프로그램 설치와 별개 |
| .gitignore | 있음. 가상환경·빌드 결과·PC별 설정·원본 로그 제외 규칙 포함 |
| Python 앱 코드 | 아직 없음 |
| HTML 화면 시안 | 점검 당시 src/ui/wireframe.html. 현재 docs/design/wireframe.html로 이동 |
| 기존 src/core·adapters·monitors·storage | 점검 당시 빈 자리표시자. 현재 정리 대상에서 제거 |

## 4. 준비 순서

1. 기존 Python 3.9는 유지하고 프로젝트용 Python 3.14 x64를 준비한다.
2. 이 프로젝트의 .venv를 만들고 PySide6·pywin32·PyInstaller·pytest를 설치·고정한다.
3. VS Code를 사용할 경우 Python 확장과 .venv 인터프리터를 설정한다.
4. pyproject.toml·개발/실행 의존성·Git 저장소·실제 Python 패키지 진입점을 준비한다.
5. 실제 Ethernet 연동을 이 PC에서 시험하려면 Wireshark 도구와 Npcap을 준비한다.
6. 기존 CANoe 19와 VN 장비의 라이선스/측정·COM 연결은 명시적인 연동 실증에서 확인한다.

이번 점검에서 위 설치·프로젝트 초기화를 실행하지 않았다. 설치할 항목의 상세 구분은 [설치 목록](installation_matrix.md), 폴더 기준은 [프로젝트 구조](project_structure.md)를 참고한다.

## 5. 확인 한계

Python은 등록된 3.9 x64/x86의 전역 패키지와 기본 사용자 패키지 경로를 확인했다. 다른 비표준 가상환경이나 앱 내부 번들 Python까지 전체 탐색한 결과는 아니다. 현재 프로젝트에 쓸 환경이 준비됐는지를 기준으로 판정했다.

일부 Windows 설치 등록정보는 읽기 제한으로 조회되지 않았다. 따라서 등록정보가 없다는 이유만으로 미설치를 단정하지 않고 실행 파일·버전·기본 경로 결과를 함께 사용했다.

CANoe 파일 존재는 라이선스·COM·복수 인스턴스 제어 정상의 증거가 아니다. vcanv.sys 파일은 실제 VN 장비 드라이버 동작의 증거가 아니다. 실제 앱 실행·실제 장비·시험 PC 설치 상태는 별도 확인한다.
