# Windows 코드 서명

2026-10-14 기준, 사용자는 무료 SignPath Foundation 신청과 자체 소스 MIT 라이선스를 선택했다. [신청 준비](signpath-application.md), [라이선스 검토](license-review.md), [Code signing policy](code-signing-policy.md)에 준비 상태를 기록한다. 아래 Windows 인증서 저장소/SignTool 구현은 기존에 준비한 별도 서명 경로이며 SignPath 서버 연결은 아니다. 이 구현이나 아래의 합성 검사를 **실제 서명 완료, Windows 경고 제거, SmartScreen 평판 확보**로 표현하지 않는다.

## 서로 다른 두 서명

- **Windows Authenticode**: Windows가 EXE의 게시자와 무결성을 확인한다. 신뢰할 수 있는 인증기관의 코드 서명 인증서가 필요하다.
- **업데이트 Ed25519**: 기존 앱이 업데이트 ZIP의 출처와 해시를 검증한다. 기존 고정 공개키와 개인키를 그대로 사용한다. 이 서명만으로 Windows의 게시자 표시가 바뀌지는 않는다.

코드 서명이 유효해도 관리자 권한 확인 창 자체가 사라지는 것은 아니다. 새 파일의 SmartScreen 평판 경고도 남을 수 있다. 현재 NSIS 설치 프로그램은 `RequestExecutionLevel user`로 현재 사용자에게 설치한다. 관리자 권한이 필요하다는 창이 실제로 나타나면 실행 파일과 실행 옵션을 별도로 확인한다.

## 인증서 준비

현재 구현은 **Windows 인증서 저장소의 특정 인증서와 Windows SDK SignTool**을 사용한다. 토큰이나 클라우드 HSM을 사용하는 인증기관은 해당 공급자의 도구로 인증서를 `CurrentUser\My` 또는 `LocalMachine\My`에 연결해야 한다. 공급자별 연결·로그인·개인 발급 자격은 별도 확인 항목이다.

무료 SignPath Foundation은 오픈소스 라이선스·프로젝트 심사·빌드 연결 조건을 충족해야 한다. 자체 라이선스는 MIT로 결정했으며 신청·서비스 연동은 준비 단계다. 인증서 게시자는 개인 명의가 아닌 SignPath Foundation이 된다. 한국 개인 명의는 조사한 Azure Artifact Signing의 Public Trust 개인 인증 지원 지역에 포함되지 않는다.

스크립트는 인증서 발급·구매, 개인키 가져오기, 신뢰 저장소 변경을 수행하지 않는다. 인증서 비밀번호를 명령행이나 설정에 받지 않는다. 인증기관이 발급한 인증서와 개인키 사용 권한을 준비한 뒤 다음 예시를 로컬 파일로 복사한다.

```powershell
New-Item -ItemType Directory -Path research/private -Force
Copy-Item packaging/signing-config.example.json research/private/signing-config.local.json
```

설정 파일의 항목:

| 항목 | 의미 |
| --- | --- |
| `schema` | `1` |
| `signToolPath` | 설치한 Windows SDK의 `signtool.exe` 절대 경로 |
| `certificateThumbprint` | 사용할 인증서의 정확한 40자리 지문. 자동 선택하지 않음 |
| `certificateStoreLocation` | `CurrentUser` 또는 `LocalMachine`. 저장소는 `My` |
| `timestampUrl` | 인증기관에서 안내하는 RFC 3161 HTTP(S) 타임스탬프 서버 |

예시의 SDK 버전·인증서 지문은 실제 값으로 바꿔야 한다. 예시 파일을 그대로 사용하면 실패한다. `/sha1`은 인증서 지문 선택용이고 실제 파일과 타임스탬프의 해시는 모두 SHA-256이다. 개인키·PFX·P12와 로컬 설정은 커밋하거나 배포 묶음에 넣지 않는다.

## 서명한 배포 파일 생성

앱 버전은 기존 공개 릴리스보다 높은 새 버전을 사용한다. 이미 배포된 같은 버전의 파일을 서명해서 덮어쓰면 자동 업데이트가 이를 새 버전으로 받지 않으므로, `src/bongo_chat/__init__.py`와 `pyproject.toml`을 다음 릴리스에서 함께 변경한다.

```powershell
./packaging/build.ps1 -OutputRoot dist/signed -SigningConfig research/private/signing-config.local.json
./packaging/build-setup.ps1 -Bundle dist/signed/BongoCatChat -NsisPath <NSIS-3.13-폴더> -OutputRoot dist/signed-setup -SigningConfig research/private/signing-config.local.json
.venv/Scripts/python tools/release.py pack --bundle dist/signed/BongoCatChat --private-key research/private/update-signing-key.dpapi --output dist/signed-release --signing-config research/private/signing-config.local.json
```

처리 순서:

