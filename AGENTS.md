# AutoLog 작업 규칙

## 배포용 사용자 가이드 유지

- 공식 관리 원본은 `user_guide/AutoLog_User_Guide.template.html`, `distribution_notice.template.txt`, `guide_metadata.json`이다. `user_guide/README.md`의 흐름을 따른다.
- 사용자에게 보이는 동작·화면·설정, 도구/라이선스/보안 준비 조건, 파일 관리·복구·버그리포트, 실제 검증 범위가 바뀌면 같은 작업에서 사용자 가이드와 필요한 배포 안내문을 갱신한다.
- 가이드를 수정하면 `guide_metadata.json`의 개정/갱신일과 `user_guide/CHANGELOG.md`를 함께 갱신한다. SW 버전 변경 시 가이드를 검토한 뒤 `reviewed_app_version`을 맞춘다. 단순한 버전 문자열 치환으로 검토를 대신하지 않는다.
- 빌드는 HTML 가이드와 START_HERE 안내문을 EXE 폴더·ZIP에 포함하고, 적용 버전·문서 개정·파일 해시를 `build_info.json`에 기록해야 한다. 원본 누락이나 검토 버전 불일치를 우회하지 않는다.
- 사용자 가이드에는 현재 동작과 확인 범위를 쓴다. 개발 계획·모의 성공을 실제 장비/차량 기록 성공으로 표현하지 않는다. 실제 캡처·진단 로그·업무 cfg와 개인 경로를 Git에 넣지 않는다.
