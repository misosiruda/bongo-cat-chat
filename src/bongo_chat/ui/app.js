/* Native QWebChannel is the only transport. No sample data or network endpoint. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const media = matchMedia('(prefers-color-scheme: dark)');
  const narrow = matchMedia('(max-width: 760px)');
  let bridge, model = null, selected = '', account = '', query = '', before = null;
  let theme = 'system', collapsed = false, composing = false, sending = false, switching = 0;
  let refreshing = false, requestVersion = 0, draftVersion = 0, draftTimer, signature = '';
  let deleteScope = null;
  let renderedIds = new Set();
  let newVisibleIds = new Set();
  const positions = new Map();
  const notices = {
    checking: 'Steam과 게임의 채팅·숨김 연동 구조를 확인하고 있어요.',
    discovering: '게임의 숨김 상태를 확인하고 있어요. 최초 연결에는 시간이 걸릴 수 있어요.',
    read_only: '읽기 전용으로 실행 중입니다. 메시지를 전송하지 않습니다.',
    no_lobby: '현재 게임 로비를 확인할 수 없어요. 게임에서 로비에 참여해 주세요.',
    hidden_unavailable: '게임의 숨김 상태를 확인할 수 없어 상대 대화 표시·신규 저장과 전송을 중단했어요.',
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
      storage_failed:'저장에 실패했어요. 작성한 내용은 이 창에서 확인해 주세요.'})[error.message] || '요청을 완료하지 못했어요. 연결·저장 상태를 확인해 주세요.';
    toast(text);
  }
  function updateSend() {
    const text = $('message-input').value;
    $('send-button').disabled = !model?.can_send || composing || sending || switching || !text.trim() || text.length > 50;
    $('message-input').disabled = !selected || sending || switching;
    $('composer-help').textContent = `${text.length}/50 · Enter 전송 · Shift + Enter 줄바꿈`;
    $('message-form').classList.toggle('is-unavailable', !model?.can_send);
  }
  async function saveDraft(text = $('message-input').value, room = selected, owner = account) {
    if (room && owner) await rpc('draft', {account:owner,lobby:room,text});
  }
  function roomButton(room, live) {
    const button = node('button', `room-button${live ? ' is-live' : ''}`);
    button.title = room.name; button.setAttribute('aria-label', room.name);
    if (selected === room.lobby) button.setAttribute('aria-current', 'page');
    button.append(avatar(null));
    const info = node('span', 'room-info'); info.append(node('span','room-name',room.name),node('span','room-detail', live ? '현재 게임 로비' : `${room.segments}개 연결 구간 · 보관 기록`));
    button.append(info); button.addEventListener('click', () => changeRoom(room.lobby)); return button;
  }
  async function changeRoom(lobby) {
    if (switching) return;
    switching++; updateSend(); requestVersion++;
    positions.set(selected, $('message-scroll').scrollTop);
    clearTimeout(draftTimer);
    try {
      await saveDraft();
      selected = lobby; before = null; signature = '';
      query = ''; $('message-search').value = ''; $('message-input').value = '';
      drawer(false); await refresh(true);
      $('message-scroll').scrollTop = positions.get(lobby) ?? $('message-scroll').scrollHeight;
    } catch (e) { showError(e); }
    finally { switching--; updateSend(); }
  }
  function renderMessages(data) {
    const scroll = $('message-scroll');
    const bottom = scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight < 60;
    const top = scroll.scrollTop;
    const nextSignature = JSON.stringify([data.messages,data.profiles,data.hidden_ok,query]);
    if (signature === nextSignature) return;
    const changed = signature !== ''; signature = nextSignature;
    const added = data.messages.filter(message => !message.own && !renderedIds.has(message.id));
    renderedIds = new Set(data.messages.map(message => message.id));
    newVisibleIds = new Set([...newVisibleIds].filter(id => renderedIds.has(id)));
    if (!changed || bottom || before !== null || query) newVisibleIds.clear();
    else for (const message of added) newVisibleIds.add(message.id);
    $('new-messages').hidden = newVisibleIds.size === 0;
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
      const profile = data.profiles[message.sender]; row.append(avatar(profile));
      const content = node('div','message-content'), meta = node('div','message-meta');
      meta.append(node('strong','', profile?.name || message.name));
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
        jump.addEventListener('click',async () => { query=''; $('message-search').value=''; before=Number.isInteger(message.seq)?message.seq+1:null; signature=''; requestVersion++; await refresh(true); document.getElementById(row.id)?.scrollIntoView({block:'center'}); });
        content.append(jump);
      }
      row.append(content); $('message-list').append(row);
    }
    $('empty-state').hidden = data.messages.length > 0;
    $('empty-title').textContent = query ? '검색 결과가 없어요' : '대화를 기다리고 있어요';
    $('empty-description').textContent = data.hidden_ok ? '앱이 연결된 동안 받은 대화만 표시합니다.' : '게임의 숨김 상태를 확인하면 상대 대화를 표시합니다.';
    if (bottom && before === null && !query) { scroll.scrollTop=scroll.scrollHeight; $('new-messages').hidden=true; }
    else scroll.scrollTop=top;
  }
  function render(data, resetDraft) {
    model = data;
    const update = data.update || {state:'development',current:''};
    $('app-version').textContent = update.current ? `v${update.current}` : '';
    $('update-status').textContent = updateStatuses[update.state] || updateStatuses.verification_failed;
    $('check-updates').disabled = ['checking','downloading','offline','development'].includes(update.state);
    theme = data.theme; collapsed = data.collapsed; applyTheme(); applySidebar();
    $('live-rooms').replaceChildren(); $('archived-rooms').replaceChildren();
    for (const room of data.rooms) (room.lobby === data.context.lobby ? $('live-rooms') : $('archived-rooms')).append(roomButton(room,room.lobby === data.context.lobby));
    const room = data.rooms.find(r => r.lobby === selected);
    $('room-title').textContent = room?.name || 'Bongo Cat Chat';
    const connected = data.state === 'ready' && data.hidden_ok;
    $('connection-label').querySelector('span').textContent = data.can_send ? '게임과 연결됨' : selected && selected !== data.context.lobby ? '보관 기록 · 읽기 전용' : connected ? '게임 수신 연결됨' : '연결 확인 중';
    document.querySelectorAll('.status-dot').forEach(el => el.classList.toggle('unavailable',!connected));
    let notice = data.notice ? notices[data.notice] || '게임 상태를 확인하지 못했어요. 연동을 중단하고 다시 확인하고 있습니다.' : '';
    if (data.notice === 'unsupported_game_build') {
      const build = /^[0-9]{1,12}$/.test(data.game_build || '') ? `게임 빌드 ${data.game_build}` : '현재 게임 파일';
      const progress = ({checking:'앱 업데이트를 확인하고 있어요.', downloading:'새 앱을 내려받고 있어요.',
        ready:'새 앱이 준비됐어요. 앱을 다시 실행하면 적용합니다.',
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
    $('account-status').textContent = connected ? 'Bongo Cat 연결됨' : '연결 확인 중';
    const accountAvatar = document.querySelector('.account-avatar');
    const replacement = avatar(data.profiles[data.context.account]); replacement.classList.add('account-avatar'); accountAvatar.replaceWith(replacement);
    const people = Object.entries(data.profiles);
    $('member-count').textContent = `${people.length}명`;
    $('participants-button').setAttribute('aria-label', `확인된 참여자 ${people.length}명 보기`);
    document.querySelector('.avatar-stack').replaceChildren(...people.slice(0,3).map(([,p])=>avatar(p)));
    $('participant-list').replaceChildren(...people.map(([,p])=>{const li=node('li'); li.append(avatar(p),node('span','participant-name',p.name)); return li;}));
    $('participants-description').textContent = '게임의 숨김 설정을 따릅니다. 외형 조회 실패는 기본 윤곽으로 표시합니다.';
    if (resetDraft) $('message-input').value = data.draft;
    $('message-input').placeholder = selected === data.context.lobby ? '메시지 입력' : '이 로비에 남겨 둘 초안';
    $('search-status').hidden=!query; $('search-summary').textContent=`현재 페이지 ${data.messages.length}개 결과`;
    $('older').hidden = !data.has_more; $('latest').hidden = before === null;
    renderMessages(data); updateSend();
  }
  async function refresh(force=false) {
    if (refreshing && !force) return;
    const version = requestVersion, editing = draftVersion;
    let lockedEditor = false;
    refreshing = true;
    try {
      let data = await rpc('view',{lobby:selected,query,before,account});
      if (version !== requestVersion) return;
      let reset = !model || data.lobby !== model.lobby;
      if (account !== data.context.account || model && model.context.lobby !== data.context.lobby && data.context.lobby) {
        // Freeze the old editor before awaiting its save. Input during the first
        // view request still belongs to the old room, never the new destination.
        switching++; lockedEditor=true; updateSend(); clearTimeout(draftTimer);
        await saveDraft();
        if (version !== requestVersion) return;
        if (account !== data.context.account) positions.clear();
        account=data.context.account; selected=data.context.lobby; before=null; query='';
        $('message-search').value=''; $('message-input').value=''; signature=''; reset=true;
        data=await rpc('view',{lobby:selected,query,before,account});
      } else if (!selected && data.context.lobby) {selected=data.context.lobby; reset=true;}
      if (version !== requestVersion) return;
      render(data,reset && (switching || editing === draftVersion));
    } catch (e) {
      if (version === requestVersion) {
        if (model) render({...model,state:'unavailable',notice:'view_unavailable',hidden_ok:false,can_send:false,messages:[],profiles:{},has_more:false},false);
        showError(e); $('send-button').disabled=true;
      }
    } finally {refreshing=false; if (lockedEditor) switching--; updateSend();}
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
      signature=''; await refresh();
    } catch(e) {showError(e);} finally {sending=false;updateSend();$('message-input').focus();}
  }
  function connect(value) {
    bridge=value;
    $('message-form').addEventListener('submit',send);
    $('message-input').addEventListener('compositionstart',()=>{composing=true;updateSend();});
    $('message-input').addEventListener('compositionend',()=>{composing=false;updateSend();});
    $('message-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!composing&&e.keyCode!==229){e.preventDefault();send();}});
    $('message-input').addEventListener('input',()=>{draftVersion++; updateSend(); clearTimeout(draftTimer); const text=$('message-input').value,room=selected,owner=account; draftTimer=setTimeout(()=>saveDraft(text,room,owner).catch(showError),150);});
    $('message-search').addEventListener('input',()=>{query=$('message-search').value;before=null;requestVersion++;refresh(true);});
    $('clear-search').addEventListener('click',()=>{query='';$('message-search').value='';before=null;requestVersion++;refresh(true);});
    $('older').addEventListener('click',()=>{before=model.messages.find(message=>Number.isInteger(message.seq))?.seq;signature='';requestVersion++;refresh(true);});
    $('latest').addEventListener('click',()=>{before=null;signature='';requestVersion++;refresh(true);});
    $('new-messages').addEventListener('click',()=>{$('message-scroll').scrollTop=$('message-scroll').scrollHeight;newVisibleIds.clear();$('new-messages').hidden=true;});
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
    document.querySelectorAll('[name=appearance]').forEach(el=>el.addEventListener('change',()=>{theme=el.value;applyTheme();rpc('setting',{key:'theme',value:theme}).catch(showError);}));
    media.addEventListener('change',applyTheme); narrow.addEventListener('change',applySidebar);
    ['delete-room','delete-all'].forEach(id=>$(id).addEventListener('click',()=>{deleteScope={account,lobby:id==='delete-room'?selected:null};$('delete-confirm').hidden=false;}));
    $('confirm-delete').addEventListener('click',async()=>{try{
      if (!deleteScope || deleteScope.account!==account) throw new Error('connection_changed');
      const scope={...deleteScope}; clearTimeout(draftTimer); requestVersion++;
      await rpc('delete',scope); $('delete-confirm').hidden=true;
      if (scope.account===account && (scope.lobby===null || scope.lobby===selected)) {
        $('message-input').value=''; selected=''; before=null; query=''; $('message-search').value='';
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
