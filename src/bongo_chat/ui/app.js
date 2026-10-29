/* Native QWebChannel is the only transport. No sample data or network endpoint. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const media = matchMedia('(prefers-color-scheme: dark)');
  const narrow = matchMedia('(max-width: 760px)');
  let language = 'ko', languagePreference = 'system', translations = {}, languagePending = false;
  // Capture only the initial application shell. Never scan runtime chat, names or drafts.
  const staticText = [], staticAttributes = [];
  const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const text = walker.currentNode;
    if (/[가-힣]/.test(text.data) && text.parentElement?.id !== 'language-select'
        && text.parentElement?.getAttribute('value') !== 'ko') staticText.push([text, text.data]);
  }
  document.querySelectorAll('[aria-label], [placeholder], [title]').forEach(el => {
    for (const attr of ['aria-label','placeholder','title']) {
      const text = el.getAttribute(attr);
      if (text && /[가-힣]/.test(text)) staticAttributes.push([el,attr,text]);
    }
  });
  function t(source, values={}) {
    const text = language === 'en' ? (translations[source] ?? source) : source;
    return text.replace(/\{(\w+)\}/g, (match,key) => Object.hasOwn(values,key) ? String(values[key]) : match);
  }
  function applyLanguage(data) {
    if (data.language && data.language !== language && data.translations) {
      language=data.language; translations=data.translations;
      document.documentElement.lang=language;
      for (const [el,source] of staticText) if (el.isConnected) {
        el.data=source.replace(/\S[\s\S]*\S|\S/, text=>t(text));
      }
      for (const [el,attr,source] of staticAttributes) if (el.isConnected) el.setAttribute(attr,t(source));
      signature=''; participantsSignature='';
      for (const id of ['language-status','reaction-save-status','notification-save-status','block-status']) $(id).textContent='';
      $('toast').hidden=true;
    }
    languagePreference=data.language_preference || 'system';
    if (!languagePending) $('language-select').value=languagePreference;
  }
  let bridge, model = null, selected = '', account = '', query = '', before = null;
  let theme = 'system', collapsed = false, composing = false, sending = false, switching = 0;
  let refreshing = 0, requestVersion = 0, draftVersion = 0, draftTimer, signature = '';
  let deleteScope = null;
  const notificationSettings = {notification_flash:true,notification_toast:true};
  const notificationPending = new Set();
  const notificationControls = {notification_flash:'notification-flash',notification_toast:'notification-toast'};
  let reactionsEnabled = false, reactionSettingPending = false;
  let restartPlan = null, restarting = false, lastEdit = 0;
  let openingProfile = false, participantsSignature = '';
  let participantMenuTarget = null;
  let blockPending = false, blockedSignature = '';
  let mergeRevision = -1, mergeBusy = false, mergeState = null;
  let mergeInputGroup = '';
  let start = null, seenSeq = null, loadingHistory = false, restoring = false;
  let seenVolatile = new Set(), searchPosition = null, pendingPosition = {bottom:true};
  const positions = new Map();
  let reactionContext = '', reactionLane = 0;
  const activeReactions = new Map();
  const reactionIds = new Set();
  function removeReaction(el) {
    clearTimeout(activeReactions.get(el)); activeReactions.delete(el); el.remove();
  }
  function trimReactions(limit) {
    while (activeReactions.size > limit) removeReaction(activeReactions.keys().next().value);
  }
  function clearReactions() {
    trimReactions(0);
  }
  function renderReactions(data) {
    const context = JSON.stringify(data.context);
    if (context !== reactionContext) {clearReactions(); reactionIds.clear(); reactionContext = context;}
    const layer = $('reaction-layer');
    if (!reactionsEnabled || reactionSettingPending || document.hidden || query || switching || !data.connected || !data.lobby_verified || data.lobby !== data.context.lobby) {
      clearReactions(); return;
    }
    for (const el of activeReactions.keys()) {
      if (!data.profiles[el.dataset.sender]) removeReaction(el);
    }
    const width = layer.clientWidth;
    const cap = Math.min(24, Math.max(8, Math.floor(width / 70) * 2));
    trimReactions(cap); // Also enforce a smaller viewport without new input.
    for (const event of data.reactions || []) {
      if (reactionIds.has(event.id)) continue;
      reactionIds.add(event.id);
      if (reactionIds.size > 256) reactionIds.delete(reactionIds.values().next().value);
      // A delayed bridge reply must not resurrect an old reaction.
      if (!(event.expires_in_ms > performance.now() - data.reactionRequestedAt)) continue;
      if (!data.profiles[event.sender] || !event.avatar?.startsWith('data:image/png;base64,')) continue;
      if (event.kind !== 'meow' && (event.kind !== 'emote' || !event.image?.startsWith('data:image/png;base64,'))) continue;
      // Admit fresh valid input immediately; never wait for a full layer to expire.
      trimReactions(cap - 1);
      const el = node('div', 'reaction-particle'); el.dataset.sender = event.sender;
      const cat = node('img', 'reaction-cat'); cat.src = event.avatar; cat.alt = '';
      let reaction;
      if (event.kind === 'meow') reaction = node('span', 'reaction-meow', event.text);
      else {reaction = node('img', 'reaction-item'); reaction.src = event.image; reaction.alt = '';}
      const name = node('span', 'reaction-name', data.profiles[event.sender].name || t('이름 확인 중'));
      name.dir = 'auto';
      el.append(cat, reaction, name);
      const lanes = Math.max(2, Math.min(6, Math.floor(width / 115)));
      const step = reactionLane++ % lanes;
      const lane = step % 2 === 0 ? step / 2 : lanes - 1 - Math.floor(step / 2);
      const left = 12 + lane * Math.max(0, width - 144) / Math.max(1, lanes - 1) + Math.random() * 20 - 10;
      el.style.left = `${Math.max(8, Math.min(width - 132, left))}px`;
      el.style.setProperty('--reaction-drift', `${Math.random() * 20 - 10}px`);
      el.style.setProperty('--reaction-rise', `${Math.min(245, Math.max(100, layer.clientHeight - 75)) * (.85 + Math.random() * .15)}px`);
      const remove = () => removeReaction(el);
      el.addEventListener('animationend', remove, {once:true});
      cat.addEventListener('error', remove, {once:true}); reaction.addEventListener('error', remove, {once:true});
      activeReactions.set(el, setTimeout(remove, 2400)); layer.append(el);
    }
  }
  const notices = () => ({
    checking: t('Steam과 게임의 채팅 연동 구조를 확인하고 있어요.'),
    searching_lobby: t('Bongo Cat의 현재 로비를 확인하고 있어요. 연결이 확인되면 대화를 불러옵니다.'),
    discovering: t('로비를 찾았어요. 현재 연결을 확인하는 동안 메시지를 미리 작성할 수 있어요.'),
    discovery_failed: t('Steam 연결은 유지 중이에요. 현재 로비 검증을 다시 시도하고 있어요. 전송은 확인 후 사용할 수 있어요.'),
    read_only: t('읽기 전용으로 실행 중입니다. 메시지를 전송하지 않습니다.'),
    no_lobby: t('현재 게임 로비를 확인할 수 없어요. 게임에서 로비에 참여해 주세요.'),
    unsupported_game_build: t('채팅 연동 구조의 호환성을 확인하지 못했어요. 대응 앱 업데이트를 확인하고 있습니다.'),
    game_files_changed: t('게임 업데이트를 감지했어요. 연동 구조를 다시 확인하고 있습니다.'),
    compatibility_tool_missing: t('호환성 검사 파일이 없어 연결할 수 없어요. 앱을 다시 설치해 주세요.'),
    compatibility_timeout: t('호환성 검사에 시간이 걸리고 있어요. 연결을 보류하고 다시 확인합니다.'),
    game_missing_or_ambiguous: t('실행 중인 Bongo Cat 하나를 확인해야 연결할 수 있어요.'),
    worker_stopped: t('연결 작업자가 종료됐어요. 전송 결과가 불명확한 메시지는 다시 보내지 않습니다.'),
    view_unavailable: t('대화 상태를 조회하지 못해 표시와 전송을 중단했어요. 다시 확인하고 있습니다.'),
    offline: t('오프라인으로 실행 중입니다. 실제 게임과 연결하지 않습니다.'),
  });
  const statuses = () => ({pending: t('전송 중'), accepted: t('전송됨 · Steam 접수'), failed: t('전송 실패'), unknown: t('전송 결과 확인 불가 · 자동 재전송 안 함')});
  const updateStatuses = () => ({idle:t('업데이트를 자동으로 확인합니다.'), checking:t('새 버전을 확인하고 있어요.'),
    disabled:t('GitHub 업데이트 통신을 껐습니다. Steam 채팅은 계속 사용할 수 있습니다.'),
    downloading:t('새 버전을 내려받고 있어요. 채팅을 계속 이용할 수 있습니다.'), ready:t('업데이트 준비 완료 · 다음 실행 때 적용합니다.'),
    current:t('최신 버전을 사용하고 있어요.'), unavailable:t('아직 받을 수 있는 정식 릴리스가 없습니다.'),
    applied:t('새 버전이 적용됐어요.'), rolled_back:t('새 버전이 시작되지 않아 이전 버전으로 돌아왔습니다.'),
    apply_failed:t('업데이트를 적용하지 못해 기존 버전을 유지했습니다.'),
    network_error:t('업데이트 서버에 연결하지 못했어요. 다음 확인 때 다시 시도합니다.'),
    verification_failed:t('업데이트를 확인하지 못했어요. 현재 버전을 유지합니다.'),
    offline:t('오프라인 실행 중에는 업데이트를 확인하지 않습니다.'), development:t('설치된 앱에서 자동 업데이트를 사용할 수 있습니다.')});
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
      const img = node('img'); img.src = profile.avatar; img.alt = t('게임 스킨·모자 정지 프로필'); el.append(img);
    } else { el.append(icon('cat')); el.title = t('고양이 외형 확인 불가'); }
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
    $('theme-note').textContent = theme === 'system' ? t('시스템의 밝기 설정을 따릅니다.') : t('{mode} 모드를 사용합니다.', {mode:theme === 'dark' ? t('다크') : t('라이트')});
  }
  function applySidebar() {
    $('app').classList.toggle('is-collapsed', collapsed);
    $('sidebar-toggle').setAttribute('aria-expanded', String(!collapsed));
    $('sidebar-toggle').setAttribute('aria-label', collapsed ? t('사이드바 펼치기') : t('사이드바 접기'));
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
    const text = ({connection_changed:t('연결 대상이 변경되어 전송하지 않았어요. 초안은 원래 방에 남겨 두었습니다.'),
      development_limit_50:t('개발판에서는 50 UTF-16 단위 이내로 보내 주세요.'),
      storage_failed_before_send:t('기록을 저장하지 못해 전송하지 않았어요.'),
      storage_failed:t('저장에 실패했어요. 작성한 내용은 이 창에서 확인해 주세요.'),
      legal_unavailable:t('안내 파일을 열지 못했어요. 앱 파일을 복구하거나 다시 설치해 주세요.'),
      invalid_steam_id:t('프로필 대상을 확인하지 못했어요. 참여자 목록을 다시 확인해 주세요.'),
      steam_profile_unavailable:t('현재 연결에서 열 수 없는 프로필이에요. 참여자와 연결 상태를 확인해 주세요.'),
      steam_profile_failed:t('Steam 프로필을 열지 못했어요. Steam 실행 상태를 확인해 주세요.'),
      update_permission_failed:t('업데이트 통신 설정을 저장하지 못했어요. 기존 선택을 유지합니다.')})[error.message] || t('요청을 완료하지 못했어요. 연결·저장 상태를 확인해 주세요.');
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
      toast(t('Steam에 프로필 열기를 요청했어요. 친구 추가는 Steam에서 진행해 주세요.'));
    } catch (error) { showError(error); }
    finally { openingProfile = false; updateProfileBusy(); }
  }
  function profileButton(uid, profile, context, key, cls, content) {
    const button = node('button', `steam-profile-action ${cls}`);
    const captured = {...context}; // Preserve the action's original connection, including for detached events.
    button.type = 'button'; button.dataset.profileKey = key;
    button.dataset.profileContext = profileContext(captured);
    button.setAttribute('aria-label', t('Steam 프로필 열기 · {name}', {name:profile?.name || t('참여자')}));
    button.title = t('Steam 프로필 열기 · 친구 추가는 Steam에서 진행해 주세요');
    button.append(content);
    button.addEventListener('click', event => openProfile(event, uid, captured));
    return button;
  }
  function preserveProfileFocus(container) {
    const active = document.activeElement;
    if (!container.contains(active) || !active?.matches('.steam-profile-action, .block-action, .participant-more')) return () => {};
    const key = active.dataset.profileKey, context = active.dataset.profileContext;
    return () => {
      const target = [...container.querySelectorAll('.steam-profile-action, .block-action, .participant-more')].find(button =>
        button.dataset.profileKey === key && button.dataset.profileContext === context);
      const fallback = container === $('participant-list')
        ? document.querySelector('#participants-dialog .dialog-heading button')
        : container === $('participant-menu') ? participantMenuTrigger() || document.querySelector('#participants-dialog .dialog-heading button')
        : container === $('blocked-list') ? $('block-steam-id') : $('message-scroll');
      (target || fallback).focus({preventScroll:true});
    };
  }
  function updateBlockBusy() {
    document.querySelectorAll('.block-action, #block-submit, #block-steam-id').forEach(control => {
      control.disabled = blockPending || restarting || !model?.context.account || !model?.blocks_ready;
    });
  }
  async function setBlocked(uid, blocked, owner) {
    if (blockPending || restarting || !owner || owner !== model?.context.account) return;
    const focused = document.activeElement, focusKey = focused?.dataset.profileKey;
    blockPending = true; requestVersion++; updateBlockBusy();
    $('block-status').textContent = t('차단 설정을 저장하고 있어요.');
    try {
      await rpc('block_user', {steam_id:uid, blocked, account:owner});
      requestVersion++;
      await refresh(true);
      const message = blocked ? t('채팅을 차단했어요.') : t('채팅 차단을 해제했어요.');
      $('block-status').textContent = message; toast(message);
    } catch (error) {
      $('block-status').textContent = error.message === 'invalid_steam_id'
        ? t('올바른 Steam ID를 숫자로 입력해 주세요.') : t('차단 설정을 저장하지 못했어요. 이전 설정을 유지합니다.');
      toast($('block-status').textContent);
    } finally {
      blockPending = false; updateBlockBusy();
      if (document.activeElement === document.body && owner === model?.context.account) {
        const replacement = [...document.querySelectorAll('.block-action')].find(el => el.dataset.profileKey === focusKey);
        const fallback = $('settings-dialog').open ? $('block-steam-id') : document.querySelector('#participants-dialog .dialog-heading button');
        (replacement || (focused?.isConnected ? focused : fallback))?.focus({preventScroll:true});
      }
    }
  }
  function blockButton(uid, blocked, owner, key) {
    const button = node('button', 'block-action', blocked ? t('차단 해제') : t('채팅 차단'));
    button.type = 'button'; button.dataset.profileKey = key; button.dataset.profileContext = owner;
    button.setAttribute('aria-label', t('{action} · Steam ID {id}', {action:button.textContent, id:uid}));
    button.addEventListener('click', () => setBlocked(uid, !blocked, owner));
    return button;
  }
  function renderBlocks(data) {
    const next = JSON.stringify([data.context.account, data.blocked_users, language]);
    if (next !== blockedSignature) {
      blockedSignature = next;
      const restoreFocus = preserveProfileFocus($('blocked-list'));
      $('blocked-list').replaceChildren(...(data.blocked_users || []).map(person => {
        const li = node('li'), info = node('span', 'participant-info');
        if (person.name) info.append(node('span', 'participant-name', person.name));
        info.append(node('span', 'steam-id', person.steam_id));
        li.append(info, blockButton(person.steam_id, true, data.context.account, `blocked-${person.steam_id}`));
        return li;
      }));
      restoreFocus();
    }
    $('blocked-empty').hidden = !!data.blocked_users?.length;
    $('blocked-empty').textContent = data.blocks_ready ? t('차단한 사용자가 없습니다.') : t('차단 목록을 확인할 수 없어 상대 대화를 보류합니다. 연결 상태 새로고침 후 다시 확인해 주세요.');
    updateBlockBusy();
  }
  function renderParticipants(data, people) {
    const nextSignature = JSON.stringify([people, data.profile_targets, data.context, data.lobby, data.connected, data.lobby_verified, language]);
    if (participantsSignature === nextSignature) return;
    participantsSignature = nextSignature;
    const restoreFocus = preserveProfileFocus($('participant-list'));
    $('participant-list').replaceChildren(...people.map(([uid,p]) => {
      const li = node('li'), name = node('span', 'participant-name', p.name || t('이름 확인 중'));
      name.title = name.textContent;
      li.append(avatar(p), name);
      if (uid !== data.context.account) {
        if (p.blocked) li.append(node('span', 'participant-badge', t('차단됨')));
        const more = node('button', 'participant-more', '⋯');
        more.type = 'button'; more.id = `participant-more-${uid}`;
        more.dataset.profileKey = `more-${uid}`; more.dataset.profileContext = profileContext(data.context);
        more.setAttribute('aria-label', t('참여자 메뉴 · {name}', {name:name.textContent}));
        more.setAttribute('aria-haspopup', 'menu'); more.setAttribute('aria-controls', 'participant-menu');
        more.setAttribute('aria-expanded', String(participantMenuTarget?.uid === uid));
        const context = profileContext(data.context);
        more.addEventListener('click', () => {
          if (!model || context !== profileContext(model.context) || !$('participants-dialog').open) return;
          if (participantMenuTarget?.uid === uid) { closeParticipantMenu(true); return; }
          closeParticipantMenu(); participantMenuTarget = {uid, context};
          renderParticipantMenu(model);
          if (!participantMenuTarget) return;
          $('participant-menu').showPopover(); more.setAttribute('aria-expanded', 'true');
          positionParticipantMenu(); $('participant-menu').querySelector('button')?.focus();
        });
        li.append(more);
      } else li.append(node('span', 'participant-badge', t('나')));
      return li;
    }));
    renderParticipantMenu(data);
    restoreFocus();
    updateBlockBusy();
  }
  function participantMenuTrigger() {
    return participantMenuTarget ? $(`participant-more-${participantMenuTarget.uid}`) : null;
  }
  function closeParticipantMenu(restoreFocus=false) {
    const trigger = participantMenuTrigger();
    trigger?.setAttribute('aria-expanded', 'false'); participantMenuTarget = null;
    if ($('participant-menu').matches(':popover-open')) $('participant-menu').hidePopover();
    $('participant-menu').replaceChildren();
    if (restoreFocus) (trigger || document.querySelector('#participants-dialog .dialog-heading button')).focus({preventScroll:true});
  }
  function positionParticipantMenu() {
    const menu = $('participant-menu'), trigger = participantMenuTrigger();
    if (!trigger || !menu.matches(':popover-open')) return;
    const rect = trigger.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(innerWidth - menu.offsetWidth - 8, rect.right - menu.offsetWidth))}px`;
    const below = rect.bottom + 6;
    menu.style.top = `${Math.max(8, Math.min(innerHeight - menu.offsetHeight - 8,
      below + menu.offsetHeight <= innerHeight - 8 ? below : rect.top - menu.offsetHeight - 6))}px`;
  }
  function renderParticipantMenu(data) {
    if (!participantMenuTarget) return;
    const {uid, context} = participantMenuTarget, person = data.participants?.[uid];
    if (!person || context !== profileContext(data.context) || !$('participants-dialog').open) {
      closeParticipantMenu(true); return;
    }
    const menu = $('participant-menu'), restoreFocus = preserveProfileFocus(menu);
    const name = node('strong', 'participant-menu-name', person.name || t('이름 확인 중'));
    name.id = 'participant-menu-name'; name.setAttribute('role', 'presentation');
    const id = node('span', 'steam-id', t('Steam ID {id}', {id:uid})); id.setAttribute('role', 'presentation');
    menu.replaceChildren(name, id);
    if (profileAvailable(data, uid)) menu.append(profileButton(uid, person, data.context, `participant-${uid}`,
      'participant-profile', document.createTextNode(t('Steam 프로필 열기'))));
    menu.append(blockButton(uid, person.blocked, data.context.account, `block-${uid}`));
    menu.querySelectorAll('button').forEach(button => button.setAttribute('role', 'menuitem'));
    updateBlockBusy(); updateProfileBusy(); positionParticipantMenu(); restoreFocus();
  }
  function updateSend() {
    const text = $('message-input').value;
    $('send-button').disabled = !model?.can_send || composing || sending || switching || restarting || !text.trim() || text.length > 50;
    $('message-input').disabled = !selected || sending || switching || restarting;
    $('composer-help').textContent = t('{count}/50 · Enter 전송 · Shift + Enter 줄바꿈', {count:text.length});
    $('message-form').classList.toggle('is-unavailable', !model?.can_send);
    updateProfileBusy();
  }
  async function saveDraft(text = $('message-input').value, room = selected, owner = account) {
    if (room && owner) await rpc('draft', {account:owner,lobby:room,text});
  }
  function updateRestartNotice(update) {
    const banner = $('update-notice');
    if (update.state === 'ready' && update.merge_deferred) {
      restartPlan = null;
      const text = t('자동 합성의 실행 또는 결과 확인이 끝나면 업데이트를 적용합니다.');
      banner.textContent = text; banner.hidden = false; $('update-status').textContent = text; return;
    }
    if (update.state !== 'ready' || !update.can_restart) {
      restartPlan = null; banner.hidden = true; return;
    }
    if (restartPlan?.version !== update.version) {
      restartPlan = {version:update.version, deadline:Date.now()+30000, retryAt:0, reason:''};
    }
    const seconds = Math.max(0, Math.ceil((Math.max(restartPlan.deadline,lastEdit+5000)-Date.now())/1000));
    let text = t('새 버전 준비 완료 · {seconds}초 후 자동 재시작합니다. 작성 중인 문장은 저장됩니다.', {seconds});
    if (composing || sending || switching || restartPlan.reason === 'sending') text = t('새 버전 준비 완료 · 입력·전송이 끝나면 자동으로 재시작합니다.');
    if (restartPlan.reason === 'storage' || model?.storage_error) text = t('저장되지 않은 내용이 있어 자동 재시작을 기다립니다. 저장 상태를 확인해 주세요.');
    if (restarting) text = t('작성 중인 문장을 저장하고 업데이트를 적용하기 위해 재시작합니다.');
    banner.textContent = text; banner.hidden = false;
    $('update-status').textContent = text;
  }
  async function maybeRestart() {
    if (!restartPlan || restarting || refreshing || composing || sending || switching || model?.storage_error || mergeState?.active || mergeState?.unresolved) return;
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
    const name=room.name || t('게임 로비');
    button.title = name; button.setAttribute('aria-label', name);
    if (selected === room.lobby) button.setAttribute('aria-current', 'page');
    button.append(avatar(null));
    const info = node('span', 'room-info'); info.append(node('span','room-name',name),node('span','room-detail', live ? t('현재 게임 로비') : t('{count}개 연결 구간 · 보관 기록', {count:room.segments})));
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
    return {lobby:selected, account, query, language, before:query ? before : null,
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
    $('latest').textContent=query || model.has_newer ? t('최근 대화로') : t('맨 아래로');
    $('older').hidden=!model.has_more;
    $('older').disabled=loadingHistory;
    $('older').textContent=loadingHistory ? t('이전 대화 불러오는 중…') : t('이전 대화 불러오기');
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
    clearReactions();
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
    clearReactions();
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
    const nextSignature = JSON.stringify([data.messages,data.profiles,data.blocks_ready,query,
      data.profile_targets,data.context,data.lobby,data.connected,data.lobby_verified]);
    if (signature === nextSignature) {if (pendingPosition) restorePosition(position); pendingPosition=null; updateNavigation(); return;}
    signature = nextSignature;
    const restoreFocus = preserveProfileFocus($('message-list'));
    $('message-list').replaceChildren();
    let day = '', segment = '';
    for (const message of data.messages) {
      const date = new Date(message.received*1000), label = date.toLocaleDateString(language === 'ko' ? 'ko-KR' : 'en-US');
      if (day !== label || segment !== message.session) {
        $('message-list').append(node('div','date-divider', `${label} · ${t('앱이 수신한 기록')}${segment && segment !== message.session ? t(' · 연결 공백 있음') : ''}`));
        day = label; segment = message.session;
      }
      const row = node('article', `message${message.own ? ' is-own' : ''}`);
      row.id = `message-${message.id}`; row.setAttribute('role','listitem');
      if (message.kind === 'member_joined' || message.kind === 'member_left') {
        row.classList.add('presence-notice');
        const name = message.name || t('이름 확인 중');
        row.append(node('span','presence-text',message.kind === 'member_joined'
          ? t('{name}님이 들어왔습니다.', {name}) : t('{name}님이 나갔습니다.', {name})));
        const time = node('time','presence-time',date.toLocaleTimeString(language === 'ko' ? 'ko-KR' : 'en-US',{hour:'2-digit',minute:'2-digit'}));
        time.dateTime = date.toISOString(); row.append(time);
        if (message.unsaved) row.append(node('span','message-status',t('이 기록은 저장되지 않았어요')));
        $('message-list').append(row);
        continue;
      }
      const profile = data.profiles[message.sender];
      const canOpen = !message.own && profileAvailable(data, message.sender);
      row.append(canOpen ? profileButton(message.sender, profile, data.context, `${message.id}-avatar`, 'profile-avatar', avatar(profile)) : avatar(profile));
      const content = node('div','message-content'), meta = node('div','message-meta');
      const name = node('strong','', profile?.name || message.name || (message.own ? t('나') : t('이름 확인 중')));
      meta.append(canOpen ? profileButton(message.sender, profile, data.context, `${message.id}-name`, 'profile-name', name) : name);
      if (message.own) meta.append(node('span','self-tag',t('나')));
      meta.append(node('time','',date.toLocaleTimeString(language === 'ko' ? 'ko-KR' : 'en-US',{hour:'2-digit',minute:'2-digit'})));
      const bubble = node('div','message-bubble');
      // DOM text preserves CR, but it does not render it as a line break.
      const body = message.body.replace(/\r\n?/g, '\n');
      const index = query ? body.toLocaleLowerCase().indexOf(query.toLocaleLowerCase()) : -1;
      if (index >= 0) bubble.append(document.createTextNode(body.slice(0,index)),node('mark','',body.slice(index,index+query.length)),document.createTextNode(body.slice(index+query.length)));
      else bubble.textContent = body;
      content.append(meta,bubble);
      if (statuses()[message.status] || message.unsaved) content.append(node('span','message-status',message.unsaved ? t('이 기록은 저장되지 않았어요') : statuses()[message.status]));
      if (query) {
        const jump = node('button','page-button',t('대화에서 보기'));
        jump.addEventListener('click',() => jumpToMessage(message));
        content.append(jump);
      }
      row.append(content); $('message-list').append(row);
    }
    $('empty-state').hidden = data.messages.length > 0;
    $('empty-title').textContent = query ? t('검색 결과가 없어요') : t('대화를 기다리고 있어요');
    $('empty-description').textContent = data.blocks_ready ? t('앱이 연결된 동안 받은 대화만 표시합니다.') : t('차단 목록을 확인할 수 없어 상대 대화를 보류합니다. 연결 상태 새로고침 후 다시 확인해 주세요.');
    restoreFocus(); restorePosition(position); pendingPosition=null;
  }
  function renderMerge(value, force=false) {
    if (!value || (!force && value.revision < mergeRevision)) return;
    mergeRevision = value.revision; mergeState = value;
    if (value.exchange_group) {
      if (mergeInputGroup && mergeInputGroup !== value.exchange_group) $('merge-limit').value = '';
      mergeInputGroup = value.exchange_group;
      $('merge-target-group').value = value.exchange_group;
    }
    const states = {idle:t('시작할 수 있어요'),blocked:t('시작할 수 없어요'),arming:t('합성 준비 중'),preparing:t('합성 준비 중'),
      selecting:t('중복 아이템 선택 중'),merging:t('합성 요청 준비 중'),waiting:t('합성 결과 확인 중'),
      stopping:t('중지 요청 · 진행 중인 결과 확인 중'),completed:t('합성 종료'),stopped:t('중지됨'),
      failed:t('확인 필요 · 실행 중단'),unknown:t('결과 미확인 · 실행 중단')};
    const reasons = {adapter_unverified:t('게임 내부 연결 모듈이 연결되지 않았습니다. 현재는 시작할 수 없습니다.'),
      offline:t('오프라인 모드에서는 자동 합성을 사용할 수 없습니다.'),read_only:t('읽기 전용 모드에서는 자동 합성을 사용할 수 없습니다.'),
      closed:t('자동 합성 연결이 종료되었습니다.'),game_unavailable:t('실행 중인 게임을 확인할 수 없습니다.'),
      screen_unavailable:t('게임 내부 상태를 확인할 수 없습니다. 연결 상태를 확인해 주세요.'),
      target_changed:t('게임, 계정 또는 합성 그룹이 바뀌어 중단했습니다.'),settings_changed:t('게임의 보호 옵션이 바뀌어 중단했습니다.'),
      existing_selection:t('선택된 재료 또는 진행 중인 합성이 있습니다. 게임에서 확인해 주세요.'),
      observation_stale:t('게임 상태 확인이 지연되어 중단했습니다.'),selection_unverified:t('중복 자동 선택 결과를 확인하지 못했습니다.'),
      selection_timeout:t('중복 자동 선택 결과를 기다리다 중단했습니다.'),
      result_timeout:t('합성 응답 시간이 초과되었습니다. 재시도하지 않았으며 게임에서 결과를 확인해야 합니다.'),
      result_unverified:t('합성 결과를 확정할 수 없습니다. 게임에서 결과를 확인해 주세요.'),
      input_failed:t('게임 함수 호출을 확인하지 못해 중단했습니다.'),game_failed:t('게임에서 합성 실패를 확인했습니다. 성공이 확인된 횟수만 표시합니다.'),
      manual_exchange_screen_open:t('수동 합성 화면을 닫으면 앱에서 합성을 시작할 수 있습니다.'),
      group_changing:t('선택한 그룹의 가능 횟수를 확인하고 있습니다.'),
      test_budget_exhausted:t('이번 연결의 시험 횟수를 모두 사용했습니다. 추가 합성은 요청하지 않습니다.'),
      bridge_observation_failed:t('게임 내부 상태를 확인할 수 없습니다. 연결 상태를 확인해 주세요.'),
      no_duplicates:t('현재 합성 그룹에 합성할 중복 아이템이 더 없습니다.'),
      limit_reached:t('설정한 상한에 도달했거나 다음 합성이 상한을 넘습니다.'),
      user_stopped:t('새 합성 요청을 중지했습니다. 이미 요청한 합성은 취소되지 않습니다.'),
      app_closed:t('앱 종료로 중단했습니다. 이미 요청한 결과는 게임에서 확인해 주세요.'),
      checked_in_game:t('게임에서 결과를 확인했습니다. 미확인 건을 완료 횟수에 추가하지 않았습니다.'),
      ready:t('게임의 중복 자동 선택을 사용합니다. 게임 탭을 열어 둘 필요가 없습니다.')};
    const title = states[value.state] || t('시작할 수 없어요');
    const summary = t('{state} · 완료 {count}회', {state:title,count:value.completed || 0});
    $('merge-state').textContent = title;
    $('merge-reason').textContent = reasons[value.reason] || reasons.screen_unavailable;
    if (value.connection) {
      const connection = value.connection;
      $('merge-connection').hidden = false;
      $('merge-connection').dataset.state = connection.state;
      $('merge-connect').disabled = mergeBusy || !connection.can_connect || value.active || value.unresolved;
      $('merge-connect').textContent = connection.state === 'connected' ? t('다시 연결') : t('게임에 연결');
      $('merge-connection-title').textContent = connection.state === 'connecting' ? t('게임에 연결 중')
        : connection.state === 'connected' ? t('게임 연결됨') : connection.state === 'error' ? t('연결 확인 필요') : t('게임 연결');
      const connectionErrors = {
        merge_compiler_missing:t('게임 연결에 필요한 Windows .NET Framework 도구를 찾을 수 없습니다.'),
        merge_prepare_failed:t('게임 연결 모듈을 준비하지 못했습니다. 게임 버전과 앱 파일을 확인해 주세요.'),
        game_missing_or_ambiguous:t('Bongo Cat을 실행한 뒤 다시 연결해 주세요.'),
        unsupported_game_build:t('현재 게임 버전은 자동 합성 연결을 지원하지 않습니다. 호환되는 앱 업데이트가 필요합니다.'),
        bridge_assets_missing:t('이 앱에 자동 합성 연결 파일이 없습니다. 자동 합성을 포함한 앱을 설치해 주세요.'),
        bridge_client_in_use:t('다른 앱이 자동 합성에 연결되어 있습니다. 해당 앱을 닫은 뒤 연결해 주세요.'),
        prior_bridge_active:t('기존 연결 상태를 확인할 수 없습니다. 게임을 직접 다시 실행한 뒤 연결해 주세요.'),
        bridge_session_unavailable:t('이전 연결 상태를 확인할 수 없습니다. 합성 결과를 확인하고 게임을 직접 다시 실행해 주세요.'),
        attach_not_confirmed_no_retry:t('연결 완료를 확인하지 못했습니다. 자동으로 재시도하지 않습니다. 게임을 직접 다시 실행한 뒤 연결해 주세요.')};
      $('merge-connection-message').textContent = connection.state === 'connecting'
        ? t('게임과 연결 파일을 확인하고 있습니다. 아이템을 선택하거나 소비하지 않습니다.')
        : connection.state === 'error' ? connectionErrors[connection.error] || t('게임 연결에 실패했습니다. 게임과 앱의 실행 상태를 확인해 주세요.')
        : connection.state === 'connected' ? t('그룹과 횟수를 선택하고 시작을 눌러 주세요. 앱을 다시 열어도 자동으로 시작하지 않습니다.')
        : t('게임에 연결한 뒤 그룹과 횟수를 선택해 주세요. 연결만으로 합성하지 않습니다.');
    }
    $('merge-sidebar-status').textContent = value.active || value.completed || value.unresolved ? summary : title;
    $('merge-open').title = t('아이템 자동 합성') + ' · ' + summary;
    $('merge-open').setAttribute('aria-label',t('아이템 자동 합성') + ' · ' + summary);
    $('merge-sidebar-stop').hidden = !value.active;
    $('merge-sidebar-stop').disabled = !value.can_stop;
    $('merge-run-bar').hidden = !value.active && !value.unresolved;
    $('merge-run-status').textContent = summary;
    $('merge-run-stop').hidden = !value.active;
    $('merge-run-stop').disabled = !value.can_stop;
    $('merge-stop').disabled = !value.can_stop;
    $('merge-limit').disabled = mergeBusy || value.active || value.unresolved;
    $('merge-target-group').disabled = mergeBusy || !value.can_change_group || !value.exchange_group;
    if (value.active) $('merge-limit').value = String(value.limit);
    renderMergeLimit();
    $('merge-acknowledge').hidden = !value.unresolved;
    $('merge-acknowledge').disabled = mergeBusy;
    $('merge-completed').textContent = String(value.completed || 0);
    $('merge-pending').textContent = String(value.pending || 0);
    const groups = {cosmetics:t('캐릭터·모자·봉고'),emotes:t('이모티콘·UI 테마')};
    $('merge-group').textContent = groups[value.exchange_group] || t('게임에서 확인 필요');
    $('merge-available-label').textContent = groups[value.exchange_group]
      ? t('{group} 그룹에서 합성 가능', {group:groups[value.exchange_group]}) : t('현재 그룹에서 합성 가능');
    $('merge-group-help').textContent = value.exchange_group === 'cosmetics'
      ? t('캐릭터·모자·봉고가 같은 합성 그룹입니다. 이모티콘·UI 테마는 포함하지 않습니다.')
      : value.exchange_group === 'emotes'
        ? t('이모티콘·UI 테마가 같은 합성 그룹입니다. 캐릭터·모자·봉고는 포함하지 않습니다.')
        : t('앱에서 합성할 그룹을 선택해 주세요. 두 그룹의 재료와 가능 횟수는 합산하지 않습니다.');
    for (const [id,key] of [['merge-favorites','favorites_allowed'],['merge-events','events_excluded']])
      $(id).textContent = value[key] === true ? t('켜짐') : value[key] === false ? t('꺼짐') : t('게임에서 확인 필요');
  }
  function renderMergeLimit() {
    const available = mergeState?.available_exchanges;
    const known = Number.isSafeInteger(available) && available >= 0;
    const limit = $('merge-limit').valueAsNumber;
    const valid = Number.isSafeInteger(limit) && limit > 0;
    $('merge-available').textContent = known ? t('{count}회', {count:available}) : t('확인 필요');
    $('merge-maximum').disabled = mergeBusy || !mergeState?.can_start || !known || available === 0;
    $('merge-start').disabled = mergeBusy || !mergeState?.can_start || !valid || available === 0;
    $('merge-planned').textContent = !valid ? t('합성 횟수는 1 이상의 정수로 입력해 주세요.')
      : known ? t('이번 실행 예정: 최대 {count}회', {count:Math.min(limit,available)}) : t('이번 실행 예정: 확인 필요');
  }
  async function mergeAction(action, args={}) {
    // Stop remains available during another bridge request.
    if (mergeBusy && action !== 'merge_stop') return;
    mergeBusy = true; if (mergeState) renderMerge(mergeState);
    try {
      const result = await rpc(action,action === 'merge_start' ? {limit:Number($('merge-limit').value)} : args);
      if (action === 'merge_maximum') {
        if (result.ok && Number.isSafeInteger(result.limit) && result.limit > 0 && result.auto_merge?.revision >= mergeRevision)
          $('merge-limit').value = String(result.limit);
        else toast(t('가능 횟수를 확인하지 못했습니다. 수량을 다시 확인해 주세요.'));
      }
      renderMerge(result.auto_merge);
    } catch (error) { showError(error); }
    finally { mergeBusy = false; if (mergeState) renderMerge(mergeState); refresh(); }
  }
  function render(data, resetDraft) {
    const position=pendingPosition || capturePosition();
    applyLanguage(data);
    // Refresh translations using the newest merge state, never a delayed view.
    renderMerge(data.auto_merge && data.auto_merge.revision >= mergeRevision ? data.auto_merge : mergeState, true);
    document.documentElement.dataset.notice=data.notice || '';
    model = data;
    if (!reactionSettingPending) {
      reactionsEnabled = data.reactions_enabled === true;
      $('reactions-enabled').checked = reactionsEnabled;
    }
    for (const [key,id] of Object.entries(notificationControls)) {
      if (!notificationPending.has(key)) {
        notificationSettings[key] = data.notifications?.[key] !== false;
        $(id).checked = notificationSettings[key];
      }
    }
    const notificationStatus = data.notification_status || {};
    $('notification-status').textContent = ({unavailable:t('Windows 알림을 사용할 수 없어요. 설치된 앱의 시작 메뉴 바로가기를 확인해 주세요. 실패한 알림은 다시 보내지 않으며, 옵션을 껐다 켜면 다음 새 메시지부터 다시 시도합니다.'),
      disabled:t('Windows에서 이 앱의 알림을 제한하고 있어요. 표시 여부는 Windows 알림 설정을 따릅니다.'),
      cleanup_failed:t('이전 Windows 알림을 지우지 못했어요. 알림 센터에서 직접 지울 수 있습니다.')})[notificationStatus.toast] || '';
    if (notificationStatus.flash === 'unavailable') $('notification-status').textContent += t(' 작업 표시줄 알림을 사용할 수 없어요.');
    if (seenSeq===null) {seenSeq=data.latest_seq || 0; seenVolatile=new Set(data.volatile_peer_ids || []);}
    if (!query && start===null) start=data.messages.find(message => Number.isInteger(message.seq))?.seq ?? null;
    const update = data.update || {state:'development',current:''};
    $('app-version').textContent = update.current ? `v${update.current}` : '';
    $('update-status').textContent = updateStatuses()[update.state] || updateStatuses().verification_failed;
    $('check-updates').disabled = ['checking','downloading','offline','development','disabled'].includes(update.state);
    $('allow-update-checks').checked = update.allowed !== false;
    updateRestartNotice(update);
    theme = data.theme; collapsed = data.collapsed; applyTheme(); applySidebar();
    $('live-rooms').replaceChildren(); $('archived-rooms').replaceChildren();
    for (const room of data.rooms) (room.lobby === data.context.lobby ? $('live-rooms') : $('archived-rooms')).append(roomButton(room,room.lobby === data.context.lobby));
    const room = data.rooms.find(r => r.lobby === selected);
    $('room-title').textContent = room ? room.name || t('게임 로비') : 'Bongo Cat Chat';
    const connected = data.connected;
    const connectionLabel = !data.lobby_verified ? t('로비 발견 · 연결 확인 중') : data.can_send ? t('게임과 연결됨') : t('게임 수신 연결됨');
    $('connection-label').querySelector('span').textContent = selected && selected !== data.context.lobby ? t('보관 기록 · 읽기 전용') : connected ? connectionLabel : t('연결 확인 중');
    document.querySelectorAll('.status-dot').forEach(el => el.classList.toggle('unavailable',!connected));
    let notice = data.notice ? notices()[data.notice] || t('게임 상태를 확인하지 못했어요. 연동을 중단하고 다시 확인하고 있습니다.') : '';
    if (data.notice === 'unsupported_game_build') {
      const build = /^[0-9]{1,12}$/.test(data.game_build || '') ? t('게임 빌드 {build}', {build:data.game_build}) : t('현재 게임 파일');
      const progress = ({checking:t('앱 업데이트를 확인하고 있어요.'), downloading:t('새 앱을 내려받고 있어요.'),
        disabled:t('GitHub 통신이 꺼져 있습니다. 앱 설정에서 업데이트 확인을 켤 수 있어요.'),
        ready:data.update?.can_restart ? t('새 앱이 준비됐어요. 잠시 후 자동으로 재시작합니다.') : t('새 앱이 준비됐어요. 앱을 다시 실행하면 적용합니다.'),
        offline:t('오프라인 상태입니다.'), development:t('설치판에서 자동 업데이트를 사용할 수 있어요.'),
        network_error:t('업데이트 서버에 연결하지 못했어요. 자동으로 다시 확인합니다.'),
        verification_failed:t('업데이트를 검증하지 못했어요. 기존 앱을 유지합니다.')})[data.update?.state]
        || t('아직 대응 버전이 없습니다. 앱 업데이트를 주기적으로 확인합니다.');
      notice = t('{build}의 호환성을 확인하지 못해 연동을 중단했어요. {progress}', {build,progress});
    }
    $('connection-notice').textContent = notice || (!data.blocks_ready ? t('차단 목록을 확인할 수 없어 상대 대화를 보류합니다. 연결 상태 새로고침 후 다시 확인해 주세요.') : t('개발판 · 게임의 고양이 숨김과 채팅 차단은 별개입니다. 받지 못한 대화는 복원하지 않습니다.'));
    $('connection-notice').hidden = false;
    $('storage-label').textContent = data.storage_error ? t('저장 실패 · 일부 기록 미보관') : t('이 기기에 30일 보관');
    document.querySelector('.account-copy strong').textContent = data.profiles[data.context.account]?.name || t('계정 확인 중');
    $('account-status').textContent = connected ? (data.lobby_verified ? t('Bongo Cat 연결됨') : t('Steam 연결됨 · 로비 확인 중')) : t('연결 확인 중');
    const accountAvatar = document.querySelector('.account-avatar');
    const replacement = avatar(data.profiles[data.context.account]); replacement.classList.add('account-avatar'); accountAvatar.replaceWith(replacement);
    const people = Object.entries(data.participants || {}).sort(([a], [b]) => a.localeCompare(b));
    $('member-count').textContent = t('{count}명', {count:people.length});
    $('participants-button').setAttribute('aria-label', t('확인된 참여자 {count}명 보기', {count:people.length}));
    document.querySelector('.avatar-stack').replaceChildren(...people.slice(0,3).map(([,p])=>avatar(p)));
    renderParticipants(data, people);
    renderBlocks(data);
    $('participants-description').textContent = t('⋯에서 Steam 프로필과 채팅 차단을 관리하세요.');
    if (resetDraft) $('message-input').value = data.draft;
    $('message-input').placeholder = selected === data.context.lobby ? t('메시지 입력') : t('이 로비에 남겨 둘 초안');
    $('search-status').hidden=!query; $('search-summary').textContent=t('현재 페이지 {count}개 결과', {count:data.messages.length});
    // The history control changes the content height; settle it before restoring the anchor.
    $('older').hidden=!data.has_more;
    renderMessages(data,position); renderReactions(data); updateSend();
  }
  async function refresh(force=false) {
    if (restarting || refreshing && !force) return;
    const version = requestVersion, editing = draftVersion;
    let lockedEditor = false;
    refreshing++;
    try {
      const reactionRequestedAt = performance.now();
      let data = await rpc('view',viewArgs({reactions:reactionsEnabled && !reactionSettingPending && !document.hidden && !query && !switching}));
      data.reactionRequestedAt = reactionRequestedAt;
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
        if (model) render({...model,state:'unavailable',notice:'view_unavailable',connected:false,lobby_verified:false,blocks_ready:false,participants:{},can_send:false,messages:[],profiles:{},has_more:false,has_newer:false,unseen:false,unseen_seq:0,volatile_peer_ids:[]},false);
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
    for (const id of ['merge-open','merge-run-details']) $(id).addEventListener('click',()=>{
      $('merge-dialog').showModal(); document.querySelector('.merge-content').scrollTop=0;
    });
    $('merge-start').addEventListener('click',()=>mergeAction('merge_start'));
    $('merge-connect').addEventListener('click',()=>mergeAction('merge_connect'));
    $('merge-target-group').addEventListener('change',event=>mergeAction('merge_group',{group:event.target.value}));
    $('merge-maximum').addEventListener('click',()=>mergeAction('merge_maximum'));
    $('merge-limit').addEventListener('input',renderMergeLimit);
    for (const id of ['merge-stop','merge-sidebar-stop','merge-run-stop'])
      $(id).addEventListener('click',()=>mergeAction('merge_stop'));
    $('merge-acknowledge').addEventListener('click',()=>mergeAction('merge_acknowledge'));
    $('block-form').addEventListener('submit', event => {
      event.preventDefault();
      setBlocked($('block-steam-id').value, true, model?.context.account);
    });
    document.addEventListener('visibilitychange', clearReactions);
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
    $('participants-dialog').addEventListener('close', () => closeParticipantMenu());
    $('participants-dialog').addEventListener('scroll', positionParticipantMenu);
    window.addEventListener('resize', positionParticipantMenu);
    $('participant-menu').addEventListener('toggle', event => {
      if (event.newState === 'closed' && !$('participant-menu').matches(':popover-open')) closeParticipantMenu();
    });
    document.addEventListener('keydown', event => {
      if (!$('participant-menu').matches(':popover-open')) return;
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation(); closeParticipantMenu(true);
      } else if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
        event.preventDefault();
        const buttons = [...$('participant-menu').querySelectorAll('button:not(:disabled)')];
        const index = buttons.indexOf(document.activeElement);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
          : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next]?.focus();
      }
    }, true);
    $('language-select').addEventListener('change',async()=>{
      if (languagePending) return;
      const control=$('language-select'), value=control.value, previous=languagePreference;
      const hadFocus=document.activeElement===control;
      languagePending=true; requestVersion++; control.disabled=true; control.value=previous;
      $('language-status').textContent=t('언어 설정을 저장하고 있어요.');
      let saved=false;
      try {
        await rpc('setting',{key:'language',value});
        saved=true; requestVersion++;
        await refresh(true);
        $('language-status').textContent=t('언어 설정을 저장했어요.');
      } catch(error) {
        $('language-status').textContent=t('언어 설정을 저장하지 못해 이전 언어를 유지합니다. 다시 시도해 주세요.');
      } finally {
        requestVersion++; languagePending=false; control.disabled=false;
        control.value=saved ? value : previous;
        if (hadFocus && document.activeElement===document.body && $('settings-dialog').open) control.focus({preventScroll:true});
      }
    });
    $('refresh-button').addEventListener('click',()=>rpc('refresh').then(()=>refresh()).catch(showError));
    $('check-updates').addEventListener('click',()=>rpc('check_updates').then(()=>refresh(true)).catch(showError));
    $('allow-update-checks').addEventListener('change',event=>rpc('update_permission',{allowed:event.target.checked}).then(()=>refresh(true)).catch(error=>{showError(error);refresh(true);}));
    $('reactions-enabled').addEventListener('change',async()=>{
      if (reactionSettingPending) return;
      const control=$('reactions-enabled'), value=control.checked;
      const hadFocus=document.activeElement===control;
      reactionSettingPending=true; requestVersion++; control.disabled=true; control.checked=reactionsEnabled;
      clearReactions();
      $('reaction-save-status').textContent=t('반응 효과 설정을 저장하고 있어요.');
      try {
        await rpc('setting',{key:'reactions_enabled',value});
        reactionsEnabled=value;
        if (model) model.reactions_enabled=value;
        $('reaction-save-status').textContent=t('반응 효과 설정을 저장했어요.');
      } catch(error) {
        $('reaction-save-status').textContent=t('반응 효과 설정을 저장하지 못해 이전 값으로 되돌렸어요. 다시 시도해 주세요.');
      } finally {
        requestVersion++; control.checked=reactionsEnabled; control.disabled=false; reactionSettingPending=false;
        if (hadFocus && document.activeElement===document.body && $('settings-dialog').open) control.focus();
      }
    });
    for (const [key,id] of Object.entries(notificationControls)) $(id).addEventListener('change',async()=>{
      if (notificationPending.has(key)) return;
      const control=$(id), value=control.checked, previous=notificationSettings[key];
      notificationPending.add(key); requestVersion++; control.disabled=true; control.checked=previous;
      $('notification-save-status').textContent=t('알림 설정을 저장하고 있어요.');
      try {
        await rpc('setting',{key,value});
        notificationSettings[key]=value;
        if (model) model.notifications={...notificationSettings};
        $('notification-save-status').textContent=t('알림 설정을 저장했어요.');
      } catch(error) {
        $('notification-save-status').textContent=t('알림 설정을 저장하지 못해 이전 값으로 되돌렸어요. 다시 시도해 주세요.');
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
      signature='';await refresh(true);toast(t('선택한 기록을 삭제했어요.'));
    }catch(e){showError(e);}});
    refresh(true); setInterval(()=>refresh(),600);
  }
  if (typeof QWebChannel === 'function' && window.qt?.webChannelTransport) {
    new QWebChannel(qt.webChannelTransport, channel=>connect(channel.objects.bridge));
  } else {
    $('connection-notice').hidden=false; $('connection-notice').textContent=t('Windows 앱에서 열어 주세요. 이 화면만으로는 게임에 연결할 수 없습니다.');
  }
})();
