# Code signing policy

2026-10-14: SignPath Foundation 신청 준비 중이다. 승인·후원·인증서 사용 권한을 아직 받지 않았으며 기존 공개 개발판은 Windows Authenticode 미서명 상태다.

## 책임과 승인

현재 제안 역할은 다음과 같다. 실제 SignPath 조직 권한은 가입·심사 후 설정하고 확인한다.

| 역할 | 담당 |
| --- | --- |
| Author / committer | [misosiruda](https://github.com/misosiruda) |
| Reviewer | [misosiruda](https://github.com/misosiruda), 외부 기여와 빌드·서명 설정 검토 |
| Signing approver | [misosiruda](https://github.com/misosiruda), 매 릴리스 직접 승인 |

GitHub와 SignPath 계정의 다중 인증 사용 여부는 소유자가 확인해야 한다. CI 토큰은 서명 요청에만 사용하고 수동 승인 책임을 대신하지 않는다. 새로운 담당자를 추가하면 이 정책과 서비스 권한을 함께 갱신한다.

## 서명 대상

프로젝트 소스에서 생성한 런처, 앱, 호환성 도구, 설치·제거 실행 파일만 대상으로 한다. Python, Qt/Chromium, Mono.Cecil 및 다른 프로젝트의 DLL/EXE를 프로젝트 인증서로 다시 서명하지 않는다. 각 제품 실행 파일에는 `Bongo Cat Chat` 제품명과 같은 빌드의 동일 제품 버전을 넣는다.

GitHub 호스팅 Windows 실행기에서 생성하고 GitHub Actions artifact로 보관한 결과를 출처 검증과 수동 승인 후 서명하는 경로를 준비한다. 로컬 미서명 빌드, 합성 테스트, XML/YAML 초안은 서비스의 출처 검증·실제 서명 완료 증거가 아니다.

SignPath Foundation 경로가 승인되면 게시자 인증서는 재단 명의가 된다. 서명은 게시자·무결성 확인을 제공하며 게임 개발사의 승인, 기능 안전성, SmartScreen 경고의 즉시 소멸을 보장하지 않는다.

## 개인정보

[Privacy policy / 개인정보 처리 안내](privacy-policy.md)를 확인한다. 설치본의 자동 GitHub 업데이트 통신이 있으므로 “사용자가 요청하기 전에는 모든 네트워크 통신을 하지 않는다”는 문구를 사용하지 않는다.

## 승인 후 사용할 고지

아래 문구는 **승인 후 실제 서비스를 사용하는 시점**에 홈페이지와 다운로드/릴리스 페이지에 게시한다. 현재 후원받는다는 문구로 사용하지 않는다.

> Free code signing provided by [SignPath.io](https://signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

기준: [SignPath Foundation 조건](https://signpath.org/terms), [GitHub 출처 검증](https://docs.signpath.io/trusted-build-systems/github).
