# SignPath 신청을 위한 라이선스 검토

기준일: 2026-10-14. 서명 준비는 `45e7d1e`에서 시작했으며 `2cc8348`까지의 main 변경(dev7·설정창·모자·초기 연결·울음 필터 수정)을 병합했다. 검토 대상은 `build/windows-code-signing`의 신청 후보이며 기존 공개 자산을 소급해 승인하는 문서가 아니다. 공개 릴리스 `v0.1.0.dev6`의 실제 파일, 설치된 잠금 버전의 패키지 메타데이터, 원저작자의 문서를 대조했다.

## 판정

자체 코드에는 소유자가 선택한 **MIT**를 [LICENSE](../LICENSE)와 `pyproject.toml`에 적용했다. SignPath의 OSI 라이선스 요건에 사용할 수 있는 선택이다. 그러나 자체 라이선스 결정은 패키지 전체의 재배포 조건, 게임 연동 허가 또는 SignPath 승인 완료를 뜻하지 않는다.

| 대상 | 확인한 사실 | 이번 조치 / 남은 확인 |
| --- | --- | --- |
| 자체 소스·문서 | 기존 원격 저장소는 공개이지만 LICENSE 미지정 | 소유자의 MIT 선택을 루트 LICENSE와 패키지 메타데이터에 적용하고 공개 작업 브랜치에 게시 |
| FMOD | 기존 번들에 `fmod_toolkit/libfmod/Windows/x64/fmod.dll` 존재. MIT인 Python 래퍼와 FMOD Engine의 이용 조건은 다름 | 앱이 쓰지 않는 AudioClip 변환과 FMOD를 빌드에서 제외. 새 번들 검증 결과는 아래 기록 |
| Qt QML 부가 모듈 | 기존 번들에 Qt Graphs/Quick3D/VirtualKeyboard 등 앱에서 쓰지 않는 모듈이 포함됨 | QML 리소스·디버그 플러그인·가상 키보드 수집을 제한. Widgets/WebEngine과 Windows 기본 입력 경로 유지 |
| Qt/PySide6 | 사용 모듈은 LGPL 경로 검토 대상. 패키지 한 개의 라이선스 문자열로 모든 Qt DLL을 판정할 수 없음 | 모듈별 고지, 라이브러리 교체·재빌드 설명, 대응 소스 접근을 확인 |
| 공개 고지 파일 | `v0.1.0.dev6`에 `THIRD-PARTY-NOTICES.txt` 자산이 이미 존재. FMOD 별도 조건도 언급됨 | LGPL 전문과 Chromium 고지의 완전성을 확인한 자료가 아니므로 그대로 재사용해 “검토 완료” 처리하지 않음 |
| 게임·Steam | 게임/Steam DLL과 그림을 번들에 넣지 않으며 설치된 파일을 읽거나 로드함 | 이 사실만으로 SignPath의 System Libraries 예외 해당 여부나 게임사의 연동 허가가 확정되지는 않음. 심사자에게 동작 설명 필요 |
| Windows 런타임 | Python·MSVC 및 시스템 API 의존 | CPython 고지와 재배포 런타임 고지/예외 범위 확인 |

