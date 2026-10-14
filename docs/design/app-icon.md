# 앱 아이콘과 파비콘

2026-10-15 사용자 요청: 원래 Bongo Cat 아이콘에 말풍선을 더한다.

원작의 기울어진 하얀 고양이, 양쪽 앞발과 분홍 발바닥을 유지하고 메신저의 강조색인 보라색 말풍선과 흰 점 세 개를 더했다. 바깥은 투명하며 라이트·다크 테마에서 같은 그림을 사용한다.

## 원본과 출력

| 파일 | 용도 |
| --- | --- |
| `assets/bongo-cat-chat-master.png` | 내장 imagegen으로 만든 투명 고해상도 마스터 |
| `../../src/bongo_chat/ui/app-icon.png` | 256px 앱 내부 로고 |
| `../../src/bongo_chat/ui/app-icon.ico` | 16·20·24·32·40·48·64·96·128·256px Windows 창·EXE·설치/제거 프로그램 아이콘 |
| `../../src/bongo_chat/ui/favicon.ico` | 16·32·48px 파비콘 |

제품 UI와 디자인 미리보기는 동일한 출력 파일을 참조한다. Qt는 로컬 아이콘 파일을 사용하고, WebEngine의 기존 파일 허용 목록에는 로고 PNG와 파비콘만 추가한다. 게임 실행이나 원격 이미지 다운로드가 필요하지 않다. 두 PyInstaller EXE 및 NSIS 설치·제거 프로그램에도 같은 ICO를 사용한다.

마스터를 교체한 뒤 저장소 루트에서 `.venv/Scripts/python.exe tools/export_icons.py`로 출력 파일을 재생성한다. Pillow는 현재 잠금 의존성에 포함된다. 내보내기는 그림을 바꾸지 않고 크기와 파일 형식만 변환한다. ICO는 NSIS 호환 DIB 프레임으로 저장한다.

## 참조 자료와 생성

공개 [Bongo Cat Steam 페이지](https://store.steampowered.com/app/3419430/Bongo_Cat/)와 [커뮤니티 아이콘](https://shared.akamai.steamstatic.com/community_assets/images/apps/3419430/b25d4b846c745bdf809f5657af00298e0ae62465.jpg)을 확인했다. 실제 편집 참조는 설치된 `BongoCat.exe`의 아이콘 리소스를 읽기 전용으로 추출한 256px 그림이다. 게임 실행 파일을 수정하거나 저장소에 복사하지 않았다. 추출한 참조와 초기 시안은 Git에서 제외되는 로컬 작업 자료로만 유지한다.

아래 프롬프트로 내장 `image_gen`을 사용했다. 생성·편집한 마스터는 게임 원본 아이콘과 구분하며, 게임 이름·캐릭터의 권리는 해당 권리자에게 남는다. 이 변경이 공식 제품·개발사 승인 또는 타사 이미지의 MIT 재허가를 의미하지 않는다.

### 최초 편집 프롬프트

```text
Use case: precise-object-edit / logo-brand.
Asset type: Windows desktop application icon and browser favicon for Bongo Cat Chat.
Input image 1 is the edit target: the original Bongo Cat game icon extracted locally for visual reference.
Primary request: retain the original recognizable white Bongo Cat with its tilted head, two raised front paws, pink paw pads and pink ear interiors, round dark eyes and small cute mouth; add one clear chat speech bubble. Make the result polished and immediately recognizable at 16, 32, 48 and 256 pixels.
Keep the cat's identity and pose very close to the reference. Refine the soft low-resolution edges into smooth confident thick dark-charcoal outlines without changing the expression. Fit the entire visible head and two paws comfortably inside the canvas. Remove the salmon/peach square background completely; the surrounding canvas must be truly transparent.
Composition: a compact square icon, cat fills the lower two thirds, with one generously sized rounded speech bubble in the open space above and to the right, its short tail pointing toward the cat. Bubble must not cover the eyes or paws. Use muted rich lavender (#8178bb) for the bubble with three large evenly spaced white dots and a clean thick dark outline. Preserve the white cat, warm pink accents, and simple flat colors. Close spacing makes cat and bubble read as one silhouette; modest transparent outer padding.
Style: clean charming 2D mascot app icon, crisp flat artwork. No gradients, no shadows, no glow, no 3D, no glossy treatment, no surrounding badge, no text or lettering, no extra decorative shapes, no mockup. Only one finished icon on a square transparent canvas.
```

### 하단 윤곽 정리 프롬프트

```text
Use case: precise-object-edit.
Edit target: the supplied Bongo Cat Chat icon. Preserve the exact cat identity, tilted pose, raised pink paws, face, colors, lavender speech bubble, three white dots, and overall composition.
Make one targeted cleanup for a production app icon: fix the unfinished bottom edge. Replace the cropped open white bottom of the cat and all ragged detached white pixels underneath it with a single clean smooth dark outline forming a softly rounded closed bottom contour for the cat and paws. Keep that bottom contour well inside the square canvas with approximately 8 percent transparent padding below it. Preserve the existing head, face, paws, and speech bubble. Remove ALL stray pixels or speckles outside the icon, especially beneath it; outside the single clean icon silhouette must be completely transparent. The outlines must remain thick, crisp and smooth. No new objects, shadows, texture, lettering, background tile, or extra details. Flat colors and true transparent background.
```
