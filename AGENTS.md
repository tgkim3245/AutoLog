# One Click Log 작업 규칙

## 배포용 사용자 가이드 유지

- 공식 관리 원본은 `user_guide/AutoLog_User_Guide.template.html`, `distribution_notice.template.txt`, `guide_metadata.json`이다. `user_guide/README.md`의 흐름을 따른다.
- 사용자에게 보이는 동작·화면·설정, 도구/라이선스/보안 준비 조건, 파일 관리·복구·버그리포트, 실제 검증 범위가 바뀌면 같은 작업에서 사용자 가이드와 필요한 배포 안내문을 갱신한다.
- 가이드를 수정하면 `guide_metadata.json`의 개정/갱신일과 `user_guide/CHANGELOG.md`를 함께 갱신한다. SW 버전 변경 시 가이드를 검토한 뒤 `reviewed_app_version`을 맞춘다. 단순한 버전 문자열 치환으로 검토를 대신하지 않는다.
- 빌드는 HTML 가이드와 START_HERE 안내문을 EXE 폴더·ZIP에 포함하고, 적용 버전·문서 개정·파일 해시를 `build_info.json`에 기록해야 한다. 원본 누락이나 검토 버전 불일치를 우회하지 않는다.
- 사용자 가이드에는 현재 동작과 확인 범위를 쓴다. 개발 계획·모의 성공을 실제 장비/차량 기록 성공으로 표현하지 않는다. 실제 캡처·진단 로그·업무 cfg와 개인 경로를 Git에 넣지 않는다.

## 문서 분류와 현재 기준

- 문서 시작점은 `docs/README.md`다. 현재 요구/설계는 `docs/reference/`, 사용 준비·오류 조치는 `docs/guides/`, 검증·실차 TC는 `docs/testing/`에 둔다.
- 버전별 변경·해당 배포물의 검증은 `docs/updates/`, 초기 계획/단계 기록은 `docs/archive/`, 제공 자료 분석은 `docs/analysis/`, 발표/성과 양식은 `docs/presentation/`에서 관리한다. 공식 배포 가이드 원본은 계속 `user_guide/`에 둔다.
- 현재 문서에 예전 정책을 덧붙여 상충하는 지침을 남기지 않는다. 현재 기준을 갱신하고 과거 기록에는 당시 범위와 현재 문서 링크를 명시한다. 실제 현장 실패·검증 근거는 과거라는 이유만으로 삭제하거나 현재 버전 통과로 바꾸지 않는다.
- 문서를 이동/삭제하면 상대 링크·문서 앵커·실행 예제·생성 도구 경로를 함께 수정하고 프로젝트 Python으로 `tools/check_docs.py`를 실행한다.
- 실차 시험서 원본은 `docs/testing/vehicle_test_plan.md`, 생성기는 `tools/build_vehicle_test_document.py`다. 원본 변경 후 HTML을 재생성하고 `--check`로 최신성을 확인한다. 기존 회차 결과 JSON을 문서 정리 때문에 잃지 않도록 호환성을 확인한다.
- 소스·테스트·도구 삭제는 실제 참조와 실행/복구·호환 경로를 확인한 뒤 수행한다. 로컬 캡처·진단 ZIP·사용자 DB·기존 배포물은 문서/코드 정리 대상과 구분한다.
