# 두 Windows PC에서 번갈아 배포하기

두 PC는 같은 업데이트 Ed25519 키를 사용하고 각 Windows 사용자 계정의 DPAPI로 따로 암호화해 보관한다. 기존 이용자의 신뢰 기준인 `src/bongo_chat/update-config.json`의 공개키는 바꾸지 않는다. 이 설정은 Windows Authenticode 게시자 인증과 별개다.

2026-10-15 사용자 승인으로 기존 키 PC를 보존한 채 두 번째 PC의 구성을 완료했다. 두 PC가 동일한 dev11 manifest 원본 바이트에 만든 Ed25519 서명이 일치했고, 두 번째 PC는 저장한 키를 별도 새 프로세스에서 다시 열어 검증했다. 기존 공개키와 원본 PC의 키 파일은 변경하지 않았다. 이 결과는 서명 환경의 검증이며 다른 PC의 실제 게임·설치본 인수를 대신하지 않는다.

## 작업을 시작할 때

1. 실제 작업 폴더와 Git 루트, 브랜치, 변경 파일을 확인한다. 다른 PC에서 작업했다면 원격 `main`·열린 PR·최신 Release를 읽고 로컬 상태와 비교한다. 로컬 변경을 덮거나 강제로 초기화하지 않는다.
2. 해당 PC의 `research/private/update-signing-key.dpapi` 존재 여부를 확인한다. 내용은 화면·채팅·로그에 출력하지 않는다. 파일이 있으면 서명을 위해 다른 PC를 켜거나 채팅에 요청할 필요가 없다.
3. 키가 없다면 새 키를 생성하거나 공개키를 바꾸지 않는다. 기존 키 PC의 제한된 서명 또는 별도로 승인된 안전한 이전 절차를 사용한다.
4. 개발 환경은 각 PC의 프로젝트 `.venv`를 사용한다. 게임·Qt·설치본 검증 결과를 다른 PC에도 적용된 것으로 취급하지 않는다.

## 빌드와 서명

버전과 소스·검토·CI·설치 검사를 확정한 뒤 기존 `tools/release.py pack`에 이 PC의 DPAPI 파일을 지정한다. 이 도구는 개인키의 공개키가 저장소에 고정된 키와 일치하는지 검사하고, 그 키로 manifest 원본 바이트에 서명한다. Windows 인증서 없는 개발판은 기존과 같이 명시적인 `--allow-unsigned` 경로를 사용하며 게시자 경고가 사라졌다고 표현하지 않는다.

```powershell
.venv/Scripts/python.exe tools/release.py pack `
  --bundle dist/<새-빌드>/BongoCatChat `
  --private-key research/private/update-signing-key.dpapi `
  --output dist/<새-릴리스-자산> `
  --allow-unsigned
```

두 PC가 같은 버전을 동시에 게시하지 않는다. 게시 전 원격 최신 Release·태그·소스 커밋을 다시 확인하고, 이미 배포된 버전의 자산을 덮어쓰지 않는다. 서명 후 ZIP과 manifest를 바꾸면 다시 검증·서명해야 한다. 공개 게시 후 익명 다운로드와 기존 버전의 실제 업데이트를 별도로 검증한다.

## 키 취급과 복구

- 개인키 원문·DPAPI 파일·일회용 이전 파일은 Git, 앱, 설치 파일, Release 자산에 포함하지 않는다. `research/private/`는 Git 제외 영역이다.
- 두 PC의 DPAPI 파일은 바이트가 같을 필요가 없다. 복호화 후 얻는 공개키와 같은 입력에 대한 Ed25519 서명이 일치하는지로 확인한다.
- Windows 재설치·사용자 계정 변경·PC 분실 후에도 DPAPI 파일만 있으면 복구된다고 가정하지 않는다. 키 백업·재해 복구와 새 PC 추가는 별도 준비가 필요하다.
- 기존 키의 사본 추가와 키 교체를 구분한다. 공개키 변경은 기존 설치 앱의 업데이트 신뢰를 바꾸므로 일반적인 두 PC 작업 전환에 사용하지 않는다.

검증 기록과 개인 경로·이전 암호문은 로컬 비공개 영역에 보관한다. 제품의 실제 동작과 자동 업데이트는 [제품 검증](product-validation.md), [업데이트 검증](update-validation.md), [릴리스 절차](automatic-updates.md)를 따른다.

키 사본은 일회용 수신 공개키를 사용하는 [RSA-OAEP](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/#encryption)로 전달했고, 원본 Ed25519 서명과 수신자·전달 문맥을 검증한 뒤 [Windows 사용자 범위 DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)로 다시 보호했다. 평문 키를 파일이나 출력에 쓰지 않았으며, 확인 후 일회용 복호화키를 제거했다. 이를 별도 복구용 백업이 마련됐다는 의미로 사용하지 않는다.
