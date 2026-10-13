# 디자인 이미지 생성 기록

2026-10-13 내장 `imagegen`으로 생성했다. 실제 게임 아트나 사용자 사진을 입력하지 않았다. 아래 문장은 최종 생성 요청 원문이며 로컬 경로는 저장소 상대 경로로 기록한다. `desktop-concept-dark.png`와 `cat-avatars.png`는 라이트 시안을 참조했다.

## 라이트 화면

출력: `assets/desktop-concept.png`. 신규 생성, 불투명 배경.

```text
Use case: ui-mockup.
Create one exceptional, production-quality desktop messenger interface concept for "Bongo Cat Chat", a Korean-language companion app for the existing Bongo Cat game lobby chat. This is the complete primary app screen, not a landing page or promotional poster. Flat straight-on screenshot, 1536 x 1024 landscape, no device frame, no presentation captions outside the app. Do not add shadows around an outer browser, desktop wallpaper, or a hero section.

Art direction: calm, refined desktop messenger. Crisp true-white conversation surface #ffffff, a very pale cool-gray sidebar #f6f7f9, charcoal text #252832, muted cool-gray supporting text, thin #e9eaef separators. Restrained dusty violet #7770b8 accent, pale lavender #efedf8 own-message bubbles. Meticulous spacing, refined Pretendard / Korean sans-serif typography, generous but functional density, tiny consistent 1.6px outline icons, subtle 12px radii only where appropriate. Premium desktop software, not a wireframe, not neon, not glassmorphism, not a gamer dashboard. Small charming original hand-illustrated cat portraits are the only playful element.

Layout: exactly two panes. A 260px-wide left sidebar from top to bottom, and a wide conversation area. No permanent right sidebar. Left: simple cat-outline mark and "Bongo Cat Chat" at top, a small clearly visible sidebar-collapse icon. Below, search field labeled "대화 검색" with magnifier and Ctrl K hint. Section label "현재 로비", one selected lobby row "느긋한 오후" with a rounded small lavender cat-themed lobby icon and supporting "13명과 함께 이야기 중". Section label "보관한 대화", two quieter rows "새벽 작업실" with "어제" and "고양이의 거실" with "10월 11일". Bottom left own cat avatar with name "오늘의고양이" and quiet supporting "Bongo Cat 연결됨", a small settings icon. Keep this sidebar airy and tightly aligned.

Conversation header at upper left: "느긋한 오후" in 22px semibold, below a green dot and "게임과 연결됨". Upper right: a subtle inline group of three tiny cat portraits plus "13명", then a search icon and refresh icon. Header is 94px high, with a thin bottom rule.
Messages occupy the middle of the screen in a calm, spacious scrollable column with 42px horizontal gutters, max width about 960px. At top a discreet centered divider "2026년 10월 13일". All participants must use original illustrated cat avatars, not human/Steam photos, not blank circles. Incoming message groups have a 40px cat avatar on the left, display name in medium dark text and tiny timestamp on one line, message bubble below in very light neutral gray with dark text. Outgoing group aligns right and includes display name "오늘의고양이" and a tiny "나" suffix with own cat avatar on the right, own bubble pale lavender, never saturated.
Exact conversation, in order:
모찌 · 오후 1:24 : "다들 오늘 어떤 모자 쓰고 있어요?"
구름 · 오후 1:25 : "저는 드디어 식빵 모자 얻었어요."
오늘의고양이 나 · 오후 1:25 : "고양이들이 모여 있으니까 보기 좋네요."
밤고양이 · 오후 1:26 : "여기서 같이 느긋하게 놀아요."
라떼 · 오후 1:26 : "이 방 분위기 좋네요."
Use original minimal 2D white, oatmeal, charcoal and peach cats; one cat wears a tiny green leaf, one a small beige toast hat, another a soft purple cap. These are design placeholders, not extracted game art.

Composer anchored at bottom inside conversation pane, generous gutter, a single wide softly outlined 2-line-capable input surface with exact placeholder "느긋한 오후에 메시지 보내기". Small violet square send button with simple arrow icon on the right. Below outside input, subtle text "Enter로 전송 · Shift + Enter로 줄바꿈" at left and "이 기기에 대화 보관" with a tiny outlined storage icon at right. NO attachments, emoji picker, stickers, voice/video controls, reactions, typing indicators or read receipts. NO app-level hide/mute/block buttons; the future app automatically follows the game's hide setting. No sample content from real people.

All text, buttons, controls, dividers and panels must be practical native HTML/CSS elements in the implementation, clearly separated from avatar art. Information architecture must remain exactly this existing-lobby messenger; no friends tab, new server creation, room joining, account login, unrelated dashboards, stats or invented features. Prioritize excellent full-screen composition, readable Korean, restrained color, real desktop-messenger credibility and a refined input area.
```