1. PyInstaller 빌드 후 실행기 `BongoCatChat.exe`, 앱 본체 `BongoCatChatApp.exe`, 자체 호환성 검사기 `FeatureProbe.exe`와 읽기 전용 검색기 `MemoryScan.exe`를 서명한다.
2. 각 파일에 SHA-256 Authenticode와 RFC 3161 타임스탬프를 적용한다. 서명 상태·인증서 지문·타임스탬프와 `signtool verify /pa /all /tw` 결과를 확인한다. SignTool의 경고 종료 코드도 실패로 처리한다.
3. 설치 빌드가 입력 묶음의 서명을 다시 검사한다. NSIS `!uninstfinalize`에서 `Uninstall.exe`를 서명한 후 설치 파일에 포함한다.
4. 임시 이름으로 생성된 설치 EXE를 서명·검증하고 최종 해시를 계산한 뒤 배포용 파일명과 `.sha256`을 만든다. 실패한 임시 설치 파일은 제거한다. 이미 같은 출력 파일이나 체크섬이 있으면 덮어쓰지 않는다.
5. 업데이트 도구가 입력 EXE들의 Windows 서명을 다시 검사한 뒤 ZIP·SHA-256·Ed25519 manifest 서명을 생성한다. Windows 서명 검사 실패 시 업데이트 개인키를 읽거나 출력 디렉터리를 만들지 않는다.

서명 후 EXE를 수정하면 서명이 깨진다. ZIP·manifest·체크섬 생성 이후 파일을 다시 서명하면 해시가 달라진다. 변경이 필요하면 새 출력 디렉터리에서 해당 배포 단계를 다시 실행한다. 스크립트는 GitHub Release를 자동 게시하지 않는다.

제3자 DLL·Python 확장·Qt 실행 파일의 기존 서명은 이 작업에서 교체하지 않는다. **모든 종속 바이너리의 Smart App Control 통과는 별도 검사 대상**이다. 설치·제거 PowerShell 원본은 기존 설치 엔진의 원본 일치 검사를 유지한다.

## 개발용 미서명 빌드

인증서가 없는 상태의 로컬 검증은 매 단계 명시적으로 허용한다. 옵션 없이 실행하면 빌드를 중단하며, 실패한 서명을 자동으로 미서명 빌드로 바꾸지 않는다.

```powershell
./packaging/build.ps1 -OutputRoot dist/development -AllowUnsigned
./packaging/build-setup.ps1 -Bundle dist/development/BongoCatChat -NsisPath <NSIS-3.13-폴더> -OutputRoot dist/development-setup -AllowUnsigned
.venv/Scripts/python tools/release.py pack --bundle dist/development/BongoCatChat --private-key research/private/update-signing-key.dpapi --output dist/development-release --allow-unsigned
```

이 옵션은 Windows 게시자 경고를 해결하지 않는다. `-TestIdentity`도 서명 검사를 자동으로 건너뛰지 않는다. 별도 시험 식별자로 미서명 설치 파일을 만들 때는 `-TestIdentity -AllowUnsigned`를 함께 사용한다.

## 검증과 남은 인수

`tests/test_windows_signing.py`는 잘못된 설정, 다른 인증서, 누락·변조·타임스탬프 없는 서명, SignTool 실패·경고, 자체 EXE 선택, 업데이트 해시·Ed25519 재생성을 검사한다. `BONGO_TEST_NSIS_PATH`에 NSIS 폴더를 지정하면 실제 컴파일러의 제거 프로그램 콜백과 설치 파일 생성 순서도 검사한다. 이때 서명 성공은 격리된 합성 대역으로 만들며 실제 인증서나 신뢰 저장소는 변경하지 않는다.

인증서 확보 후 추가할 실제 인수:

- 새 빌드의 자체 EXE·설치 EXE·설치 후 `Uninstall.exe`가 `Valid`이며 의도한 게시자와 타임스탬프를 갖는지 확인
- 브라우저로 내려받은 파일을 별도 Windows PC에서 실행하여 게시자 표시·SmartScreen·Smart App Control을 각각 기록
- 서명된 새 업데이트가 기존 실행기의 Ed25519 검증을 통과하고 대화 기록을 보존하는지 확인
- 게임·Steam 연동은 기존 별도 인수 범위를 유지하고 실사용 로비로 자동 테스트 메시지를 보내지 않음

서명 스크립트 도입은 DB·업데이트 프로토콜·앱 런타임을 바꾸지 않는다. 스크립트 변경을 되돌려도 이미 서명된 파일의 서명을 제거하거나 설치본을 자동으로 다운그레이드하지 않는다. 인증서 갱신 시 새 지문을 설정에 반영하고 검증해야 하며, 기존 업데이트 Ed25519 키는 회전하지 않는다.

공식 근거: [SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool), [NSIS 컴파일 콜백](https://nsis.sourceforge.io/Docs/Chapter5.html#uninstfinalize), [SmartScreen 평판](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation), [Artifact Signing 지원 조건](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart#prerequisites), [SignPath 조건](https://signpath.org/terms).
