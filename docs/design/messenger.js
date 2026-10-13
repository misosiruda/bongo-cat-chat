(() => {
  'use strict';

  // This standalone design preview has no game or Steam transport.
  const STORAGE_KEY = 'bongo-cat-chat.design.v2';
  const THEMES = ['light', 'dark', 'system'];
  const ROOM_IDS = ['room-live', 'room-dawn', 'room-living', 'room-next'];
  const $ = (id) => document.getElementById(id);
  const darkPreference = matchMedia('(prefers-color-scheme: dark)');
  const narrowWindow = matchMedia('(max-width: 760px)');
  let saved = {};
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    if (value && typeof value === 'object' && !Array.isArray(value)) saved = value;
  } catch { /* Storage can be unavailable when opening a local file. */ }

  const people = [
    { id: 'self', name: '오늘의고양이', cat: 'sprout' },
    { id: 'mochi', name: '모찌', cat: 'sprout' },
    { id: 'cloud', name: '구름', cat: 'toast' },
    { id: 'night', name: '밤고양이', cat: 'night' },
    { id: 'latte', name: '라떼', cat: 'peach' },
    { id: 'walnut', name: '호두', cat: 'toast' },
    { id: 'socks', name: '양말', cat: 'night' },
    { id: 'coco', name: '코코', cat: 'peach' },
    { id: 'tofu', name: '두부', cat: 'sprout' },
    { id: 'dawn', name: '새벽', cat: 'night' },
    { id: 'barley', name: '보리', cat: 'toast' },
    { id: 'cotton', name: '솜이', cat: 'sprout' },
    { id: 'dalgona', name: '달고나', cat: 'peach' },
  ];
  const rooms = {
    'room-live': { name: '느긋한 오후', cat: 'sprout', date: '2026년 10월 13일', label: '오늘', people: people.map((person) => person.id), messages: [
      { person: 'mochi', time: '오후 1:24', text: '다들 오늘 어떤 모자 쓰고 있어요?' },
      { person: 'cloud', time: '오후 1:25', text: '저는 드디어 식빵 모자 얻었어요.' },
      { person: 'self', time: '오후 1:25', text: '고양이들이 모여 있으니까 보기 좋네요.' },
      { person: 'night', time: '오후 1:26', text: '여기서 같이 느긋하게 놀아요.' },
      { person: 'latte', time: '오후 1:26', text: '이 방 분위기 좋네요.' },
    ] },
    'room-dawn': { name: '새벽 작업실', cat: 'night', date: '2026년 10월 12일', label: '어제', people: ['self', 'night', 'cloud'], messages: [
      { person: 'night', time: '오후 11:04', text: '조용히 작업하기 좋은 밤이네요.' },
      { person: 'self', time: '오후 11:05', text: '오늘도 고양이와 함께 마무리해요.' },
      { person: 'cloud', time: '오후 11:08', text: '모두 편안한 밤 보내세요.' },
    ] },
    'room-living': { name: '고양이의 거실', cat: 'peach', date: '2026년 10월 11일', label: '10월 11일', people: ['self', 'latte'], messages: [
      { person: 'latte', time: '오후 3:10', text: '잠깐 쉬었다 가요.' },
      { person: 'self', time: '오후 3:12', text: '따뜻한 차 한 잔 가져왔어요.' },
    ] },
    'room-next': { name: '초록빛 작업실', cat: 'toast', date: '2026년 10월 13일', label: '오늘', people: ['self', 'cloud', 'latte'], messages: [] },
  };
  const state = {
    theme: THEMES.includes(saved.theme) ? saved.theme : 'system',
    collapsed: saved.collapsed === true,
    drafts: Object.fromEntries(ROOM_IDS.map((id) => [id, typeof saved.drafts?.[id] === 'string' ? saved.drafts[id].slice(0, 4000) : ''])),
    selected: 'room-live', live: 'room-live', scene: 'connected', query: '',
    composing: false, refreshTimer: null, toastTimer: null,
  };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#i-${name}`);
    svg.append(use);
    return svg;
  }

  function avatar(cat, description) {
    const node = element('span', `avatar cat-${cat}`);
    if (description) { node.setAttribute('role', 'img'); node.setAttribute('aria-label', description); }
    else node.setAttribute('aria-hidden', 'true');
    return node;
  }

  function persist() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 2, theme: state.theme, collapsed: state.collapsed, drafts: state.drafts }));
    } catch { /* Keep the current session functional without persistent storage. */ }
  }

  function toast(text) {
    clearTimeout(state.toastTimer);
    $('toast').textContent = text;
    $('toast').hidden = false;
    state.toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3000);
  }

  function applyTheme() {
    document.documentElement.dataset.theme = state.theme === 'system' ? (darkPreference.matches ? 'dark' : 'light') : state.theme;
    $('preview-theme').value = state.theme;
    document.querySelectorAll('input[name="appearance"]').forEach((input) => { input.checked = input.value === state.theme; });
    $('theme-note').textContent = state.theme === 'system' ? '시스템의 밝기 설정을 따릅니다.' : `${state.theme === 'dark' ? '다크' : '라이트'} 모드를 사용합니다.`;
  }

  function chooseTheme(value) {
    if (!THEMES.includes(value)) return;
    state.theme = value;
    applyTheme();
    persist();
  }

  function updateSidebar() {
    $('app').classList.toggle('is-collapsed', state.collapsed);
    const collapsed = state.collapsed && !narrowWindow.matches;
    $('sidebar-toggle').setAttribute('aria-label', narrowWindow.matches ? '사이드바 닫기' : (collapsed ? '사이드바 펼치기' : '사이드바 접기'));
    $('sidebar-toggle').setAttribute('aria-expanded', String(!collapsed));
    $('sidebar-toggle').replaceChildren(icon(collapsed ? 'expand' : 'collapse'));
    $('sidebar').inert = narrowWindow.matches && !$('app').classList.contains('is-drawer-open');
  }

  function drawer(open, restoreFocus = false) {
    $('app').classList.toggle('is-drawer-open', open);
    $('drawer-backdrop').hidden = !open;
    $('mobile-menu').setAttribute('aria-expanded', String(open));
    $('sidebar').inert = narrowWindow.matches && !open;
    document.querySelector('.conversation').inert = open && narrowWindow.matches;
    if (open) $('sidebar-toggle').focus();
    else if (restoreFocus && narrowWindow.matches) $('mobile-menu').focus();
  }

  function focusSearch() {
    if (narrowWindow.matches) drawer(true);
    else if (state.collapsed) { state.collapsed = false; updateSidebar(); persist(); }
    $('message-search').focus();
  }

  const isHidden = (id) => state.scene === 'hidden' && id === 'night';
  const visiblePeople = (roomId = state.selected) => people.filter((person) => rooms[roomId].people.includes(person.id) && !isHidden(person.id));
  const canSend = () => state.selected === state.live && (state.scene === 'connected' || state.scene === 'hidden');

  function renderRooms() {
    const createRoom = (id) => {
      const room = rooms[id];
      const live = id === state.live;
      const button = element('button', `room-button${live ? ' is-live' : ''}`);
      button.type = 'button';
      button.dataset.room = id;
      button.title = room.name;
      button.setAttribute('aria-label', `${room.name}, ${live ? '현재 로비' : '보관한 대화'}`);
      if (id === state.selected) button.setAttribute('aria-current', 'page');
      const info = element('span', 'room-info');
      info.append(element('span', 'room-name', room.name));
      if (live) info.append(element('span', 'room-detail', `${visiblePeople(id).length}명과 함께 이야기 중`));
      button.append(avatar(room.cat), info);
      if (!live) button.append(element('span', 'room-date', room.label));
      button.addEventListener('click', () => selectRoom(id));
      return button;
    };
    $('live-rooms').replaceChildren(createRoom(state.live));
    const archives = ['room-live', 'room-dawn', 'room-living'].filter((id) => id !== state.live);
    $('archived-rooms').replaceChildren(...archives.map(createRoom));
  }

  function renderParticipants() {
    const list = visiblePeople();
    $('member-count').textContent = `${list.length}명`;
    $('participants-button').setAttribute('aria-label', `${state.selected === state.live ? '참여자' : '보관된 대화 참여자'} ${list.length}명 보기`);
    document.querySelector('.avatar-stack').replaceChildren(...list.filter((person) => person.id !== 'self').slice(0, 3).map((person) => avatar(person.cat)));
    $('participants-description').textContent = `${rooms[state.selected].name} · ${state.selected === state.live ? '함께 있는' : '기록에 있는'} 고양이 ${list.length}마리`;
    $('participant-list').replaceChildren(...list.map((person) => {
      const item = element('li');
      item.append(avatar(person.cat), element('span', 'participant-name', `${person.name}${person.id === 'self' ? ' · 나' : ''}`));
      return item;
    }));
  }

  function highlight(text) {
    const fragment = document.createDocumentFragment();
    const query = state.query.trim().toLocaleLowerCase('ko');
    if (!query) { fragment.append(text); return fragment; }
    const lower = text.toLocaleLowerCase('ko');
    let start = 0;
    let found = lower.indexOf(query, start);
    while (found !== -1) {
      fragment.append(text.slice(start, found), element('mark', '', text.slice(found, found + query.length)));
      start = found + query.length;
      found = lower.indexOf(query, start);
    }
    fragment.append(text.slice(start));
    return fragment;
  }

  function renderMessages({ bottom = false, preserveScroll = false } = {}) {
    const scrollTop = $('message-scroll').scrollTop;
    const room = rooms[state.selected];
    const query = state.query.trim().toLocaleLowerCase('ko');
    const messages = room.messages.filter((message) => {
      const person = people.find((item) => item.id === message.person);
      return !isHidden(message.person) && (!query || `${person.name}\n${message.text}`.toLocaleLowerCase('ko').includes(query));
    });
    $('message-list').replaceChildren();
    $('message-list').hidden = messages.length === 0;
    $('empty-state').hidden = messages.length > 0;
    $('empty-title').textContent = query ? '검색 결과가 없어요' : '대화를 기다리고 있어요';
    $('empty-description').textContent = query ? '다른 단어나 이름으로 찾아보세요.' : '이 로비에서 받은 대화가 여기에 표시돼요.';
    $('search-status').hidden = !query;
    $('search-summary').textContent = query ? `“${state.query.trim()}” · ${messages.length}개의 메시지` : '';
    if (messages.length) {
      const date = element('div', 'date-divider', room.date);
      date.setAttribute('role', 'presentation');
      $('message-list').append(date);
    }
    messages.forEach((message) => {
      const person = people.find((item) => item.id === message.person);
      const own = person.id === 'self';
      const row = element('article', `message${own ? ' is-own' : ''}`);
      row.setAttribute('role', 'listitem');
      const content = element('div', 'message-content');
      const meta = element('div', 'message-meta');
      const name = element('strong');
      name.append(highlight(person.name));
      meta.append(name);
      if (own) meta.append(element('span', 'self-tag', '나'));
      const dot = element('span', 'meta-dot', '·');
      dot.setAttribute('aria-hidden', 'true');
      meta.append(dot, element('span', '', message.time));
      const bubble = element('div', 'message-bubble');
      bubble.append(highlight(message.text));
      content.append(meta, bubble);
      if (message.preview) content.append(element('span', 'message-status', '미리보기'));
      const copy = element('button', 'message-copy');
      copy.type = 'button';
      copy.setAttribute('aria-label', `${person.name} 메시지 복사`);
      copy.title = '메시지 복사';
      copy.append(icon('copy'));
      copy.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(message.text);
          toast('메시지를 복사했어요.');
        } catch {
          const selection = getSelection();
          const range = document.createRange();
          range.selectNodeContents(bubble);
          selection.removeAllRanges();
          selection.addRange(range);
          toast('문장을 선택했어요. Ctrl/Cmd + C로 복사하세요.');
        }
      });
      row.append(avatar(person.cat, `${person.name}의 고양이 예시`), content, copy);
      $('message-list').append(row);
    });
    if (bottom) $('message-scroll').scrollTop = $('message-scroll').scrollHeight;
    else $('message-scroll').scrollTop = preserveScroll ? scrollTop : 0;
  }

  function sizeInput() {
    $('message-input').style.height = 'auto';
    $('message-input').style.height = `${Math.min(170, $('message-input').scrollHeight)}px`;
  }

  function updateComposer() {
    const available = canSend();
    const archived = state.selected !== state.live;
    $('message-input').disabled = !available;
    $('send-button').disabled = !available || !$('message-input').value.trim();
    $('message-form').classList.toggle('is-unavailable', !available);
    $('message-input').placeholder = available ? `${rooms[state.selected].name}에 메시지 보내기` : archived ? '보관한 대화는 읽기 전용이에요' : '게임 연결을 확인하고 있어요';
    $('composer-help').textContent = available ? 'Enter로 전송 · Shift + Enter로 줄바꿈' : archived ? '현재 로비에서 대화를 이어갈 수 있어요' : '연결되면 이 로비에서 대화를 이어갈 수 있어요';
  }

  function updateStatus() {
    const archived = state.selected !== state.live;
    const disconnected = state.scene === 'disconnected';
    const switching = state.scene === 'switching';
    $('room-title').textContent = rooms[state.selected].name;
    $('connection-label').lastElementChild.textContent = archived ? '보관한 대화 · 읽기 전용' : disconnected ? '게임 연결 끊김' : switching ? '로비 이동 중' : '게임과 연결됨';
    $('connection-label').firstElementChild.style.background = archived || disconnected ? 'var(--muted)' : switching ? 'var(--amber)' : 'var(--green)';
    $('account-status').textContent = disconnected ? '게임 연결 끊김' : switching ? '로비 이동 중' : 'Bongo Cat 연결됨';
    document.querySelector('.account-copy .status-dot').style.background = disconnected ? 'var(--muted)' : switching ? 'var(--amber)' : 'var(--green)';
    const notice = disconnected ? '게임과 연결이 끊어졌어요. 대화와 초안은 그대로 남아 있어요.' : switching ? '새 로비를 확인하고 있어요. 이전 로비의 초안은 보관돼요.' : state.scene === 'hidden' ? '게임에서 숨긴 1명의 대화가 제외됐어요.' : '';
    $('connection-notice').textContent = notice;
    $('connection-notice').hidden = !notice;
    $('preview-scene').value = state.scene;
    updateComposer();
    renderParticipants();
  }

  function saveDraft() {
    state.drafts[state.selected] = $('message-input').value.slice(0, 4000);
    persist();
  }

  function selectRoom(id) {
    saveDraft();
    state.selected = id;
    $('message-input').value = state.drafts[id];
    renderRooms();
    updateStatus();
    renderMessages();
    sizeInput();
    if (narrowWindow.matches) drawer(false, true);
  }

  function changeScene(scene) {
    clearTimeout(state.refreshTimer);
    $('refresh-button').classList.remove('is-refreshing');
    $('refresh-button').disabled = false;
    saveDraft();
    state.scene = scene;
    if (scene === 'connected') {
      state.live = 'room-live';
      state.selected = state.live;
      $('message-input').value = state.drafts[state.selected];
    }
    renderRooms();
    updateStatus();
    renderMessages({ preserveScroll: true });
    sizeInput();
  }

  $('preview-theme').addEventListener('change', (event) => chooseTheme(event.target.value));
  document.querySelectorAll('input[name="appearance"]').forEach((input) => input.addEventListener('change', () => chooseTheme(input.value)));
  darkPreference.addEventListener('change', () => { if (state.theme === 'system') applyTheme(); });
  $('sidebar-toggle').addEventListener('click', () => {
    if (narrowWindow.matches) drawer(false, true);
    else { state.collapsed = !state.collapsed; updateSidebar(); persist(); }
  });
  $('mobile-menu').addEventListener('click', () => drawer(true));
  $('drawer-backdrop').addEventListener('click', () => drawer(false, true));
  narrowWindow.addEventListener('change', () => { drawer(false); updateSidebar(); });
  $('header-search').addEventListener('click', focusSearch);
  $('sidebar-search-button').addEventListener('click', focusSearch);
  $('message-search').addEventListener('input', () => { state.query = $('message-search').value; renderMessages(); });
  $('clear-search').addEventListener('click', () => { state.query = ''; $('message-search').value = ''; renderMessages(); });
  $('preview-scene').addEventListener('change', (event) => changeScene(event.target.value));
  $('refresh-button').addEventListener('click', () => {
    $('refresh-button').classList.add('is-refreshing');
    $('refresh-button').disabled = true;
    state.refreshTimer = setTimeout(() => {
      if (state.scene === 'switching') {
        saveDraft();
        state.live = 'room-next';
        state.selected = state.live;
        state.scene = 'connected';
        $('message-input').value = state.drafts[state.selected];
      } else if (state.scene === 'disconnected') state.scene = 'connected';
      $('refresh-button').classList.remove('is-refreshing');
      $('refresh-button').disabled = false;
      renderRooms();
      updateStatus();
      renderMessages({ preserveScroll: true });
      sizeInput();
      toast('로비 확인을 완료했어요. (미리보기)');
    }, 650);
  });
  $('message-input').addEventListener('input', () => { saveDraft(); sizeInput(); updateComposer(); });
  $('message-input').addEventListener('compositionstart', () => { state.composing = true; });
  $('message-input').addEventListener('compositionend', () => { state.composing = false; saveDraft(); updateComposer(); });
  $('message-input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !state.composing && event.keyCode !== 229) {
      event.preventDefault();
      if (!event.repeat) $('message-form').requestSubmit();
    }
  });
  $('message-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const text = $('message-input').value.trim();
    if (!canSend() || !text || state.composing) return;
    rooms[state.selected].messages.push({ person: 'self', time: new Intl.DateTimeFormat('ko-KR', { hour: 'numeric', minute: '2-digit' }).format(new Date()), text, preview: true });
    $('message-input').value = '';
    saveDraft();
    sizeInput();
    updateComposer();
    renderMessages({ bottom: true });
    if (state.query && !`${people[0].name}\n${text}`.toLocaleLowerCase('ko').includes(state.query.trim().toLocaleLowerCase('ko'))) toast('미리보기 메시지가 추가됐어요. 검색을 지우면 볼 수 있어요.');
    $('message-input').focus();
  });
  $('settings-button').addEventListener('click', () => $('settings-dialog').showModal());
  $('participants-button').addEventListener('click', () => { renderParticipants(); $('participants-dialog').showModal(); });
  document.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  }));
  document.addEventListener('keydown', (event) => {
    if (document.querySelector('dialog[open]')) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); focusSearch(); }
    if (event.key === 'Escape') {
      if ($('app').classList.contains('is-drawer-open')) drawer(false, true);
      else if (state.query) { state.query = ''; $('message-search').value = ''; renderMessages(); }
    }
    if (event.key === 'Tab' && narrowWindow.matches && $('app').classList.contains('is-drawer-open')) {
      const controls = [...$('sidebar').querySelectorAll('button, input')].filter((node) => !node.disabled && node.getClientRects().length);
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });

  $('message-input').value = state.drafts[state.selected];
  applyTheme();
  updateSidebar();
  renderRooms();
  updateStatus();
  renderMessages();
  sizeInput();
})();
