/* Opt-in presentation only. Persistence and evidence authorization belong to the caller. */
(() => {
  'use strict';
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const modes = {advice:'자문',verify:'검증 요청',member:'프로젝트 멤버',site_request:'현장 의뢰',resource_request:'자원 요청'};
  let activeSend = null;
  let activeRecipient = null;
  let serial = 0;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function button(className, text, title, handler) {
    const node = element('button', className, text);
    node.type = 'button'; node.title = title;
    if (handler) node.addEventListener('click', handler);
    return node;
  }
  function safeHTTP(value) {
    try {
      const url = new URL(String(value || ''), location.origin);
      return value && ['http:', 'https:'].includes(url.protocol) ? url : null;
    } catch { return null; }
  }
  function dateLabel(value) {
    const parsed = new Date(value || '');
    return Number.isNaN(parsed.valueOf()) ? '날짜 미확인' : parsed.toLocaleDateString('ko-KR');
  }
  function envelope(name, interactive, onOpen) {
    const node = interactive ? button('rd-env-object', '', '봉투를 열어 제안문 읽기', onOpen) : element('div', 'rd-env-object');
    if (interactive) node.setAttribute('aria-label', String(name || '받는 사람') + '님에게 온 봉투 열기');
    const back = element('span', 'rd-env-back');
    const paper = element('span', 'rd-env-paper');
    const paperTop = element('span', 'rd-env-paper-top');
    const paperBottom = element('span', 'rd-env-paper-bottom');
    for (const half of [paperTop, paperBottom]) {
      half.append(element('i', 'rd-env-paper-line'), element('i', 'rd-env-paper-line'), element('i', 'rd-env-paper-line'));
    }
    paper.append(paperTop, paperBottom);
    const face = element('span', 'rd-env-face');
    const flap = element('span', 'rd-env-flap');
    const recipient = element('span', 'rd-env-recipient', name || '받는 사람');
    for (const decor of [back, paper, face, flap]) decor.setAttribute('aria-hidden','true');
    node.append(back, paper, face, flap, recipient);
    return node;
  }

  async function playSend({recipientName='', first=false, count=1, anchor=null} = {}) {
    if (activeSend) activeSend.finish();
    const reduced = reduceMotion();
    if (reduced || document.hidden) return {duration_ms:0,reduced,fullAnimation:false};
    const fullAnimation = !!first;
    const started = performance.now();
    return new Promise(resolve => {
      const timers = new Set();
      const overlay = element('div','rd-env-send-overlay');
      overlay.dataset.phase = fullAnimation ? 'paper' : 'sealed';
      overlay.setAttribute('role','status'); overlay.setAttribute('aria-live','polite');
      const scene = element('div','rd-env-send-scene');
      scene.append(envelope(String(recipientName),false));
      const amount = Math.max(1, Math.min(7, Number(count) || 1));
      const notice = element('p','rd-env-send-notice',`제안 ${amount}건 저장 · 내 사본 보관 · 외부 전송 없음`);
      overlay.append(scene, notice); document.body.append(overlay);
      const rect = anchor && typeof anchor.getBoundingClientRect === 'function' ? anchor.getBoundingClientRect() : null;
      const targetX = rect ? rect.left + rect.width/2 : innerWidth - 62;
      const targetY = rect ? rect.top + rect.height/2 : 48;
      scene.style.setProperty('--rd-env-dx',`${targetX-innerWidth/2}px`);
      scene.style.setProperty('--rd-env-dy',`${targetY-innerHeight/2}px`);
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true; for (const timer of timers) clearTimeout(timer);
        document.removeEventListener('keydown', escape);
        document.removeEventListener('visibilitychange', visibility);
        overlay.remove();
        if (activeSend?.finish === finish) activeSend = null;
        resolve({duration_ms:Math.round(performance.now()-started),reduced,fullAnimation});
      };
      const escape = event => { if(event.key==='Escape') finish(); };
      const visibility = () => { if(document.hidden) finish(); };
      const after = (delay, phase) => timers.add(setTimeout(() => {if(!finished)overlay.dataset.phase=phase;},delay));
      activeSend = {finish};
      document.addEventListener('keydown', escape);
      document.addEventListener('visibilitychange', visibility);
      if (fullAnimation) {
        after(240,'folding'); after(670,'inserting'); after(1120,'sealed'); after(1450,'flying');
        timers.add(setTimeout(finish,2150));
      } else {
        after(50,'flying'); timers.add(setTimeout(finish,500));
      }
    });
  }

  function appendLinkedText(parent, text) {
    const pattern = /\[([^\]]+)\]\(([^)]+)\)/g;
    let cursor = 0;
    for (const match of String(text).matchAll(pattern)) {
      parent.append(document.createTextNode(String(text).slice(cursor,match.index)));
      const url = safeHTTP(match[2]);
      if (url) {
        const link = element('a','',match[1]); link.href=url.href; link.target='_blank'; link.rel='noopener noreferrer'; link.title='인용된 근거 기록 열기'; parent.append(link);
      } else parent.append(document.createTextNode(match[1]));
      cursor = match.index + match[0].length;
    }
    parent.append(document.createTextNode(String(text).slice(cursor)));
  }
  function letterBody(text, recipientName) {
    const content = element('div','rd-env-body');
    let paragraph = [], quote = [];
    const flushParagraph = () => {
      if (!paragraph.length) return;
      const p = element('p'); appendLinkedText(p,paragraph.join('\n')); content.append(p); paragraph=[];
    };
    const flushQuote = () => {
      if(!quote.length)return;
      const block = element('blockquote','rd-env-quote');
      block.append(element('small','','검증 대상 · 인용한 주장'));
      const p=element('p', '',quote.join('\n'));block.append(p);content.append(block);quote=[];
    };
    for (const line of String(text || '').split(/\r?\n/)) {
      if (/^# 수소문(?:\s|$)/.test(line) || line.trim()===String(recipientName)+'님께,' || /^— 제안자/.test(line)) continue;
      if (/^>\s?/.test(line)) {flushParagraph();quote.push(line.replace(/^>\s?/,''));continue;}
      flushQuote();
      if (/^#{1,3}\s/.test(line)) {flushParagraph();content.append(element('h3','',line.replace(/^#{1,3}\s+/,'')));}
      else if (!line.trim()) flushParagraph();
      else paragraph.push(line.replace(/^- \[ \] /,'□ ').replace(/^- /,'• '));
    }
    flushQuote();flushParagraph();return content;
  }

  function openRecipient({proposal={},recipientName='',body='',onStatus,onEvidence,returnFocus} = {}) {
    if (activeRecipient) activeRecipient.close();
    const previousFocus=document.activeElement;
    const timers=new Set();
    let closed=false, opening=false, pending=false, status=String(proposal.status || '초안');
    const identifier='rd-env-'+(++serial);
    const dialog=element('dialog','rd-env-dialog');dialog.dataset.phase='sealed';
    dialog.setAttribute('aria-labelledby',identifier+'-title');
    const header=element('header','rd-env-dialog-header');
    const title=element('h2','', '(시연) 받는 사람으로 보기');title.id=identifier+'-title';
    const closeButton=button('rd-env-close','×','봉투 시연 닫기',closeRecipient);closeButton.setAttribute('aria-label','봉투 시연 닫기');
    header.append(title,closeButton);
    const stage=element('div','rd-env-receive-stage');
    const object=envelope(String(recipientName),true,openLetter);
    stage.append(element('p','rd-env-stage-caption','누군가의 질문이 도착했습니다.'),object,element('p','rd-env-stage-hint','봉투를 눌러 요청을 읽어보세요.'));
    const letter=element('article','rd-env-letter');letter.hidden=true;
    const meta=element('p','rd-env-letter-meta',`수소문 · ${dateLabel(proposal.created)} · ${modes[proposal.request_kind] || '협업 요청'}`);
    const greeting=element('h2','rd-env-greeting',`${String(recipientName || '받는 사람')}님께,`);greeting.tabIndex=-1;
    letter.append(meta);
    if(proposal.route_order)letter.append(element('p','rd-env-route',`경로 ${Number(proposal.route_order)}/${Number(proposal.route_total) || '?'}`));
    if(proposal.virtual)letter.append(element('p','rd-env-virtual','가상 현장 기록 · 시연용 인물과 경험에 대한 제안입니다.'));
    letter.append(greeting,letterBody(String(body),String(recipientName)),element('p','rd-env-signature','— 제안자'));
    const evidence=element('details','rd-env-evidence');
    const summary=element('summary','','왜 저에게 왔나요?');summary.title='이 요청과 연결된 근거 기록 확인';evidence.append(summary);
    evidence.append(element('p','','아래 기록의 참여 사실과 요청 조건을 연결했습니다. 개인 수행과 현재 가용성은 확인되지 않았습니다.'));
    const evidenceList=element('ul');
    for(const record of proposal.evidence || []) {
      const row=element('li');
      const url=safeHTTP(record.url);
      const local=!!record.virtual || (url?.origin===location.origin && url.pathname==='/api/record');
      if((local || !url) && record.id && typeof onEvidence==='function') {
        row.append(button('rd-env-evidence-button',String(record.title || '근거 기록'),'가상 또는 로컬 근거 기록 열기',() => {
          closeRecipient();Promise.resolve().then(()=>onEvidence(record.id)).catch(()=>{});
        }));
      } else if(url && !local) {
        const anchor=element('a','',record.title || '근거 기록');anchor.href=url.href;anchor.target='_blank';anchor.rel='noopener noreferrer';anchor.title='외부 근거 원문 열기';row.append(anchor);
      } else row.append(element('span','',record.title || '근거 기록'));
      if(record.date)row.append(element('small','',String(record.date)));
      if(record.virtual)row.append(element('small','rd-env-virtual','가상 현장 기록'));
      evidenceList.append(row);
    }
    evidence.append(evidenceList);letter.append(evidence);
    const notice=element('p','rd-env-demo-notice','시연 상태만 바뀝니다. 실제 통화 예약·메시지 전송·본인 확인이 아닙니다.');
    const result=element('p','rd-env-response');result.setAttribute('role','status');result.setAttribute('aria-live','polite');
    const actions=element('div','rd-env-actions');
    const accept=button('rd-env-primary','(시연) 수락하고 15분 통화','시연 상태를 수락으로 바꾸기. 실제 통화는 예약하지 않습니다.',()=>respond('수락'));
    const later=button('rd-env-secondary','나중에','상태를 바꾸지 않고 봉투 보기 닫기',closeRecipient);
    const decline=button('rd-env-secondary','(시연) 정중히 거절','시연 상태를 거절로 바꾸기',()=>respond('거절'));
    actions.append(accept,later,decline);letter.append(notice,result,actions);
    dialog.append(header,stage,letter);

    function syncActions() {
      const eligible=status==='보냄' && typeof onStatus==='function';
      accept.disabled=pending || !eligible;decline.disabled=pending || !eligible;
      accept.setAttribute('aria-busy',String(pending));decline.setAttribute('aria-busy',String(pending));
      if(!eligible && !pending)result.textContent=status!=='보냄'?`현재 상태: ${status} · 보냄 상태의 제안에만 응답할 수 있습니다.`:'상태 변경 연결이 없어 읽기만 가능합니다.';
    }
    async function respond(next) {
      if(closed || pending || status!=='보냄' || typeof onStatus!=='function')return;
      pending=true;result.classList.remove('is-error');result.textContent=`시연 상태를 ${next}으로 기록하고 있어요.`;syncActions();
      try {
        const updated=await onStatus(next);
        if(closed)return;
        status=updated && typeof updated==='object' && updated.status ? String(updated.status) : next;
        pending=false;syncActions();
        result.textContent=`시연 상태를 ${status}으로 기록했습니다. 실제 통화 예약·본인 확인은 이루어지지 않았습니다.`;
      } catch(error) {
        if(closed)return;
        pending=false;syncActions();result.classList.add('is-error');
        result.textContent='상태를 바꾸지 못했습니다. 제안문은 그대로 있습니다. 같은 버튼으로 다시 시도해 주세요.';
      }
    }
    function showLetter() {
      if(closed)return;
      stage.hidden=true;letter.hidden=false;dialog.dataset.phase='reading';
      greeting.focus({preventScroll:true});dialog.scrollTop=0;
    }
    function openLetter() {
      if(closed || opening)return;opening=true;object.disabled=true;
      if(reduceMotion()){showLetter();return;}
      dialog.dataset.phase='opening';
      timers.add(setTimeout(()=>{if(!closed)dialog.dataset.phase='extracting';},330));
      timers.add(setTimeout(showLetter,760));
    }
    function closeRecipient() {
      if(closed)return;closed=true;for(const timer of timers)clearTimeout(timer);
      if(dialog.open)dialog.close();dialog.remove();
      if(activeRecipient?.dialog===dialog)activeRecipient=null;
      const target=previousFocus?.isConnected ? previousFocus : (typeof returnFocus==='function' ? returnFocus() : null);
      if(target?.isConnected && typeof target.focus==='function')target.focus({preventScroll:true});
    }
    dialog.addEventListener('cancel',event=>{event.preventDefault();closeRecipient();});
    dialog.addEventListener('close',closeRecipient);
    activeRecipient={dialog,close:closeRecipient};syncActions();document.body.append(dialog);dialog.showModal();
    if(reduceMotion())showLetter();else object.focus({preventScroll:true});
    return {element:dialog,close:closeRecipient};
  }

  function close() {
    if(activeSend)activeSend.finish();
    if(activeRecipient)activeRecipient.close();
  }
  window.RndplzEnvelope=Object.freeze({playSend,openRecipient,close});
})();
