# SignPath 준비 검증

2026-10-14, 별도 `build/windows-code-signing` 워크트리에서 실행했다. 소스 기준은 `45e7d1e`와 이 워크트리의 미커밋 변경이다. 원래 작업 폴더의 소스를 수정하거나 게임 로비에 시험 메시지를 보내지 않았다. 기존 가상환경과 NSIS 3.13은 도구로만 재사용했다.

## 실행 결과

| 구분 | 결과 | 범위 |
| --- | --- | --- |
| 의존성 버전 | 39개 잠금 버전 일치 | 메타데이터 조사. 네이티브 라이선스 전체 검토 아님 |
| 전체 PyInstaller 빌드 | 앱 onedir와 런처 onefile 성공 | 새 `dist/signpath-preparation/build-oss` 출력, 미서명 |
| 네이티브 검사 | 121개 네이티브 파일 해시 기록, 알려진 금지 파일 0개 | FMOD·게임 파일·불필요한 Qt GPL 모듈 검사 |
| frozen Python archive | UnityPy와 Texture2DConverter 포함, AudioClipConverter/fmod_toolkit/pyfmodex 제외 확인 | CArchiveReader로 실제 앱 EXE의 PYZ 검사 |
| 이미지 변환 | FMOD import 차단 상태에서 실제 UnityPy의 합성 RGBA 변환 성공 | 게임 파일·실제 아바타를 읽은 검사는 아님 |
| frozen 앱 UI | renderer=true, console_errors=[], offline=true, steam_connected=false | `--offline --smoke-report`, offscreen Qt, GPU 비활성화 환경 |
| 제품 메타데이터 | 런처·앱·FeatureProbe에 제품명 `Bongo Cat Chat`, 제품 버전 `0.1.0.dev6` 일치 | 실제 파일의 VersionInfo 조회 |
| NSIS | 미서명 Setup.exe 생성 성공 | 설치·제거의 실제 사용자 UI 재인수는 하지 않음 |
| 회귀 테스트 | 103 passed in 142.67s | 배포 구성 12개 + 기존 서명·설치·업데이트 검사 91개 |
| 고지 수집 추가 검사 | 관련 파일 13 passed in 5.56s | 위 12개 재실행 및 고지 수집 1개 추가 |
| 고지 필수 파일 검사 | 1 passed in 1.98s | GNU 전문 파일을 필수로 읽도록 바꾼 뒤 고지 검사 재실행 |
| Python 배포 메타데이터 | wheel 빌드 성공, `License-Expression: MIT`, `License-File: LICENSE` 및 실제 LICENSE 포함 확인 | `setuptools>=77`로 PEP 639 지원 최솟값 반영 |
| 문법·diff | PowerShell AST, artifact XML 파싱, `git diff --check` 통과 | SignPath 서비스 스키마/CI 서버 실행과 구분 |

셋업은 고지를 수집한 뒤 `dist/signpath-preparation/setup-with-notices`에 다시 생성했다. 첫 번째 `setup` 출력은 최종 고지 수집 전 파일이므로 후속 배포 후보로 사용하지 않는다. 모든 출력은 `0.1.0.dev6`의 **로컬 검토용 재빌드**이며 공개된 같은 버전의 기존 릴리스를 교체하지 않았다. 실제 배포 시 새 버전과 소스 태그를 정해야 한다.

최종 로컬 Setup.exe는 214,089,276 bytes, SHA-256 `6d65c609343bcd5d59fcfb8d66119995f1c73d29031c6d1a8e1718a8abf164db`이며 생성된 `.sha256`과 일치했다. 제품명·제품 버전은 다른 자체 실행 파일과 일치하고 Authenticode 상태는 `NotSigned`다.

## 실행 명령

```powershell
# 기존 환경을 읽어 잠금 버전·패키지 라이선스 메타데이터 수집
& 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' tools/audit_distribution.py --output dist/signpath-preparation/dependencies.json

# 전용 출력에 앱·런처 재빌드
./packaging/build.ps1 -Python 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' -OutputRoot dist/signpath-preparation/build-oss -AllowUnsigned

# 빌드 후 추가한 고지 수집 단계를 실제 후보에도 실행
& 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' tools/collect_license_notices.py --output dist/signpath-preparation/build-oss/BongoCatChat/versions/0.1.0.dev6/BongoCatChatApp/_internal/bongo_chat/legal

./packaging/build-setup.ps1 -Bundle dist/signpath-preparation/build-oss/BongoCatChat -NsisPath 'C:/Project/bongo-cat-chat/research/private/tooling/nsis-3.13' -OutputRoot dist/signpath-preparation/setup-with-notices -AllowUnsigned

$env:BONGO_TEST_NSIS_PATH = 'C:/Project/bongo-cat-chat/research/private/tooling/nsis-3.13'
& 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' -m pytest -q tests/test_distribution.py tests/test_windows_signing.py tests/test_packaging.py tests/test_updates.py
& 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' -m pytest -q tests/test_distribution.py
& 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' -m pytest -q tests/test_distribution.py::test_notice_collection_keeps_licences_and_excludes_unused_fmod
& 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' -m pip wheel --no-deps --no-build-isolation --wheel-dir dist/signpath-preparation/wheel .
```

빌드 훅 조정 중 첫 후보에서 간접 Qt GPL 의존성을 두 개 검출해 실패시켰다. DLL을 빌드 후 임의 삭제한 것이 아니라 해당 플러그인의 수집을 제한한 뒤 전체 재빌드로 통과했다. 일반 실행·입력기의 장기 동작이나 앞으로 추가할 QML 기능까지 검증한 것으로 확대하지 않는다.

## 완료되지 않은 외부 검증

- GitHub Actions의 실제 호스팅 빌드 실행과 SignPath 서버 XML/정책 검증
- SignPath 신청·승인·MFA·GitHub App 연결·매 릴리스 수동 승인
- 실제 인증서로 앱/설치/제거 파일을 서명하고 새 PC에서 신뢰 체인을 확인하는 검사
- 최종 Qt/Chromium 고지·대응 소스 제공 완전성, Steam/게임 의존 허용 여부
- 설치 중 개인정보 고지와 업데이트 통신 선택권
- 기존 자동 업데이트의 클라우드 CI 키 보관/게시 설계 및 서명된 새 버전 인수
- 정상 GPU 화면, 한글 입력, 실제 게임 아바타·로비, 다른 PC·순정 설치 인수

미서명 앱·런처·FeatureProbe의 `Get-AuthenticodeSignature` 결과는 `NotSigned`다. Windows 경고가 해결됐다고 표현하지 않는다. [신청 자료](signpath-application.md)와 [라이선스 검토](license-review.md)에 남은 준비를 연결했다.
