/* Native QWebChannel is the only transport. No sample data or network endpoint. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const media = matchMedia('(prefers-color-scheme: dark)');
  const narrow = matchMedia('(max-width: 760px)');
  let bridge, model = null, selected = '', account = '', query = '', before = null;
  let theme = 'system', collapsed = false, composing = false, sending = false, switching = 0;
  let refreshing = 0, requestVersion = 0, draftVersion = 0, draftTimer, signature = '';
  let deleteScope = null;
  const notificationSettings = {notification_flash:true,notification_toast:true};
  const notificationPending = new Set();
  const notificationControls = {notification_flash:'notification-flash',notification_toast:'notification-toast'};
  let restartPlan = null, restarting = false, lastEdit = 0;
  let openingProfile = false, participantsSignature = '';
  let start = null, seenSeq = null, loadingHistory = false, restoring = false;
  let seenVolatile = new Set(), searchPosition = null, pendingPosition = {bottom:true};
  const positions = new Map();
  const notices = {
    checking: 'Steam과 게임의 채팅·숨김 연동 구조를 확인하고 있어요.',
    searching_lobby: 'Bongo Cat의 현재 로비를 확인하고 있어요. 연결이 확인되면 대화를 불러옵니다.',
    discovering: '로비를 찾았어요. 현재 로비와 숨김 설정을 확인하는 동안 메시지를 미리 작성할 수 있어요.',
    discovery_failed: 'Steam 연결은 유지 중이에요. 현재 로비 검증을 다시 시도하고 있어요. 전송은 확인 후 사용할 수 있어요.',
    read_only: '읽기 전용으로 실행 중입니다. 메시지를 전송하지 않습니다.',
    no_lobby: '현재 게임 로비를 확인할 수 없어요. 게임에서 로비에 참여해 주세요.',
    hidden_unavailable: '로비 연결은 유지 중이에요. 숨김 설정을 확인할 수 없어 상대 대화 표시와 신규 저장을 보류하고 있어요.',
    hidden_syncing: '일부 참여자의 숨김 설정을 확인하고 있어요. 확인된 상대의 대화부터 표시하고 저장합니다.',
    unsupported_game_build: '채팅·숨김 연동 구조의 호환성을 확인하지 못했어요. 대응 앱 업데이트를 확인하고 있습니다.',
    game_files_changed: '게임 업데이트를 감지했어요. 연동 구조를 다시 확인하고 있습니다.',
    compatibility_tool_missing: '호환성 검사 파일이 없어 연결할 수 없어요. 앱을 다시 설치해 주세요.',
    compatibility_timeout: '호환성 검사에 시간이 걸리고 있어요. 연결을 보류하고 다시 확인합니다.',
    game_missing_or_ambiguous: '실행 중인 Bongo Cat 하나를 확인해야 연결할 수 있어요.',
    worker_stopped: '연결 작업자가 종료됐어요. 전송 결과가 불명확한 메시지는 다시 보내지 않습니다.',
    view_unavailable: '대화 상태를 조회하지 못해 표시와 전송을 중단했어요. 다시 확인하고 있습니다.',
    offline: '오프라인으로 실행 중입니다. 실제 게임과 연결하지 않습니다.',
  };
  const statuses = {pending: '전송 중', accepted: '전송됨 · Steam 접수', failed: '전송 실패', unknown: '전송 결과 확인 불가 · 자동 재전송 안 함'};
  const updateStatuses = {idle:'업데이트를 자동으로 확인합니다.', checking:'새 버전을 확인하고 있어요.',
    disabled:'GitHub 업데이트 통신을 껐습니다. Steam 채팅은 계속 사용할 수 있습니다.',
    downloading:'새 버전을 내려받고 있어요. 채팅을 계속 이용할 수 있습니다.', ready:'업데이트 준비 완료 · 다음 실행 때 적용합니다.',
    current:'최신 버전을 사용하고 있어요.', unavailable:'아직 받을 수 있는 정식 릴리스가 없습니다.',
    applied:'새 버전이 적용됐어요.', rolled_back:'새 버전이 시작되지 않아 이전 버전으로 돌아왔습니다.',
    apply_failed:'업데이트를 적용하지 못해 기존 버전을 유지했습니다.',
    network_error:'업데이트 서버에 연결하지 못했어요. 다음 확인 때 다시 시도합니다.',
    verification_failed:'업데이트를 확인하지 못했어요. 현재 버전을 유지합니다.',
    offline:'오프라인 실행 중에는 업데이트를 확인하지 않습니다.', development:'설치된 앱에서 자동 업데이트를 사용할 수 있습니다.'};
  function node(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#i-${name}`); svg.append(use); return svg;
  }
  function avatar(profile) {
    const el = node('span', 'avatar');
    if (profile?.avatar?.startsWith('data:image/png;base64,')) {
      const img = node('img'); img.src = profile.avatar; img.alt = '게임 스킨·모자 정지 프로필'; el.append(img);
    } else { el.append(icon('cat')); el.title = '고양이 외형 확인 불가'; }
    return el;
  }
  function rpc(action, args = {}) {
    return new Promise((resolve, reject) => bridge.request(JSON.stringify({action, ...args}), raw => {
      try { const result = JSON.parse(raw); if (result.error) reject(new Error(result.error)); else resolve(result); }
      catch (e) { reject(e); }
    }));
  }
  function toast(text) { $('toast').textContent = text; $('toast').hidden = false; setTimeout(() => { $('toast').hidden = true; }, 4000); }
  function applyTheme() {
    document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme;
    document.querySelectorAll('[name=appearance]').forEach(el => { el.checked = el.value === theme; });
    $('theme-note').textContent = theme === 'system' ? '시스템의 밝기 설정을 따릅니다.' : `${theme === 'dark' ? '다크' : '라이트'} 모드를 사용합니다.`;
  }
  function applySidebar() {
    $('app').classList.toggle('is-collapsed', collapsed);
    $('sidebar-toggle').setAttribute('aria-expanded', String(!collapsed));
    $('sidebar-toggle').setAttribute('aria-label', collapsed ? '사이드바 펼치기' : '사이드바 접기');
    $('sidebar-toggle').replaceChildren(icon(collapsed ? 'expand' : 'collapse'));
    if (narrow.matches) $('sidebar').inert = !$('app').classList.contains('is-drawer-open');
    else $('sidebar').inert = false;
  }
  function drawer(open) {
    $('app').classList.toggle('is-drawer-open', open); $('drawer-backdrop').hidden = !open;
    $('mobile-menu').setAttribute('aria-expanded', String(open)); applySidebar();
  }
  function focusSearch() {
    if (collapsed) { collapsed = false; applySidebar(); rpc('setting', {key:'collapsed',value:false}).catch(showError); }
    if (narrow.matches) drawer(true);
    $('message-search').focus();
  }
  function showError(error) {
    const text = ({connection_changed:'연결 대상이 변경되어 전송하지 않았어요. 초안은 원래 방에 남겨 두었습니다.',
      development_limit_50:'개발판에서는 50 UTF-16 단위 이내로 보내 주세요.',
      storage_failed_before_send:'기록을 저장하지 못해 전송하지 않았어요.',
      storage_failed:'저장에 실패했어요. 작성한 내용은 이 창에서 확인해 주세요.',
      legal_unavailable:'안내 파일을 열지 못했어요. 앱 파일을 복구하거나 다시 설치해 주세요.',
      invalid_steam_id:'프로필 대상을 확인하지 못했어요. 참여자 목록을 다시 확인해 주세요.',
      steam_profile_unavailable:'현재 연결에서 열 수 없는 프로필이에요. 참여자와 연결 상태를 확인해 주세요.',
      steam_profile_failed:'Steam 프로필을 열지 못했어요. Steam 실행 상태를 확인해 주세요.',
      update_permission_failed:'업데이트 통신 설정을 저장하지 못했어요. 기존 선택을 유지합니다.'})[error.message] || '요청을 완료하지 못했어요. 연결·저장 상태를 확인해 주세요.';
    toast(text);
  }
  function profileContext(context) {
    return JSON.stringify([context.account, context.lobby, context.generation]);
  }
  function profileAvailable(data, uid) {
    return typeof uid === 'string' && uid !== data.context.account && data.connected && data.lobby_verified
      && data.lobby === data.context.lobby && (data.profile_targets || []).includes(uid);
  }
  function updateProfileBusy() {
    document.querySelectorAll('.steam-profile-action').forEach(button => {
      button.setAttribute('aria-disabled', String(openingProfile || !!switching || restarting));
      button.setAttribute('aria-busy', String(openingProfile));
    });
  }
  async function openProfile(event, uid, context) {
    event.preventDefault(); event.stopPropagation();
    if (openingProfile || switching || restarting || event.detail > 1) return;
    if (!model || selected !== context.lobby || profileContext(context) !== profileContext(model.context)
        || !profileAvailable(model, uid)) {
      showError(new Error('steam_profile_unavailable')); return;
    }
    openingProfile = true; updateProfileBusy();
    try {
      await rpc('open_steam_profile', {steam_id:uid, context});
      toast('Steam에 프로필 열기를 요청했어요. 친구 추가는 Steam에서 진행해 주세요.');
    } catch (error) { showError(error); }
    finally { openingProfile = false; updateProfileBusy(); }
  }
  function profileButton(uid, profile, context, key, cls, content) {
    const button = node('button', `steam-profile-action ${cls}`);
    const captured = {...context}; // Preserve the action's original connection, including for detached events.
    button.type = 'button'; button.dataset.profileKey = key;
    button.dataset.profileContext = profileContext(captured);
    button.setAttribute('aria-label', `Steam 프로필 열기 · ${profile?.name || '참여자'}`);
    button.title = 'Steam 프로필 열기 · 친구 추가는 Steam에서 진행해 주세요';
    button.append(content);
    button.addEventListener('click', event => openProfile(event, uid, captured));
    return button;
  }
  function preserveProfileFocus(container) {
    const active = document.activeElement;
    if (!container.contains(active) || !active?.matches('.steam-profile-action')) return () => {};
    const key = active.dataset.profileKey, context = active.dataset.profileContext;
    return () => {
      const target = [...container.querySelectorAll('.steam-profile-action')].find(button =>
        button.dataset.profileKey === key && button.dataset.profileContext === context);
      const fallback = container === $('participant-list')
        ? document.querySelector('[aria-label="참여자 목록 닫기"]') : $('message-scroll');
      (target || fallback).focus({preventScroll:true});
    };
  }
  function renderParticipants(data, people) {
    const nextSignature = JSON.stringify([people, data.profile_targets, data.context, data.lobby, data.connected, data.lobby_verified]);
    if (participantsSignature === nextSignature) return;
    participantsSignature = nextSignature;
    const restoreFocus = preserveProfileFocus($('participant-list'));
    $('participant-list').replaceChildren(...people.map(([uid,p]) => {
      const li = node('li'), info = node('span', 'participant-info');
      info.append(node('span', 'participant-name', p.name));
      if (profileAvailable(data, uid)) info.append(profileButton(uid, p, data.context, `participant-${uid}`,
        'participant-profile', document.createTextNode('Steam 프로필 열기')));
      li.append(avatar(p), info); return li;
    }));
    restoreFocus();
  }
  function updateSend() {
    const text = $('message-input').value;
    $('send-button').disabled = !model?.can_send || composing || sending || switching || restarting || !text.trim() || text.length > 50;
    $('message-input').disabled = !selected || sending || switching || restarting;
    $('composer-help').textContent = `${text.length}/50 · Enter 전송 · Shift + Enter 줄바꿈`;
    $('message-form').classList.toggle('is-unavailable', !model?.can_send);
    updateProfileBusy();
  }
  async function saveDraft(text = $('message-input').value, room = selected, owner = account) {
    if (room && owner) await rpc('draft', {account:owner,lobby:room,text});
  }
  function updateRestartNotice(update) {
    const banner = $('update-notice');
    if (update.state !== 'ready' || !update.can_restart) {
      restartPlan = null; banner.hidden = true; return;
    }
    if (restartPlan?.version !== update.version) {
      restartPlan = {version:update.version, deadline:Date.now()+30000, retryAt:0, reason:''};
    }
    const seconds = Math.max(0, Math.ceil((Math.max(restartPlan.deadline,lastEdit+5000)-Date.now())/1000));
    let text = `새 버전 준비 완료 · ${seconds}초 후 자동 재시작합니다. 작성 중인 문장은 저장됩니다.`;
    if (composing || sending || switching || restartPlan.reason === 'sending') text = '새 버전 준비 완료 · 입력·전송이 끝나면 자동으로 재시작합니다.';
    if (restartPlan.reason === 'storage' || model?.storage_error) text = '저장되지 않은 내용이 있어 자동 재시작을 기다립니다. 저장 상태를 확인해 주세요.';
    if (restarting) text = '작성 중인 문장을 저장하고 업데이트를 적용하기 위해 재시작합니다.';
    banner.textContent = text; banner.hidden = false;
    $('update-status').textContent = text;
  }
  async function maybeRestart() {
    if (!restartPlan || restarting || refreshing || composing || sending || switching || model?.storage_error) return;
    if (Date.now() < Math.max(restartPlan.deadline,lastEdit+5000,restartPlan.retryAt)) return;
    restarting = true; document.body.inert = true; updateSend(); clearTimeout(draftTimer);
    updateRestartNotice(model.update);
    let accepted = false;
    try {
      await saveDraft();
      const result = await rpc('restart_update');
      accepted = result.ok === true;
      if (!accepted && restartPlan) {
        restartPlan.reason = result.reason;
        restartPlan.retryAt = Date.now() + (result.reason === 'sending' ? 1000 : 30000);
      }
    } catch (error) {
      if (restartPlan) {restartPlan.reason='storage'; restartPlan.retryAt=Date.now()+30000;}
      showError(error);
    } finally {
      if (!accepted) {
        restarting = false; document.body.inert = false; updateSend();
        updateRestartNotice(model.update);
      }
    }
  }
  function roomButton(room, live) {
    const button = node('button', `room-button${live ? ' is-live' : ''}`);
    button.title = room.name; button.setAttribute('aria-label', room.name);
    if (selected === room.lobby) button.setAttribute('aria-current', 'page');
    button.append(avatar(null));
    const info = node('span', 'room-info'); info.append(node('span','room-name',room.name),node('span','room-detail', live ? '현재 게임 로비' : `${room.segments}개 연결 구간 · 보관 기록`));
    button.append(info); button.addEventListener('click', () => changeRoom(room.lobby)); return button;
  }
  function atBottom() {
    const scroll = $('message-scroll');
    return scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 2;
  }
  function capturePosition() {
    const scroll = $('message-scroll'), rect = scroll.getBoundingClientRect();
    const row = [...$('message-list').children].find(el => el.classList.contains('message') && el.getBoundingClientRect().bottom > rect.top);
    return {id:row?.id, offset:row ? row.getBoundingClientRect().top - rect.top : 0,
      top:scroll.scrollTop, bottom:atBottom() && !model?.has_newer && !query};
  }
  function captureTimeline() {
    return {start, position:capturePosition(), seenSeq, seenVolatile:[...seenVolatile]};
  }
  function resetTimeline(saved) {
    start=saved?.start ?? null; before=null; seenSeq=saved?.seenSeq ?? null;
    seenVolatile=new Set(saved?.seenVolatile || []);
    pendingPosition=saved?.position || {bottom:true}; signature=''; searchPosition=null;
  }
  function viewArgs(extra={}) {
    return {lobby:selected, account, query, before:query ? before : null,
      start:query ? null : start, seen:seenSeq, limit:query || start===null ? 100 : 1000, ...extra};
  }
  function updateNavigation() {
    if (!model) return;
    const latestBottom = atBottom() && !model.has_newer && !query;
    if (latestBottom) {
      seenSeq=Math.max(seenSeq || 0, model.latest_seq || 0);
      seenVolatile=new Set(model.volatile_peer_ids || []); model.unseen=false; model.unseen_seq=0;
    }
    const unread = !query && ((model.unseen_seq || 0) > (seenSeq || 0) || (model.volatile_peer_ids || []).some(id => !seenVolatile.has(id)));
    $('new-messages').hidden=latestBottom || !unread;
    $('latest').hidden=latestBottom || unread;
    $('latest').textContent=query || model.has_newer ? '최근 대화로' : '맨 아래로';
    $('older').hidden=!model.has_more;
    $('older').disabled=loadingHistory;
    $('older').textContent=loadingHistory ? '이전 대화 불러오는 중…' : '이전 대화 불러오기';
  }
  function restorePosition(position) {
    const scroll=$('message-scroll'); restoring=true;
    const row=position.id && document.getElementById(position.id);
    if (position.bottom && !query) scroll.scrollTop=scroll.scrollHeight;
    else if (row) scroll.scrollTop += row.getBoundingClientRect().top - scroll.getBoundingClientRect().top - position.offset;
    else scroll.scrollTop=position.top || 0;
    restoring=false; updateNavigation();
  }
  async function loadOlder() {
    if (loadingHistory || switching || !model?.has_more) return;
    const first=model.messages.find(message => Number.isInteger(message.seq))?.seq;
    if (!first) return;
    const version=++requestVersion; loadingHistory=true; updateNavigation();
    try {
      if (query) {before=first; pendingPosition={top:0}; signature=''; await refresh(true);}
      else {
        const page=await rpc('view',viewArgs({before:first,start:null,limit:100}));
        if (version!==requestVersion) return;
        const older=page.messages.find(message => Number.isInteger(message.seq));
        if (older) start=older.seq;
        pendingPosition=capturePosition(); signature=''; await refresh(true);
      }
    } catch(e) {showError(e);}
    finally {loadingHistory=false; updateNavigation();}
  }
  async function loadNewer() {
    if (loadingHistory || switching || query || !model?.has_newer) return;
    const rows=model.messages.filter(message => Number.isInteger(message.seq));
    if (!rows.length) return;
    loadingHistory=true; requestVersion++;
    start=rows[Math.max(0,rows.length-100)].seq;
    pendingPosition={...capturePosition(),bottom:false}; signature='';
    try {await refresh(true);} finally {loadingHistory=false; updateNavigation();}
  }
  async function goLatest() {
    requestVersion++; query=''; $('message-search').value=''; resetTimeline();
    await refresh(true);
  }
  function changeSearch(value) {
    if (value && !query) searchPosition=captureTimeline();
    if (!value) {const saved=searchPosition; query=''; resetTimeline(saved);}
    else {query=value; before=null; pendingPosition={top:0}; signature='';}
    requestVersion++; refresh(true);
  }
  async function jumpToMessage(message) {
    const version=++requestVersion;
    try {
      const page=Number.isInteger(message.seq) ? await rpc('view',viewArgs({query:'',before:message.seq+1,start:null,limit:100})) : null;
      if (version!==requestVersion) return;
      const previousSeen=seenSeq, previousVolatile=seenVolatile;
      query=''; $('message-search').value=''; resetTimeline();
      seenSeq=previousSeen; seenVolatile=previousVolatile;
      start=page?.messages.find(row => Number.isInteger(row.seq))?.seq ?? null;
      pendingPosition={id:`message-${message.id}`,offset:$('message-scroll').clientHeight/2-50,top:0};
      await refresh(true);
    } catch(e) {showError(e);}
  }
  async function changeRoom(lobby) {
    if (switching || restarting) return;
    switching++; updateSend(); requestVersion++;
    positions.set(selected, query && searchPosition ? searchPosition : captureTimeline());
    clearTimeout(draftTimer);
    try {
      await saveDraft();
      selected = lobby; resetTimeline(positions.get(lobby));
      query = ''; $('message-search').value = ''; $('message-input').value = '';
      drawer(false); await refresh(true);
    } catch (e) { showError(e); }
    finally { switching--; updateSend(); }
  }
  function renderMessages(data, position) {
    const nextSignature = JSON.stringify([data.messages,data.profiles,data.hidden_ok,query,
      data.profile_targets,data.context,data.lobby,data.connected,data.lobby_verified]);
    if (signature === nextSignature) {if (pendingPosition) restorePosition(position); pendingPosition=null; updateNavigation(); return;}
    signature = nextSignature;
    const restoreFocus = preserveProfileFocus($('message-list'));
    $('message-list').replaceChildren();
    let day = '', segment = '';
    for (const message of data.messages) {
      const date = new Date(message.received*1000), label = date.toLocaleDateString('ko-KR');
      if (day !== label || segment !== message.session) {
        $('message-list').append(node('div','date-divider', `${label} · 앱이 수신한 기록${segment && segment !== message.session ? ' · 연결 공백 있음' : ''}`));
        day = label; segment = message.session;
      }
      const row = node('article', `message${message.own ? ' is-own' : ''}`);
      row.id = `message-${message.id}`; row.setAttribute('role','listitem');
      const profile = data.profiles[message.sender];
      const canOpen = !message.own && profileAvailable(data, message.sender);
      row.append(canOpen ? profileButton(message.sender, profile, data.context, `${message.id}-avatar`, 'profile-avatar', avatar(profile)) : avatar(profile));
      const content = node('div','message-content'), meta = node('div','message-meta');
      const name = node('strong','', profile?.name || message.name);
      meta.append(canOpen ? profileButton(message.sender, profile, data.context, `${message.id}-name`, 'profile-name', name) : name);
      if (message.own) meta.append(node('span','self-tag','나'));
      meta.append(node('time','',date.toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'})));
      const bubble = node('div','message-bubble');
      const index = query ? message.body.toLocaleLowerCase().indexOf(query.toLocaleLowerCase()) : -1;
      if (index >= 0) bubble.append(document.createTextNode(message.body.slice(0,index)),node('mark','',message.body.slice(index,index+query.length)),document.createTextNode(message.body.slice(index+query.length)));
      else bubble.textContent = message.body;
      content.append(meta,bubble);
      if (statuses[message.status] || message.unsaved) content.append(node('span','message-status',message.unsaved ? '이 기록은 저장되지 않았어요' : statuses[message.status]));
      if (query) {
        const jump = node('button','page-button','대화에서 보기');
        jump.addEventListener('click',() => jumpToMessage(message));
        content.append(jump);
      }
      row.append(content); $('message-list').append(row);
    }
    $('empty-state').hidden = data.messages.length > 0;
    $('empty-title').textContent = query ? '검색 결과가 없어요' : '대화를 기다리고 있어요';
    $('empty-description').textContent = data.hidden_ok ? '앱이 연결된 동안 받은 대화만 표시합니다.' : '게임의 숨김 상태를 확인하면 상대 대화를 표시합니다.';
    restoreFocus(); restorePosition(position); pendingPosition=null;
  }
  function render(data, resetDraft) {
    const position=pendingPosition || capturePosition();
    model = data;
    for (const [key,id] of Object.entries(notificationControls)) {
      if (!notificationPending.has(key)) {
        notificationSettings[key] = data.notifications?.[key] !== false;
        $(id).checked = notificationSettings[key];
      }
    }
    const notificationStatus = data.notification_status || {};
    $('notification-status').textContent = ({unavailable:'Windows 알림을 사용할 수 없어요. 설치된 앱의 시작 메뉴 바로가기를 확인해 주세요. 실패한 알림은 다시 보내지 않으며, 옵션을 껐다 켜면 다음 새 메시지부터 다시 시도합니다.',
      disabled:'Windows에서 이 앱의 알림을 제한하고 있어요. 표시 여부는 Windows 알림 설정을 따릅니다.',
      cleanup_failed:'이전 Windows 알림을 지우지 못했어요. 알림 센터에서 직접 지울 수 있습니다.'})[notificationStatus.toast] || '';
    if (notificationStatus.flash === 'unavailable') $('notification-status').textContent += ' 작업 표시줄 알림을 사용할 수 없어요.';
    if (seenSeq===null) {seenSeq=data.latest_seq || 0; seenVolatile=new Set(data.volatile_peer_ids || []);}
    if (!query && start===null) start=data.messages.find(message => Number.isInteger(message.seq))?.seq ?? null;
    const update = data.update || {state:'development',current:''};
    $('app-version').textContent = update.current ? `v${update.current}` : '';
    $('update-status').textContent = updateStatuses[update.state] || updateStatuses.verification_failed;
    $('check-updates').disabled = ['checking','downloading','offline','development','disabled'].includes(update.state);
    $('allow-update-checks').checked = update.allowed !== false;
    updateRestartNotice(update);
    theme = data.theme; collapsed = data.collapsed; applyTheme(); applySidebar();
    $('live-rooms').replaceChildren(); $('archived-rooms').replaceChildren();
    for (const room of data.rooms) (room.lobby === data.context.lobby ? $('live-rooms') : $('archived-rooms')).append(roomButton(room,room.lobby === data.context.lobby));
    const room = data.rooms.find(r => r.lobby === selected);
    $('room-title').textContent = room?.name || 'Bongo Cat Chat';
    const connected = data.connected;
    const connectionLabel = !data.lobby_verified ? '로비 발견 · 연결 확인 중' : !data.hidden_ok ? '게임과 연결됨 · 숨김 확인 중' : data.can_send ? '게임과 연결됨' : '게임 수신 연결됨';
    $('connection-label').querySelector('span').textContent = selected && selected !== data.context.lobby ? '보관 기록 · 읽기 전용' : connected ? connectionLabel : '연결 확인 중';
    document.querySelectorAll('.status-dot').forEach(el => el.classList.toggle('unavailable',!connected));
    let notice = data.notice ? notices[data.notice] || '게임 상태를 확인하지 못했어요. 연동을 중단하고 다시 확인하고 있습니다.' : '';
    if (data.notice === 'unsupported_game_build') {
      const build = /^[0-9]{1,12}$/.test(data.game_build || '') ? `게임 빌드 ${data.game_build}` : '현재 게임 파일';
      const progress = ({checking:'앱 업데이트를 확인하고 있어요.', downloading:'새 앱을 내려받고 있어요.',
        disabled:'GitHub 통신이 꺼져 있습니다. 앱 설정에서 업데이트 확인을 켤 수 있어요.',
        ready:data.update?.can_restart ? '새 앱이 준비됐어요. 잠시 후 자동으로 재시작합니다.' : '새 앱이 준비됐어요. 앱을 다시 실행하면 적용합니다.',
        offline:'오프라인 상태입니다.', development:'설치판에서 자동 업데이트를 사용할 수 있어요.',
        network_error:'업데이트 서버에 연결하지 못했어요. 자동으로 다시 확인합니다.',
        verification_failed:'업데이트를 검증하지 못했어요. 기존 앱을 유지합니다.'})[data.update?.state]
        || '아직 대응 버전이 없습니다. 앱 업데이트를 주기적으로 확인합니다.';
      notice = `${build}의 호환성을 확인하지 못해 연동을 중단했어요. ${progress}`;
    }
    $('connection-notice').textContent = notice || (!data.hidden_ok ? notices.hidden_unavailable : '개발판 · 읽지 않은 구간과 숨김 중 대화는 복원하지 않습니다.');
    $('connection-notice').hidden = false;
    $('storage-label').textContent = data.storage_error ? '저장 실패 · 일부 기록 미보관' : '이 기기에 30일 보관';
    document.querySelector('.account-copy strong').textContent = data.profiles[data.context.account]?.name || '계정 확인 중';
    $('account-status').textContent = connected ? (data.lobby_verified ? 'Bongo Cat 연결됨' : 'Steam 연결됨 · 로비 확인 중') : '연결 확인 중';
    const accountAvatar = document.querySelector('.account-avatar');
    const replacement = avatar(data.profiles[data.context.account]); replacement.classList.add('account-avatar'); accountAvatar.replaceWith(replacement);
    const people = Object.entries(data.profiles).sort(([a], [b]) => a.localeCompare(b));
    $('member-count').textContent = `${people.length}명`;
    $('participants-button').setAttribute('aria-label', `확인된 참여자 ${people.length}명 보기`);
    document.querySelector('.avatar-stack').replaceChildren(...people.slice(0,3).map(([,p])=>avatar(p)));
    renderParticipants(data, people);
    $('participants-description').textContent = '현재 로비에서 확인된 상대의 Steam 프로필을 엽니다. 친구 추가는 Steam에서 진행해 주세요. 게임의 숨김 설정을 따르며 외형 조회 실패는 기본 윤곽으로 표시합니다.';
    if (resetDraft) $('message-input').value = data.draft;
    $('message-input').placeholder = selected === data.context.lobby ? '메시지 입력' : '이 로비에 남겨 둘 초안';
    $('search-status').hidden=!query; $('search-summary').textContent=`현재 페이지 ${data.messages.length}개 결과`;
    // The history control changes the content height; settle it before restoring the anchor.
    $('older').hidden=!data.has_more;
    renderMessages(data,position); updateSend();
  }
  async function refresh(force=false) {
    if (restarting || refreshing && !force) return;
    const version = requestVersion, editing = draftVersion;
    let lockedEditor = false;
    refreshing++;
    try {
      let data = await rpc('view',viewArgs());
      if (version !== requestVersion) return;
      let reset = !model || data.lobby !== model.lobby;
      if (account !== data.context.account || model && model.context.lobby !== data.context.lobby && data.context.lobby) {
        // Freeze the old editor before awaiting its save. Input during the first
        // view request still belongs to the old room, never the new destination.
        switching++; lockedEditor=true; updateSend(); clearTimeout(draftTimer);
        await saveDraft();
        if (version !== requestVersion) return;
        if (account !== data.context.account) positions.clear();
        else positions.set(selected,query && searchPosition ? searchPosition : captureTimeline());
        account=data.context.account; selected=data.context.lobby; query=''; resetTimeline(positions.get(selected));
        $('message-search').value=''; $('message-input').value=''; signature=''; reset=true;
        data=await rpc('view',viewArgs());
      } else if (!selected && data.context.lobby) {selected=data.context.lobby; reset=true;}
      if (version !== requestVersion) return;
      render(data,reset && (switching || editing === draftVersion));
    } catch (e) {
      if (version === requestVersion) {
        if (model) render({...model,state:'unavailable',notice:'view_unavailable',connected:false,lobby_verified:false,privacy_ready:false,hidden_ok:false,can_send:false,messages:[],profiles:{},has_more:false,has_newer:false,unseen:false,unseen_seq:0,volatile_peer_ids:[]},false);
        showError(e); $('send-button').disabled=true;
      }
    } finally {refreshing--; if (lockedEditor) switching--; updateSend(); maybeRestart();}
  }
  async function send(event) {
    event?.preventDefault();
    if (composing || sending || $('send-button').disabled) return;
    const text=$('message-input').value, context={...model.context}, room=selected;
    sending=true; updateSend(); clearTimeout(draftTimer);
    try {
      await saveDraft(text,room,context.account);
      await rpc('send',{context,text});
      await saveDraft('',room,context.account);
      if (selected===room && account===context.account && $('message-input').value===text) $('message-input').value='';
      if (selected===room && account===context.account) await goLatest();
    } catch(e) {showError(e);} finally {sending=false;updateSend();$('message-input').focus();}
  }
  function connect(value) {
    bridge=value;
    $('message-form').addEventListener('submit',send);
    $('message-input').addEventListener('compositionstart',()=>{composing=true;lastEdit=Date.now();updateSend();});
    $('message-input').addEventListener('compositionend',()=>{composing=false;lastEdit=Date.now();updateSend();});
    $('message-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!composing&&e.keyCode!==229){e.preventDefault();send();}});
    $('message-input').addEventListener('input',()=>{lastEdit=Date.now();draftVersion++; updateSend(); clearTimeout(draftTimer); const text=$('message-input').value,room=selected,owner=account; draftTimer=setTimeout(()=>saveDraft(text,room,owner).catch(showError),150);});
    $('message-search').addEventListener('input',()=>changeSearch($('message-search').value));
    $('clear-search').addEventListener('click',()=>{$('message-search').value='';changeSearch('');});
    $('older').addEventListener('click',loadOlder);
    $('latest').addEventListener('click',goLatest);
    $('new-messages').addEventListener('click',goLatest);
    $('message-scroll').addEventListener('scroll',()=>{
      updateNavigation();
      if (!restoring && !loadingHistory && !query) {
        if ($('message-scroll').scrollTop<40) loadOlder();
        else if (atBottom()) loadNewer();
      }
    },{passive:true});
    $('sidebar-toggle').addEventListener('click',()=>{if(narrow.matches)drawer(false);else{collapsed=!collapsed;applySidebar();rpc('setting',{key:'collapsed',value:collapsed}).catch(showError);}});
    $('mobile-menu').addEventListener('click',()=>drawer(true)); $('drawer-backdrop').addEventListener('click',()=>drawer(false));
    ['header-search','sidebar-search-button'].forEach(id=>$(id).addEventListener('click',focusSearch));
    document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();focusSearch();}});
    $('settings-button').addEventListener('click',()=>{
      deleteScope=null; $('delete-confirm').hidden=true;
      $('settings-dialog').showModal(); $('settings-content').scrollTop=0;
    });
    $('participants-button').addEventListener('click',()=>$('participants-dialog').showModal());
    $('refresh-button').addEventListener('click',()=>rpc('refresh').then(()=>refresh()).catch(showError));
    $('check-updates').addEventListener('click',()=>rpc('check_updates').then(()=>refresh(true)).catch(showError));
    $('allow-update-checks').addEventListener('change',event=>rpc('update_permission',{allowed:event.target.checked}).then(()=>refresh(true)).catch(error=>{showError(error);refresh(true);}));
    for (const [key,id] of Object.entries(notificationControls)) $(id).addEventListener('change',async()=>{
      if (notificationPending.has(key)) return;
      const control=$(id), value=control.checked, previous=notificationSettings[key];
      notificationPending.add(key); requestVersion++; control.disabled=true; control.checked=previous;
      $('notification-save-status').textContent='알림 설정을 저장하고 있어요.';
      try {
        await rpc('setting',{key,value});
        notificationSettings[key]=value;
        if (model) model.notifications={...notificationSettings};
        $('notification-save-status').textContent='알림 설정을 저장했어요.';
      } catch(error) {
        $('notification-save-status').textContent='알림 설정을 저장하지 못해 이전 값으로 되돌렸어요. 다시 시도해 주세요.';
      } finally {
        requestVersion++; control.checked=notificationSettings[key]; control.disabled=false; notificationPending.delete(key);
      }
    });
    document.querySelectorAll('[data-legal]').forEach(button=>button.addEventListener('click',()=>rpc('legal',{document:button.dataset.legal}).catch(showError)));
    document.querySelectorAll('[name=appearance]').forEach(el=>el.addEventListener('change',()=>{theme=el.value;applyTheme();rpc('setting',{key:'theme',value:theme}).catch(showError);}));
    media.addEventListener('change',applyTheme); narrow.addEventListener('change',applySidebar);
    ['delete-room','delete-all'].forEach(id=>$(id).addEventListener('click',()=>{deleteScope={account,lobby:id==='delete-room'?selected:null};$('delete-confirm').hidden=false;}));
    $('confirm-delete').addEventListener('click',async()=>{try{
      if (!deleteScope || deleteScope.account!==account) throw new Error('connection_changed');
      const scope={...deleteScope}; clearTimeout(draftTimer); requestVersion++;
      await rpc('delete',scope); $('delete-confirm').hidden=true;
      if (scope.account===account && (scope.lobby===null || scope.lobby===selected)) {
        if (scope.lobby===null) positions.clear(); else positions.delete(scope.lobby);
        $('message-input').value=''; selected=''; query=''; resetTimeline(); $('message-search').value='';
      }
      signature='';await refresh(true);toast('선택한 기록을 삭제했어요.');
    }catch(e){showError(e);}});
    refresh(true); setInterval(()=>refresh(),600);
  }
  if (typeof QWebChannel === 'function' && window.qt?.webChannelTransport) {
    new QWebChannel(qt.webChannelTransport, channel=>connect(channel.objects.bridge));
  } else {
    $('connection-notice').hidden=false; $('connection-notice').textContent='Windows 앱에서 열어 주세요. 이 화면만으로는 게임에 연결할 수 없습니다.';
  }
})();
