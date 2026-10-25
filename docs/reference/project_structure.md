# 현재 프로젝트 구조

기준 SW 1.0.0 · 검토 2026-10-25

```text
logging_automation/
  README.md / CONTRIBUTING.md / AGENTS.md
  pyproject.toml / requirements.lock
  run.cmd / run_demo.cmd / build.cmd
  src/vil_logging/
    app.py / runtime.py / instance.py / exit_guard.py
    documentation.py / verification.py
    contracts/       자료형·명령 계약
    ui/              Qt 화면·번역
    adapters/        CANoe·dumpcap·TShark
    workers/         역할별 프로세스·소유 핸들·응답/요약 전달
    monitors/        Ethernet 수신 규칙
    storage/         DB·번호·파일·복구·폐기·아카이브
    diagnostics/     준비·COM/채널/NIC·상시 진단·명시적 부하 검사
  tests/
    unit/            장비 없는 단위·UI 검사
    integration/     세션·파일·프로세스 통합 검사
    hardware/        명시적으로 실행하는 외부 도구 검사
  packaging/         EXE/ZIP 빌드·공식 도구 lock·라이선스 안내
  tools/             문서 검사·실차 시험 HTML 생성·배포 초기설정 BAT
  docs/
    README.md        문서 시작점
    reference/       현재 요구사항·구조·제어·구현 범위
    guides/          시험 PC·오류·진단 보관
    testing/         자동 검증·48 TC·결과 양식·환경별 근거
    updates/         버전별 수정·배포/검증 기록
    analysis/        제공 파일·환경 분석
    archive/         초기 계획·개발 단계
    presentation/    발표 구성·성과 측정 양식
  user_guide/        배포 가이드 템플릿·세 언어·사진·개정
  assets/            앱 아이콘 원본과 결과
  licenses/          배포 고지·라이선스
  outputs/           로컬 빌드·검증 산출물, README만 Git 관리
```

## 유지 기준

앱 런타임과 개발/문서·별도 지원 도구를 분리한다. `src/vil_logging`의 import 호환성을 문서 이동 때문에 바꾸지 않는다. `packaging`의 lock·라이선스와 `user_guide`의 원본·42장 언어별 사진·매니페스트는 빌드 검증에 필요하므로 유지한다.

demo worker, 관측/파일 식별·복구, 이전 프로필 이행은 실제 사용처와 회귀 검사가 있다. 제거된 화면의 번역이나 다른 문서로 통합된 안내만 사용처를 확인한 뒤 삭제한다. 과거 HTML 화면 시안과 가이드 위치 변경용 중복 문서는 제거했으며 현재 화면은 Qt 소스와 가이드 사진을 기준으로 본다.

현재 문서는 완료된 변경 기록을 계속 덧붙이지 않고 갱신한다. 릴리스별 사실은 [updates](../updates/README.md), 초기 설계는 [archive](../archive/README.md)에 보존한다. 상대 링크·코드 예제·생성 도구를 함께 수정하고 `tools/check_docs.py`로 검사한다.

## 로컬 데이터

사용자 설정·번호·이력은 `%LOCALAPPDATA%\One Click Log`, 모의 데이터는 그 아래 demo다. 실제 캡처와 업무 cfg·DB·진단·장치 식별자·개인 경로는 Git에 넣지 않는다. 개발 환경·캐시·outputs도 추적 대상이 아니다.

Documents에서 만든 새 배포물은 기본 `%USERPROFILE%\Downloads\OneClickLog_Builds`에 있다. `outputs`의 이전 EXE는 현재 소스 변경으로 갱신되지 않으며 다시 빌드해야 한다. [개발 안내](../../CONTRIBUTING.md)를 따른다.
