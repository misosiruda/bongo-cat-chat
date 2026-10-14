# 자동 업데이트

2026-10-13 사용자 결정: **새 버전 자동 다운로드, 다음 앱 실행 때 적용**. `misosiruda/bongo-cat-chat` 저장소는 2026-10-14 공개 전환했다. 같은 날 사용자 요청으로 [첫 공개 개발판 v0.1.0.dev6](https://github.com/misosiruda/bongo-cat-chat/releases/tag/v0.1.0.dev6)을 게시하고 실제 익명 다운로드·다음 실행 적용을 확인했다. 일반 배포 조건 검토와 다른 PC 인수는 별도로 남아 있다.

## 이용자 동작

- 설치된 앱이 시작 15초 후와 실행 중 6시간마다 GitHub 최신 정식 Release를 확인한다. 설정의 `업데이트 확인`으로도 확인할 수 있다.
- 미지원 게임 연동 구조를 발견하면 즉시 한 번 확인한다. `dev6`부터 관리 DLL의 무관한 변경은 기능 계약이 같으면 허용한다. 대응 앱은 같은 서명 검증·다음 실행 적용 경로로 받으며 게임 파일은 수정하지 않는다. [게임 업데이트 대응과 확인 범위](game-update-compatibility.md)를 참고한다.
- 채팅을 계속 사용하는 동안 새 버전을 내려받는다. 준비 상태만 알리고 실행 중인 앱을 강제로 종료하지 않는다.
- 다음 실행 때 서명·해시를 다시 확인하고, 별도 임시 DB에서 새 앱의 오프라인 화면을 검사한 뒤 버전을 전환한다. 대화 DB·초안·테마·사이드바 설정은 기존 위치를 계속 사용한다.
- 다운로드·검증·화면 검사 실패는 기존 버전을 유지한다. 새 앱이 시작 직후 비정상 종료하면 다음 실행의 선택을 이전 버전으로 되돌린다. 시도 표식을 먼저 기록해 같은 패키지를 매 실행마다 다시 적용하지 않는다.
- 다른 설치본이나 소스 실행이 같은 대화 저장소를 사용 중이면 안내 후 종료한다. 이 경우는 버전 실패로 기록하거나 이전 버전으로 되돌리지 않으며, 사용 중인 앱을 닫은 뒤 같은 새 버전으로 다시 실행할 수 있다.
- 오프라인 실행과 개발 소스 실행에서는 새 업데이트를 조회하지 않는다.

정식 Release 게시가 업데이트 기준이다. 브랜치 push나 PR 병합만으로 설치본이 바뀌지는 않는다. `draft`·`prerelease`와 현재보다 낮거나 같은 버전은 받지 않는다. GitHub의 [최신 릴리스 API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)를 사용한다.

자동 업데이트가 없는 기존 `0.1.0.dev1` 설치본은 기능을 스스로 추가할 수 없다. [새 설치 파일](installation.md)을 **최초 한 번 실행**하고 기존 설치 폴더를 선택하면 기록을 보존하며 전환한다. 먼저 수동으로 제거할 필요는 없다. 이후의 호환되는 정식 릴리스부터 자동으로 받는다.

## 설치와 실패 처리

```text
BongoCatChat/
├── BongoCatChat.exe                 # onefile 실행기와 업데이트 적용기
├── .bongo-cat-chat-install          # schema 2, active/previous 선택
├── .bongo-cat-chat-run.lock         # 실행·업데이트 배타 잠금
├── versions/<version>/
│   ├── BongoCatChatApp/             # Qt EXE와 _internal
│   └── .bongo-version.json          # 관리하는 버전 폴더 표식
├── .updates/                       # 다운로드·서명·검사·상태
├── Uninstall.exe                  # Windows 설치 파일로 설치했을 때의 제거 프로그램
└── uninstall.ps1                  # 내부 제거 엔진
```

실행기는 앱이 종료될 때까지 설치 잠금을 유지한다. 다음 실행에 준비된 패키지가 있으면 현재 설치된 실행기의 복사본에 작업을 넘기고 종료한다. 복사본은 기존 PyInstaller 외부 부트로더까지 종료된 것을 확인한 후 잠금을 얻는다. 게임·Steam·다른 앱을 종료하지 않는다.

새 앱은 별도 폴더에서 검사한다. 실행기 EXE를 원자적으로 교체하고 **활성 버전 포인터를 마지막에 원자적으로 변경**한다. 그 전에 실패하면 기존 앱 경로가 유지된다. 검사 후 파일이 없어지거나 실행 권한이 거부돼 프로세스를 시작하지 못해도 이전 버전 선택으로 복구한다. `bootstrap_schema=1`과 `data_schema=1`만 허용한다. 실행기만 먼저 갱신돼도 이전 앱을 실행할 수 있어야 하는 호환 규약이다. 다른 형식의 업데이트는 거부한다.

앱과 실행기는 저장소 잠금 획득 실패를 전용 종료 코드 `20`으로 구분한다. 실행기는 이 코드에서 활성·직전 버전과 적용 시도·결과 표식을 그대로 유지한다. 오프라인 진단 실행은 대화상자 대신 `startup_error=profile_in_use` 보고를 남기며, 일반 실행은 기존 안내창을 표시한다. 실제 프로세스 시작 예외와 그 밖의 빠른 비정상 종료 복구는 유지한다.

현재·직전 버전을 보관하고 더 오래된 폴더는 관리 표식과 알려진 구성만 있을 때 정리한다. 대화 DB를 설치 폴더 안에 두는 실행 옵션은 거부한다. 설치·업데이트·제거는 재분석 지점과 경로 탈출을 거부하며 기본 DB와 설치 폴더의 별도 파일은 보존한다.

오프라인 화면 검사가 게임 연동 호환성을 보장하지는 않는다. 게임 파일 해시·숨김 상태가 지원되지 않으면 기존 연결 방어를 따른다. 전원 손실·백신·다른 PC 인수는 실제 시험과 구분한다.

## 다운로드의 신뢰 기준

- 고정 저장소의 HTTPS API·릴리스 자산과 지정한 GitHub 리디렉션 호스트만 사용한다. 응답이 제시한 임의 다운로드 URL을 실행하지 않는다.
- 고정 공개키로 [Ed25519 서명](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)을 확인한다. manifest 원본 바이트, 저장소·플랫폼·버전·파일명·크기·SHA-256·지원 형식을 검사한다.
- ZIP은 1 GiB, 해제 후 2 GiB·20,000개 항목으로 제한한다. 경로 탈출, 링크, Windows 예약 이름·대체 데이터 스트림, 대소문자 중복, 게임 바이너리와 예상 밖 최상위 파일을 거부한다.
- GitHub 토큰이나 사용자 로그인 정보를 동봉하지 않는다. 비공개 저장소·릴리스 없음의 404와 통신 실패를 최신 버전 확인 성공으로 표시하지 않는다.
- 요청에 대화·Steam 계정·로비·초안·프로필을 넣지 않는다. 일반 HTTPS 통신의 IP 등은 GitHub에 전달된다. 렌더러는 원격 요청을 계속 차단하고 Python 작업자만 다운로드한다.

## 릴리스 작성자 절차

Windows 게시자 인증은 아래 Ed25519 서명과 별개다. 배포용 묶음은 먼저 [Windows 코드 서명](windows-code-signing.md)을 적용하고 `pack --signing-config <설정-파일>`로 다시 검사한다. 아래 예시는 인증서 없는 로컬 개발 검사이며 `--allow-unsigned`를 명시한다. Windows 경고 제거 검증으로 사용하지 않는다.

개인키는 Git·앱·릴리스에 포함하지 않는다. 개발 PC의 키는 Git 제외 경로 `research/private/update-signing-key.dpapi`에 Windows 사용자 범위 [DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)로 암호화했다. 공개키만 `src/bongo_chat/update-config.json`에 고정한다. 다른 계정·PC에서의 배포, 키 백업·복구는 별도 준비가 필요하다. 임의로 키를 교체하면 기존 이용자가 새 서명을 검증할 수 없다.

아래 초기화는 처음 한 번만 실행한다. 기존 개인키나 공개키가 있으면 덮어쓰지 않는다.

```powershell
.venv/Scripts/python tools/release.py keygen --private-key research/private/update-signing-key.dpapi
```

`src/bongo_chat/__init__.py`와 `pyproject.toml`의 버전을 맞춘다. 안정판은 `0.1.0`, 개발판은 `.devN` 형식을 사용한다. 첫 공개판은 검증된 `0.1.0.dev6`을 유지하고 기존 업데이트가 받을 수 있는 일반 GitHub Release(`draft=false`, `prerelease=false`, 최신 릴리스)로 게시했다. GitHub의 배포 채널 선택이 안정판 인수 완료를 뜻하지 않으며 제목·설명에 개발판을 명시한다.

```powershell
pwsh -NoProfile -File packaging/build.ps1 -OutputRoot dist/automatic-updates -AllowUnsigned
.venv/Scripts/python tools/release.py pack --bundle dist/automatic-updates/BongoCatChat --private-key research/private/update-signing-key.dpapi --output dist/release-assets --allow-unsigned
```

생성 자산은 `bongo-cat-chat-windows-x64.zip`, `update-manifest.json`, `update-manifest.sig`다. 도구는 로컬 파일만 만들며 GitHub에 게시하지 않는다. 첫 설치에는 실행기·버전 폴더·설치 스크립트를 갖춘 전체 설치 묶음이 필요하다. 위 ZIP은 기존 실행기가 받는 업데이트 페이로드다.

사용자가 승인한 게시 범위와 후보 검수에 따라 작성자가 `v<version>` 일반 Release에 세 자산을 함께 게시한다. 공개 리소스는 [인증 없이 조회](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)할 수 있다. 첫 공개 개발판의 게시 결정은 D-020에 기록했으며, 일반 배포 조건·소스 라이선스·게임 개발사의 승인은 별도로 관리한다.

## 검증

`tests/test_updates.py`는 서명·스키마·해시·릴리스 형식, 실패 다운로드, ZIP 경로·링크, 설치 잠금, 포인터 변경 실패, 후보 검사 실패, 이전 선택 복구와 파일 보존을 검사한다. `tests/test_desktop.py`는 실제 Qt의 준비 표시·확인 버튼·초안 보존을 검사한다. API 대역과 실제 Windows 실행기 증거는 [검증 기록](update-validation.md)에 구분한다.
