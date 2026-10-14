# GNU 라이선스 원문

2026-10-14 공식 GNU 사이트에서 내려받은 원문이다. 이 디렉터리의 GPL/LGPL은 해당 제3자 라이브러리와 고지에 관한 것으로, 프로젝트 자체 코드의 MIT 선택을 변경하지 않는다.

- `GPL-3.0.txt`: https://www.gnu.org/licenses/gpl-3.0.txt
- `LGPL-3.0.txt`: https://www.gnu.org/licenses/lgpl-3.0.txt
- `LGPL-2.1.txt`: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt

LGPLv3는 GPLv3 본문과 함께 읽는다. Qt WebEngine의 Chromium 부분에는 LGPLv2.1 등 추가 조건의 코드가 포함된다. 전문 동봉만으로 모든 저작권 고지·대응 소스 제공 의무가 충족되는 것은 아니다. 버전별 판단은 `docs/license-review.md`를 따른다.

## 네이티브 고지와 소스

`sources.lock.json`은 공식 Qt 메타데이터와 대조한 전체 소스 9개와 생성 고지의 해시를 고정한다. `QT-NOTICES.txt`와 `CHROMIUM-LICENSES.html`은 이 아카이브의 라이선스·저작권·attribution을 보존한다. upstream 빌드/시험/다른 플랫폼 구성요소도 포함하는 고지 모음이므로 실제 runtime SBOM으로 해석하지 않는다.

`additional-notices.json`은 OpenSSL, Mesa/LLVM, NSIS 고지의 원문 경로와 SHA-256을 기록한다. 파일 바이트가 바뀌면 수집 단계가 실패한다. 갱신 절차:

```powershell
python tools/prepare_source_notices.py --cache dist/signpath-sources --download --generate
python tools/collect_license_notices.py --output dist/legal
```

소스 아카이브의 버전·해시는 의존성 갱신 시 원저작자 자료와 다시 확인한다. 생성물을 검토한 뒤 lock과 함께 커밋한다. 일반 릴리스에서는 소스 아카이브도 바이너리와 함께 게시한다. 자세한 절차는 `docs/licensing/SOURCES.md`에 있다.