FMOD의 무료 사용 조건은 OSI 오픈소스 라이선스와 동일하지 않다. 일반적인 “무료 앱”이라는 사유로 SignPath의 비공개 구성요소 제한을 통과한다고 판단하지 않는다. [FMOD 조건](https://www.fmod.com/legal), [SignPath 신청 조건](https://signpath.org/terms).

Qt PDF는 현재 공식 문서에 LGPLv3 선택지가 있으므로 이름만 보고 GPL 전용으로 분류하지 않았다. Qt WebEngine에는 Chromium의 별도 라이선스들이 포함된다. [Qt 모듈별 라이선스](https://doc.qt.io/qt-6/licensing.html), [Qt PDF](https://doc.qt.io/qt-6/qtpdf-index.html), [Qt WebEngine](https://doc.qt.io/qt-6/qtwebengine-licensing.html).

## LGPL 및 네이티브 고지 준비

이번 후보는 다음 자료를 `_internal/bongo_chat/legal/`에 동봉하고 앱 설정에서 오프라인으로 열람한다.

- 자체 MIT, Python 패키지·CPython·Mono.Cecil·PyInstaller 고지, GPLv3/LGPLv3/LGPLv2.1 전문
- Qt/PySide 소스 아카이브의 저작권·라이선스·attribution 자료와 Chromium 별도 고지
- OpenSSL 3.0.16, Mesa 11.2.2/LLVM 3.6.2, NSIS 3.13 고지
- 정확한 소스 URL·SHA-256·크기를 고정한 `sources.lock.json`, [대응 소스 및 DLL 교체 안내](licensing/SOURCES.md)

Qt 6.12.0 7개 모듈, PySide/Shiboken 6.12.0, Qt WebEngine/Pdf 6.140.0의 전체 소스 아카이브 9개를 확보하고 공식 Qt 다운로드 메타데이터의 SHA-256과 대조했다. WebEngine은 별도 버전으로 출시되는 모듈이다. 아카이브의 `src/3rdparty/chromium/chrome/VERSION`은 설치된 API가 반환하는 `140.0.7339.225`와 일치한다. `CHROMIUM_VERSION`의 보안 패치 추적 값은 이 API 버전과 구분한다.

고지 생성기는 소스를 실행하거나 디렉터리로 풀지 않고 라이선스 파일·저작권 고지·attribution을 보존한다. upstream 도구·시험·다른 플랫폼 고지도 포함한 보수적 모음이며, 그 모든 구성요소가 실제 Windows 실행물에 들어 있다는 뜻은 아니다. 버전이나 생성 고지 해시가 바뀌면 빌드를 실패시킨다. 실제 payload의 알려진 배포 차단 요소는 별도 검사한다.

DLL은 onedir의 별도 파일로 유지한다. 사용자가 LGPL 라이브러리를 교체하고 개인 수정본을 실행하거나 디버깅 목적으로 역공학하는 것을 금지하지 않는다. 앱이 DLL 자체의 프로젝트 서명을 강제하지 않는다. 이미 준비된 앱 업데이트가 교체본을 바꿀 수 있다는 점과 안전한 교체 순서를 안내했다.

CI는 동일한 소스 아카이브를 내려받아 검사하고 별도 artifact로 보관한다. **새 공개 바이너리를 배포할 때 이 소스 묶음도 릴리스 자산으로 함께 게시하고 다운로드 안내에서 연결한다.** 보존 기간이 짧은 CI artifact만으로 공개 릴리스의 장기 소스 제공을 대체하지 않는다. 이번 작업에서 기존 dev6/dev7 자산은 교체하지 않는다.

Qt의 의무 정리는 [공식 LGPL 안내](https://www.qt.io/development/open-source-lgpl-obligations), [Qt 소스](https://download.qt.io/archive/qt/6.12/6.12.0/), [PySide 소스](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/)를 따른다. 전체 저작권 분쟁 부재나 법률 검토 완료를 보증하는 문서는 아니다.

설치된 Qt wheel이 `LicenseRef-Qt-Commercial.txt`만 라이선스 파일 메타데이터에 열거하는 경우가 있다. 이것만으로 상용 라이선스를 취득했다고 간주하지 않는다. 공식 PySide 배포 설명은 같은 PyPI wheel의 오픈소스 사용 경로도 명시한다. [PySide6 WebEngine 배포 설명](https://pypi.org/project/PySide6-WebEngine/6.12.0.140/).

## 재현 가능한 점검

```powershell
.venv/Scripts/python tools/audit_distribution.py --output dist/license-review/dependencies.json
.venv/Scripts/python tools/audit_distribution.py --bundle dist/review/BongoCatChat --output dist/license-review/bundle.json
./packaging/build.ps1 -OutputRoot dist/review -AllowUnsigned
```

`audit_distribution.py`는 잠금 파일 39개 배포 패키지의 설치 버전·라이선스 메타데이터·고지 파일 경로를 기록하고, 번들의 네이티브 파일 해시와 알려진 금지 파일을 검사한다. FMOD, 게임 파일, 사용하지 않는 Qt GPL 모듈이 있거나 잠금 버전이 맞지 않으면 실패한다. 메타데이터가 비어 있거나 SPDX 표현식이 없다고 임의의 라이선스를 부여하지 않는다. 통과는 **알려진 파일 검사 통과**이며 법률 검토·완전한 SBOM·전체 고지 검증 완료를 뜻하지 않는다.

`packaging/hooks/disable_unity_audio.py`는 앱이 쓰지 않는 UnityPy 오디오 변환 진입점을 명시적으로 비활성화한다. UnityPy 소스나 공용 가상환경을 수정하지 않는다. 이미지 변환은 유지하며 오디오 변환 호출은 `NotImplementedError`로 실패한다. 빌드 환경에는 UnityPy의 선언 의존성으로 FMOD 래퍼가 설치될 수 있지만 배포 실행 파일에서 해당 모듈·네이티브 라이브러리를 제외한다.

QML hook은 현재 Widgets 앱에 필요한 동적 의존성을 수집하되 QML 전체 플러그인과 프로파일러를 넣지 않는다. 향후 QML·가상 키보드·오디오 기능을 추가할 경우 이 결정을 재검토한다.

## 검증 기록

- 패키지 메타데이터: `requirements-lock.txt`의 39개 버전 일치 확인.
- FMOD import를 금지한 새 Python 프로세스에서 실제 UnityPy를 불러와 합성 RGBA 픽셀을 변환하고 오디오 기능의 명시적 실패를 검사함.
- 첫 전체 빌드에서 Qt VirtualKeyboard와 Quick3D profiler의 간접 의존성을 검사기가 검출함. 해당 수집 hook을 수정한 뒤 다시 빌드함.
- 최종 빌드·오프라인 UI·설치 파일·회귀 검사 결과는 [SignPath 준비 검증](signpath-validation.md)에 별도로 기록한다.
- 실제 SignPath 서버 검증, 인증서 서명, SmartScreen 변화, 다른 PC 또는 실제 게임 아바타 표시는 이번 검사에서 확인하지 않는다.

## 신청 준비와 재단 심사 항목

- [x] 자체 소스 MIT 선택, 적용 및 공개 후보 브랜치 게시
- [x] 의존성/네이티브 배포 차단 요소 조사 및 자동 검사 추가
- [x] LGPL/Chromium/네이티브 고지, 대응 소스 9개 해시 검증 및 향후 릴리스 동봉 절차
- [x] 설치 중 개인정보 전문 안내와 업데이트 통신 선택, 앱 내 변경·고지 열람
- [ ] Steam/게임 라이브러리 외부 의존을 SignPath 심사자가 수용하는지 확인
- [ ] GitHub 호스팅 빌드 성공 URL 확보
- [x] 라이선스·정책 문서를 공개 후보 브랜치에 게시하고 신청 초안에서 연결
- [ ] 승인 후 새 공개 릴리스에 정책 링크·대응 소스·서명 결과 게시
- [ ] 계정·MFA·서명 담당자 설정 및 신청 제출

## 패키지 메타데이터 목록

잠금 파일의 설치 버전을 대조한 목록이다. 개발 도구도 포함하며, 최종 번들의 네이티브 하위 구성요소 전체 목록은 아니다. SPDX 표현식이 없는 경우 배포자가 적은 라벨을 유지한다. FMOD 래퍼의 MIT는 엔진 DLL의 라이선스가 아니다.

| 패키지 | 버전 | 배포 메타데이터의 라이선스 |
| --- | --- | --- |
| altgraph | 0.17.5 | MIT |
| archspec | 0.2.6 | Apache-2.0 OR MIT |
| astc-encoder-py | 0.1.12 | MIT License |
| attrs | 26.1.0 | MIT |
| brotli | 1.2.0 | MIT |
| cffi | 2.1.1 | MIT-0 |
| colorama | 0.4.6 | BSD License |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| etcpak | 0.9.15 | MIT License |
| fmod_toolkit | 0.1.3 | MIT License |
| fsspec | 2026.9.0 | BSD-3-Clause |
| greenlet | 3.5.6 | MIT AND PSF-2.0 |
| iniconfig | 2.3.1 | MIT |
| lz4 | 4.4.5 | BSD License |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pefile | 2024.8.26 | MIT |
| pillow | 12.3.0 | MIT-CMU |
| playwright | 1.63.0 | Apache-2.0 |
| pluggy | 1.6.0 | MIT |
| psutil | 7.2.2 | BSD-3-Clause |
| pycparser | 3.11 | BSD-3-Clause |
| pyee | 13.0.1 | MIT |
| pyfmodex | 0.7.2 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| pyinstaller | 6.22.3 | GPL-2.0-or-later + bootloader distribution exception |
| pyinstaller-hooks-contrib | 2026.8 | Apache Software License; GNU General Public License v2 (GPLv2) |
| PySide6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Addons | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Essentials | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Pdf | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_WebEngine | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| pytest | 9.1.1 | MIT |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause |
| setuptools | 84.0.0 | MIT |
| shiboken6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| texture2ddecoder | 1.0.6 | MIT License |
| tpk_ar | 0.2.4 | MIT License |
| typing_extensions | 4.16.0 | PSF-2.0 |
| UnityPy | 1.25.4 | MIT License |
