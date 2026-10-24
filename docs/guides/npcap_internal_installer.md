# 내부 PC용 Npcap 설치기 동봉

기준 SW 0.9.21 · 빌드 코드 검토 2026-10-25

현재 옵션은 사용자가 확인한 같은 회사 내부 PC 1대용 패키지를 만드는 범위다. 일반 빌드와 구분하며 외부 배포용으로 전용하지 않는다. 이 문서는 해당 빌드 동작을 설명하며 배포 범위가 달라질 때의 권한을 대신 판단하지 않는다.

```powershell
.\build.cmd --include-npcap-internal
```

별도 `One Click Log-0.9.21-internal_<시각>` 빌드에 공식 Npcap 1.90 설치기를 원본 그대로 `installers/Npcap`에 복사한다. 공식 LICENSE·세 언어 설치 안내·파일 해시 목록을 함께 넣는다. 일반 빌드는 이 설치기를 포함하지 않는다.

고정 출처·크기·SHA256은 [npcap.lock.json](../../packaging/npcap.lock.json), 구현은 [npcap_bundle.py](../../packaging/npcap_bundle.py)를 기준으로 한다. 빌드는 Windows Authenticode 서명과 복사 결과를 확인하고 `build_info.json`에 `npcap_installer`와 `distribution_scope=internal-single-pc`를 기록한다. Wireshark CLI 폴더의 drivers_included=false와 별도 동봉 설치기를 혼동하지 않는다.

빌드는 설치기를 실행하거나 현재 PC 드라이버를 바꾸지 않는다. 대상 PC에서 기설치 상태를 확인하고 필요한 사용자가 공식 설치창을 관리자 권한으로 실행한다. 설치·재부팅·실제 캡처 성공은 대상 PC에서 별도 확인한다. 자세한 사용자 절차와 공식 조건 링크는 [배포 가이드](../../user_guide/README.md)를 따른다.

설치기·라이선스 원본 바이너리·개인 경로는 Git에 넣지 않는다. 2026-10-23 실제 패키지의 해시·서명·가이드·미설치 확인은 [해당 업데이트 기록](../updates/npcap_internal_installer_0_9_21.md)에 보존한다.
