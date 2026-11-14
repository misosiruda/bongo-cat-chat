# 변경 범위에 따른 CI

`Windows SignPath preflight`는 main 대상 PR, main push, 수동 실행에서 시작한다.
먼저 Ubuntu에서 Python 표준 라이브러리만 사용하는 가벼운 검사를 실행하고,
변경 범위에 따라 Windows 빌드 작업을 선택한다.

| 변경 | 가벼운 검사 | Windows 테스트·빌드 |
| --- | --- | --- |
| README, 일반 Markdown 문서, docs 아래 소개 이미지 | 실행 | 생략 |
| 앱 코드·리소스, 테스트, 도구, 의존성, 패키징, CI 설정 | 실행 | 실행 |
| 설치·배포에 포함되는 개인정보 안내와 소스 안내, LICENSE | 실행 | 실행 |
| 수동 실행, 비교 기준을 찾지 못한 경우, 변경 파일이 없는 경우 | 실행 | 실행 |

문서 전용 허용 목록 밖의 경로는 기본적으로 Windows 검사 대상이다.
특히 `docs/privacy-policy.md`, `docs/privacy-policy.en.md`,
`docs/licensing/SOURCES.md`는 [고지 수집 도구](../tools/collect_license_notices.py)와
[설치 파일 생성](../packaging/build-setup.ps1)의 입력이므로 일반 문서로 제외하지 않는다.
docs 아래 실행 코드·HTML·설정 파일도 문서 전용 허용 목록에 포함하지 않는다.

PR은 base와 head의 공통 조상부터 PR head까지, push는 이벤트의 before부터 after까지
전체 변경을 비교한다. 이름 변경은 이전 경로의 삭제와 새 경로의 추가로 검사한다.
따라서 마지막 커밋이 문서뿐이어도 PR 전체에 앱 변경이 있으면 Windows 검사를 실행한다.
비교 실패를 문서 전용 변경으로 취급하지 않는다.

## 가벼운 검사의 범위

- CI 선택과 문서 검사기의 회귀 테스트를 실행한다. 앱 의존성·Qt·NSIS는 설치하지 않는다.
- 루트 안내 문서와 docs 아래 Markdown의 UTF-8 인코딩 및 충돌 표시를 확인한다.
- 변경된 문서의 로컬 링크·이미지 경로가 Git에 포함되어 있는지 검사한다.
- 삭제·이름 변경된 문서와 이미지에 대한 기존 문서의 참조도 검사한다.
- 변경된 SVG의 XML을 확인한다. Markdown 줄바꿈용 공백 등 문서 스타일은 강제하지 않는다.
- 코드 예제·HTML 주석은 링크 검사에서 제외한다. 외부 URL의 응답, Markdown 제목 앵커,
  이미지 렌더링과 번역·설명의 정확성은 이 검사 범위에 포함하지 않는다.

워크플로 자체에 경로 필터를 두지 않고 Windows `build` 작업에 조건을 건다.
문서 변경도 `Change scope and documentation` 결과와 Windows 작업의 생략 상태가 남는다.
브랜치 보호·필수 검사·릴리스 승인 설정은 변경하지 않는다.

## 로컬 검사

```powershell
python -m unittest discover -s tests -p test_ci_checks.py -v
```

가벼운 검사 성공은 앱 테스트·Windows 패키징 성공을 뜻하지 않는다.
Windows가 선택되면 [기존 배포 검증 절차](signpath-validation.md#재현할-ci와-결과-위치)를
그대로 수행한다. 대응 소스 다운로드 등 기존 빌드 실패를 무시하거나 성공으로 바꾸지 않는다.
