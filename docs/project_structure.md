# 개발 폴더 구조 기준

기준일: 2026-10-18 (Asia/Seoul)

현재 Python 앱은 `src/vil_logging/`에 구현되어 있으며 `pyproject.toml`, `requirements.lock`, `packaging/app.spec`, 실행 스크립트와 자동 검사가 루트에 있다. 실제 CANoe 구성과 차량 NIC 연동은 시험 PC에서 별도로 검증한다.

## 1. Git으로 관리하는 트리

    logging_automation/
    ├─ .gitignore / .gitattributes / .editorconfig
    ├─ pyproject.toml / requirements.lock
    ├─ CONTRIBUTING.md
    ├─ run.cmd / run_demo.cmd          소스 실행
    ├─ build.cmd                      버전별 배포본 자동 빌드
    ├─ src/
    │  └─ vil_logging/                실제 앱 패키지
    │  │  ├─ app.py / runtime.py      앱 시작과 실행 조립
    │  │  ├─ contracts/               명령·응답 자료
    │  │  ├─ ui/                      PySide6 화면·번역
    │  │  ├─ adapters/                외부 도구 연결
    │  │  ├─ workers/                 별도 작업 프로세스
    │  │  ├─ storage/                 설정·번호·캡처 파일
    │  │  └─ diagnostics/             환경 진단·순환 로그
    ├─ tests/unit/                    장비 없는 단위 검사
    ├─ tests/integration/             파일·프로세스 통합 검사
    ├─ tests/hardware/                명시적으로 실행하는 장비 검사
    ├─ packaging/                     자동 빌드 로직과 PyInstaller 사양
    ├─ licenses/                      배포 라이선스 고지
    ├─ docs/                          요구사항·설계·검증·개발 기록
    │  ├─ design/wireframe.html        HTML 화면 시안
    │  └─ test_pc_setup.md             시험 PC별 환경 확인표
    ├─ user_guide/                    사용자 안내와 발표 자료
    └─ outputs/README.md              로컬 산출물 안내만 추적

`outputs/`의 배포본·검증 파일과 로컬 `.venv/`, `developer_logs/`, 실제 캡처 파일은 `.gitignore`로 제외한다. Git은 빈 디렉터리를 추적하지 않는다.

## 2. 고정할 기준

- 실제 Python import·배포 대상은 src/vil_logging 아래 하나의 패키지로 모은다.
- Python 앱 코드는 `src/vil_logging/` 아래에만 둔다. 이전에 루트 `src/` 바로 아래 만든 빈 모듈 자리표시자는 제거했다.
- 화면 시안은 `docs/design/wireframe.html`에 보관한다. 실행 앱의 화면은 `src/vil_logging/ui/`에서 수정한다.
- `pyproject.toml`에서 프로젝트와 허용 의존성 범위를 관리하고 `requirements.lock`에 개발 PC의 정확한 패키지 버전을 기록한다. `.venv/`나 개발 PC Python을 배포 대상으로 복사하지 않는다.
- `packaging/`은 빌드 설정이다. 배포 결과와 중간 작업 파일은 `outputs/`에 둔다. 실제 캡처는 앱에서 선택한 폴더에, 프로필·번호 DB는 사용자별 로컬 앱 데이터에 저장한다.
- 하드웨어 실증은 기본 자동 검사에서 분리한다.
- 빈 세부 폴더를 모두 선생성하거나 내부 파일명을 지금부터 고정할 필요는 없다.

## 3. 현재 상태와 구분

`.gitignore`는 가상환경, 테스트 캐시, PC별 설정, 업무 원본과 `outputs/` 산출물을 제외한다. 새 개발자는 [개발 안내](../CONTRIBUTING.md)에서 Python 환경, 검사와 Git 절차를 확인한다. 현재 구현 현황과 다음 작업은 [구현 계획 5절·10절](implementation_plan.md), 전체 배포 목표는 [개발·배포 계획](development_delivery_plan.md)을 따른다.