## 고양이 프로필 예시

출력: `assets/cat-avatars.png`. 라이트 시안 참조, 투명 배경.

```text
Use case: precise-object-edit / supporting ui-mockup asset extraction.
From the reference messenger concept, create a standalone production avatar sprite sheet containing ONLY the four original illustrated cat portraits. Preserve the concept's delicate black outline, soft watercolor-like shading, pink cheeks, friendly tiny eyes and refined 2D style. These are original mockup avatars, not official game assets.
Output a square transparent PNG, exactly a 2 by 2 equal cell grid. Each cell occupies exactly one quarter, with its cat centered at that cell's center and a consistent visible diameter about 82 percent of that cell. Absolutely no text, labels, card backgrounds, circles, dividing lines, shadows behind the sheet, app UI, or checkerboard drawn into the image. Real alpha transparency.
Top-left: white cat with tiny green sprout atop its head, matching the white cat in the reference.
Top-right: oatmeal tabby cat with small toast slice hat, matching the toast cat.
Bottom-left: charcoal cat wearing soft lavender baseball cap, matching the purple-cap cat.
Bottom-right: peach-and-cream cat with no hat, matching the last sender.
Include heads and tiny shoulders/paws just as the reference. Keep ears, hats, sprouts and whiskers fully inside their own cell, consistently centered and sized. This sheet will be displayed with four CSS background positions, so exact equal cell boundaries and generous transparent separation matter. Do not include any full interface elements.
```

## 다크 화면

출력: `assets/desktop-concept-dark.png`. 라이트 시안 참조, 불투명 배경.

```text
Use case: ui-mockup style variant. Create the DARK MODE counterpart of the supplied Bongo Cat Chat desktop messenger concept. Preserve its EXACT two-pane layout, relative dimensions, typography hierarchy, wording in Korean, order of all five messages, original cat avatars, icon metaphors, generous whitespace, composer geometry and sidebar items. Do not redesign or add components. This is one flat full-app screenshot, landscape 1536 x 1024, no framing or labels outside the app.
Change only the theme: conversation background deep ink #1b1d25, sidebar darker #15171e, primary text #e7e9f0, secondary text #a2a7b9, separators #30333f, incoming message surfaces #272a35, pale lavender outgoing message transformed to quiet dark violet #353044 with near-white text, active lobby #302b42, restrained accent #a59ad9, composer #20232d with a gentle gray border, violet send control. Keep the small green connection dot. Avoid pure black expanses, neon, glow, shiny gradients and excessive contrast. Maintain clear readable body text and understated hierarchy.
Cat artwork must remain the same original illustrated cats with colors intact, not negative/inverted, with a subtle small dark-gray circular backing when needed for charcoal-cat visibility. Sidebar still has exactly Bongo Cat Chat, 대화 검색, 현재 로비, 느긋한 오후, 13명과 함께 이야기 중, 보관한 대화, 새벽 작업실, 어제, 고양이의 거실, 10월 11일, 오늘의고양이, Bongo Cat 연결됨.
Header "느긋한 오후", "게임과 연결됨", "13명". Date "2026년 10월 13일".
Messages unchanged:
모찌 · 오후 1:24 : "다들 오늘 어떤 모자 쓰고 있어요?"
구름 · 오후 1:25 : "저는 드디어 식빵 모자 얻었어요."
오늘의고양이 나 · 오후 1:25 : "고양이들이 모여 있으니까 보기 좋네요."
밤고양이 · 오후 1:26 : "여기서 같이 느긋하게 놀아요."
라떼 · 오후 1:26 : "이 방 분위기 좋네요."
Composer: "느긋한 오후에 메시지 보내기"; bottom "Enter로 전송 · Shift + Enter로 줄바꿈" and "이 기기에 대화 보관".
No new controls or features; light and dark will share identical native HTML/CSS components. This image is the strict dark-theme reference.
```
