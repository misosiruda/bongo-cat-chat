# SignPath Foundation 신청 준비

2026-10-14 실제 [신청 페이지](https://signpath.org/apply)의 입력 항목을 확인해 작성한 초안이다. 폼 입력·약관 동의·가입·신청 제출은 하지 않았다. 현재 공개된 개발판을 SignPath가 이미 서명했거나 승인한 것처럼 소개하지 않는다.

## 준비 상태와 순서

자체 소스 MIT, 타사 고지·대응 소스, 설치 개인정보 안내와 업데이트 통신 선택은 준비했다. 공개 신청 후보는 `build/windows-code-signing` 브랜치다. 아래 정책 URL은 이 브랜치에서 바로 열 수 있으며 main 통합 후에는 `blob/main` 주소로 바꿀 수 있다. 기존 공개 설치 파일을 이 후보로 교체하지 않았다.

1. 아래 후보·정책·CI 근거를 검토한다. 성공 실행과 artifact는 [검증 기록](signpath-validation.md)에 둔다.
2. 신청인의 실제 이름·연락 이메일·GitHub/SignPath MFA 상태를 채우고 영문 초안을 제출한다. GitHub noreply 주소를 연락 이메일로 추정하지 않는다.
3. 재단의 신규 프로젝트 인지도 및 외부 Steam/게임 의존 판단을 받는다.
4. 승인 후 SignPath GitHub App과 프로젝트·artifact·수동 승인 정책을 설정한다. 실제 서명을 검증한 새 버전에 대응 소스 자산을 함께 게시한다.

새 프로젝트의 인지도 요건과 외부 게임 연동 방식에 대한 수용 여부는 재단 판단이다. 라이선스와 서류를 갖췄다고 승인을 보장하지 않는다. [공식 조건](https://signpath.org/terms).

## 실제 폼에 대응하는 값

아래 문서와 홈페이지는 공개 작업 브랜치의 실제 URL이다. 기존 릴리스는 이전 개발판이며, 심사용 후보는 CI artifact임을 구분한다.

| 신청 필드 | 준비할 값 |
| --- | --- |
| Project Name | `Bongo Cat Chat` |
| Repository URL | `https://github.com/misosiruda/bongo-cat-chat` |
| Homepage URL | `https://github.com/misosiruda/bongo-cat-chat/tree/build/windows-code-signing` |
| Download URL | `https://github.com/misosiruda/bongo-cat-chat/releases` |
| Privacy Policy URL | `https://github.com/misosiruda/bongo-cat-chat/blob/build/windows-code-signing/docs/privacy-policy.md` |
| Wikipedia URL | 비워 둠. 확인된 영문 Wikipedia 문서 없음 |
| Category | `Gaming` — 실제 선택지에서 확인 |
| Maintainer Type | 개인 유지보수에 해당하는 선택지. 선택지 문자열은 제출 화면에서 확인 |
| Build System | GitHub Actions — GitHub-hosted Windows 2022, 소스 검증·테스트·설치 파일 빌드 |
| First Name / Last Name | 신청인이 SignPath 계정에 사용할 실제 이름 입력 |
| Email | 신청인이 받을 수 있는 이메일 직접 입력 |
| Company Name | 개인 프로젝트이므로 해당 없으면 비워 둠 |
| Primary Discovery Channel | AI assistant에 해당하는 선택지. 정확한 선택지는 제출 화면에서 확인 |
| Exact discovery source | `ChatGPT / Codex` |

폼에는 행동 강령 동의와 개인정보 처리 동의 필수 항목이 있다. 신청인이 읽고 결정한다. 별도의 마케팅 수신 동의는 필수로 가정하지 않는다. reCAPTCHA가 나타나면 신청인이 처리한다.

## Tagline

```text
A free Windows companion messenger for existing Bongo Cat lobby chats.
```

## Description

```text
Bongo Cat Chat is an independently maintained Windows companion application for players who use Bongo Cat's existing Steam lobby chat. It provides a separate messenger interface and local history for messages received while the application is running. It connects to the existing lobby rather than operating a separate chat service. It reads the user's installed game resources and supported game state without patching game files or injecting code. The project is not affiliated with or endorsed by the game developer or Valve.
```

## Reputation

아래는 지금 사용할 수 있는 사실만 담은 초안이다. 제출 시점에 검증된 CI 실행 URL을 추가한다. 다운로드 수는 반복 다운로드를 포함하므로 이용자 수로 바꾸지 않는다.

```text
This is a new project, and I do not claim broad adoption or an established reputation. The public repository was created on October 12, 2026. The first public Windows development release, v0.1.0.dev6, was published on October 14, 2026:
https://github.com/misosiruda/bongo-cat-chat/releases/tag/v0.1.0.dev6

Source code, development decisions and validation records are available in the repository. Existing validation distinguishes offline tests, local packaging checks and limited real-game checks; clean-install and multi-PC acceptance remain incomplete. I understand that the Foundation may require more publicly verifiable history before accepting an executable application.
```

## 심사자가 추가 설명을 요청할 때

아래는 별도 전달 초안이며 필수 폼 항목이라고 가정하지 않는다. 미완료 사실은 해결·검증한 뒤에만 수정한다.

```text
Licensing: The maintainer has selected the MIT license for project-owned code. Dependencies keep their original licenses. The application build excludes unused proprietary FMOD binaries and unused GPL-only Qt add-ons. The review candidate includes third-party notices, Qt/Chromium source notices and a hash-pinned corresponding-source archive list. CI verifies and retains all nine Qt/PySide source archives. Future binary releases from this branch will publish those source archives alongside the binaries. Existing public dev6/dev7 artifacts have not been retroactively rebuilt by this work.

External integration: The application loads a Steam API library from the user's installed game and performs read-only compatibility and state checks. Game binaries and artwork are not redistributed. It has no feature for exploiting vulnerabilities, bypassing security controls, writing to game memory or injecting code. Please confirm whether this externally installed game/Steam dependency is acceptable under the Foundation's component policy; we do not assume that it qualifies for the System Libraries exception.

Privacy: Chat history stays in local SQLite storage. User-initiated messages are sent through Steam lobby chat. Installed copies automatically check GitHub for updates, which exposes ordinary connection metadata to GitHub. Chat content and game identifiers are not sent to GitHub or a developer-operated server. The installer displays the privacy policy and offers a persistent option to disable automatic and manual GitHub update requests; the same option and offline notices are available in app settings. Steam chat remains usable with update checks disabled. The choice survives reinstall and uninstall.

Build/signing: The review candidate is built by GitHub Actions on GitHub-hosted Windows runners. Source/notice verification, automated tests and unsigned installer compilation are part of the workflow. Only project-owned executables will be submitted for signing; upstream DLLs and QtWebEngineProcess.exe will not be re-signed with the Foundation certificate. Each release will require manual approval. The SignPath account, policy and end-to-end signing flow are not configured yet. Microsoft runtime libraries are upstream runtime components; they are not MIT-licensed project binaries. Please review their System Libraries treatment together with the external game/Steam dependency.
```

## 승인 후 필요한 서비스 설정

| 값 | 보관 위치 | 현재 상태 |
| --- | --- | --- |
| SignPath 조직 ID | GitHub variable `SIGNPATH_ORGANIZATION_ID` | 미발급 |
| 프로젝트 slug | `SIGNPATH_PROJECT_SLUG` | 미생성 |
| signing policy slug | `SIGNPATH_SIGNING_POLICY_SLUG` | 미생성. 수동 승인 필수 |
| artifact configuration slug | `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG` | XML 초안만 준비 |
| submitter API token | GitHub Actions secret `SIGNPATH_API_TOKEN` | 미발급. 파일·PR·채팅에 기록하지 않음 |
| GitHub App / trusted build link | SignPath에서 해당 저장소만 연결 | 미설치·미연결 |
| GitHub / SignPath MFA | 각 계정 | 소유자 확인 필요 |

`packaging/signpath/application-artifact.xml`은 네 개의 자체 EXE와 제품명·제품 버전을 제한한 초안이다. `submit-step.example.yml`은 공식 v3 action 사용 예시이며 자동 실행되지 않는다. action 참조는 조사 시 확인한 커밋으로 고정했다. 실제 서비스 스키마 검증과 인증서 검증은 아직 하지 않았다. [공식 GitHub 연결](https://docs.signpath.io/trusted-build-systems/github), [artifact 예시](https://docs.signpath.io/artifact-configuration/examples).

## NSIS 설치·제거 서명 연결

현재 `-SigningConfig` 경로는 Windows 인증서 저장소의 SignTool 경로다. SignPath API 토큰을 이 파일에 넣어서 사용할 수 없다.

SignPath 연결은 앱 EXE 서명 → 서명된 파일 검증 → NSIS 제거 EXE 생성·서명·포함 → Setup.exe 생성·서명·검증 → 최종 해시/업데이트 Ed25519 서명 순서로 완성해야 한다. NSIS를 일반 PE 파일로 제출한다고 내부 앱이나 제거 EXE까지 자동 서명되는 것으로 가정하지 않는다. `!uninstfinalize`에서 GitHub artifact 제출·대기·반환을 연결하거나 별도의 사전 생성 단계를 마련해야 하며, 서비스 계정과 승인 정책이 정해진 뒤 검증한다.

기존 Ed25519 개인키는 로컬 DPAPI 보호 키다. 이번 준비에서는 이 키를 읽거나 GitHub로 옮기지 않았다. 클라우드 CI에서 업데이트 자산까지 게시하려면 키 보관·승인 절차를 별도로 설계한다. preflight workflow에는 업데이트 서명·릴리스 게시 권한이 없다.
