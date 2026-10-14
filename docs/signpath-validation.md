# SignPath 신청 후보 검증

2026-10-14, 별도 `build/windows-code-signing` 워크트리에서 수행했다. `45e7d1e`에서 시작하여 `2cc8348`까지의 main을 병합했다. 원래 작업 폴더는 수정하지 않았고 실제 사용자 기록·게임 로비에 시험 데이터를 쓰지 않았다. 자체 소스 MIT와 개인정보 선택 기능을 포함한 **미서명 심사 후보**이며 기존 dev6/dev7 Release 자산은 변경하지 않았다.

## 재현할 CI와 결과 위치

**성공 확인:** [GitHub Actions #38530843368](https://github.com/misosiruda/bongo-cat-chat/actions/runs/38530843368), 2026-10-14. PR head `61e266e51ede2bd052a41eca61074705a5b654ba`, 실제 테스트 merge SHA `f5f109104a27ad04c6799e56da99cb45e9bc9036`. `344 passed in 98.90s`; 소스 9개 검사, 앱/설치 파일 빌드, 고지·제품 메타데이터·frozen 오프라인 화면 검사와 artifact 업로드까지 모두 성공했다. 유니코드 바로가기 수정 후 로컬 설치·제거·서명 검사도 `50 passed in 90.06s`다.

해당 실행의 artifact ID는 앱·설치 파일 `11878381827`, 대응 소스 `11877648037`, 테스트 결과 `11877503484`다. GitHub가 기록한 앱 artifact ZIP SHA-256은 `33d86b9e1eec8fbb1fc8834120d6d60b2f1fe66fb8c8494082aedaa91c33bb55`이며 Setup.exe 자체 해시와 구분한다. 보존 기간 이후에는 이 공개 소스와 workflow에서 다시 빌드해야 한다.

[PR #16](https://github.com/misosiruda/bongo-cat-chat/pull/16)의 Checks와 [Windows SignPath preflight](https://github.com/misosiruda/bongo-cat-chat/actions/workflows/windows-signpath-preflight.yml)에서 실행 SHA, 각 단계 결과, artifact를 함께 확인한다. 최종 성공 실행 URL과 결과 수치는 PR 본문의 검증 항목에 기록한다. 아래는 수행할 검사와 결과물 설명이며 실행 중·실패·취소된 작업을 성공으로 간주하지 않는다.

GitHub-hosted Windows 2022 / CPython 3.13.3에서 다음을 순서대로 실행한다.

1. 잠금 의존성을 새 가상환경에 설치한다. NSIS 3.13 및 Mono.Cecil을 공식 배포처에서 받고 SHA-256을 검증한다.
2. Qt/PySide 대응 소스 9개를 내려받아 크기·SHA-256을 대조한다.
3. 전체 pytest를 실행한다. 합성 데이터 기반 실제 Qt UI와 NSIS 설치·재설치·제거, 업데이트 거부·취소, 배포/서명 실패 방어를 포함한다.
4. 미서명 앱·런처·자체 도구를 빌드한다. 패키지 버전·알려진 배포 차단 요소와 고지 원문 해시를 검사한다.
5. 패키지의 UI/설정/기능 계약을 이 checkout과 바이트 단위로 대조한다. 자체 실행 파일 4개의 제품명·버전을 검사하고 실제 frozen EXE를 격리된 데이터 폴더에서 오프라인 실행한다.
6. 개인정보 안내와 업데이트 선택이 포함된 Setup.exe를 생성하고 최종 SHA-256을 기록한다.

| Artifact | 내용 | 보존 |
| --- | --- | --- |
| `signpath-preflight-<실행 SHA>` | `signpath-preflight/BongoCatChat/`, 네이티브 감사·고지·오프라인 결과, `signpath-setup/`의 Setup.exe와 해시 | 7일 |
| `corresponding-sources-<실행 SHA>` | 대응 소스 아카이브 9개, 소스 lock과 교체 안내 | 14일 |
| `test-results-<실행 SHA>` | JUnit XML, bundle-validation/offline-smoke JSON, PyInstaller 경고 | 7일 |

PR 이벤트의 artifact 이름은 PR head와 다른 GitHub 테스트 merge SHA를 사용할 수 있다. 실행의 head SHA와 checkout SHA를 혼동하지 않는다. CI 보존 기간은 신청 후보 검토용이며 공개 바이너리를 배포할 때 소스 아카이브를 릴리스 자산으로 별도 게시해야 한다.

## 로컬에서 확인한 범위

최신 main 통합 후 회귀 검사 343개가 통과했고, 설치 시험 fixture의 진단용 스크립트 일치를 고쳐 해당 검사 1개를 따로 재실행해 통과했다. 전체 로컬 실행은 `343 passed, 1 failed in 125.42s`, 수정 후 해당 설치 검사는 `1 passed in 18.73s`다. 이 둘을 하나의 전체 통과 실행으로 바꾸어 적지 않는다.

`dist/signpath-final-v3`의 실제 후보는 잠금 의존성 39개 일치, 네이티브 파일 122개·알려진 차단 요소 0개, 자체 실행 파일 4개의 `Bongo Cat Chat`/`0.1.0.dev7` 일치, 고지 6개 및 checkout 리소스 일치, frozen renderer=true/console_errors=[]/offline=true/steam_connected=false를 확인했다. Qt는 offscreen·GPU 비활성화 환경이며 일반 GPU 화면·IME 인수와 구분한다.

```powershell
$env:BONGO_TEST_NSIS_PATH = 'C:/Project/bongo-cat-chat/research/private/tooling/nsis-3.13'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QTWEBENGINE_CHROMIUM_FLAGS = '--disable-gpu'
& 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' -m pytest -q --basetemp 'C:/Users/misom/AppData/Local/Temp/pytest-of-runneradmin/pytest-signpath-ci-repro' --junitxml=dist/tests-integrated.xml
& 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' -m pytest -q tests/test_windows_signing.py::test_installer_update_choice_is_shared_and_preserved --basetemp 'C:/Users/misom/AppData/Local/Temp/pytest-of-runneradmin/pytest-signpath-ci-repro-2'
./packaging/build.ps1 -Python 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' -OutputRoot dist/signpath-final-v3 -AllowUnsigned
& 'C:/Project/bongo-cat-chat/.venv/Scripts/python.exe' tools/verify_review_bundle.py --bundle dist/signpath-final-v3/BongoCatChat --evidence dist/signpath-final-v3/evidence
./packaging/build-setup.ps1 -Bundle dist/signpath-final-v3/BongoCatChat -NsisPath 'C:/Project/bongo-cat-chat/research/private/tooling/nsis-3.13' -OutputRoot dist/signpath-final-v3-setup -AllowUnsigned
```

바로가기 경로 후속 수정 전 로컬 Setup.exe는 215,960,408 bytes, SHA-256 `75e5c94db0aa1f54984df17fcc4ebd051581e892c388a0c1113a6c2a509a40ab`이다. 해당 시점 후보의 설치 컴파일 확인이며 실제 인증서로 서명하지 않았다.

설치 바로가기는 후속 CI에서 Windows Script Host의 대상 설정이 한글 경로를 거부하는 것을 확인해 유니코드 API로 변경했다. 위 로컬 설치 해시와 343개 결과는 이 후속 수정 전 기록이며, 최종 설치·제거 회귀 검사와 원격 결과는 PR 본문 및 연결된 CI 실행을 기준으로 한다.

## 준비 과정에서 발견하고 수정한 사항

- 간접 Qt GPL 모듈과 사용하지 않는 FMOD를 처음 빌드에서 검출했다. 수집 hook을 수정하고 새 번들에서 제외를 검증했다.
- NSIS 일반 다운로드 URL이 HTML을 반환해 해시 검사가 실패했다. 공식 다운로드 URL과 미러를 사용하되 기대 크기·해시를 검증한 파일만 사용하도록 했다.
- 개발 환경의 editable install이 다른 checkout의 리소스를 공급할 수 있었고 깨끗한 CI에서는 패키지 데이터가 빠졌다. 현재 소스 경로를 명시하고 빌드 후 바이트 대조를 추가했다.
- 네이티브 고지만으로 Python의 선택적 개발 도구 import까지 빠짐없이 설명할 수 없어, FMOD 래퍼를 제외한 잠금 패키지 고지를 보수적으로 보존한다. 전체 고지 모음이 실제 runtime SBOM이라는 뜻은 아니다.
- CI에 전달된 한글 경로의 문자 코드는 정상이었지만 WSH의 TargetPath 설정이 실패했다. 설치·제거에 Windows `IShellLinkW`/`IPersistFile`를 직접 사용하고, 한글·공백·이모지 경로의 설치·재설치 후 별도 Shell.Application API로 바로가기 대상을 확인한다. 두 PowerShell 엔진은 기존 업데이트 형식과 호환되도록 각각 독립 스크립트로 유지한다. [Microsoft Shell Links](https://learn.microsoft.com/en-us/windows/win32/shell/links), [IShellLinkW](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-ishelllinkw).
- 과거 dev6 로컬 후보의 빌드·서명 대역 검사와 `NotSigned` 확인은 이력이다. 최신 신청 후보로 재사용하지 않는다.

## 이 검증으로 확인하지 않은 것

- SignPath 가입·신청 제출·재단 승인·MFA·GitHub App 연결·서비스 XML/정책 검증
- 실제 인증서의 Authenticode 서명, Windows 신뢰 체인·SmartScreen 변화
- 재단의 신규 프로젝트 평판·외부 Steam/게임 의존 수용 및 게임사의 승인
- 운영 업데이트 키의 클라우드 보관·새 서명 릴리스 게시·새 버전 적용 인수
- 정상 GPU/한글 입력 장기 동작·실제 로비·다른 PC·순정 게임 환경 인수

[신청 자료](signpath-application.md), [라이선스 검토](license-review.md), [개인정보 안내](privacy-policy.md)를 함께 확인한다. 실제 개인정보 안내를 포함한 설치·앱 변경과 심사/서명 승인은 별도 단계다.
