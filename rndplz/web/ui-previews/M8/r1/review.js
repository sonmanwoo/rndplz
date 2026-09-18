/* Static presentation harness. No fetch, model, persistence, or send operation. */
(() => {
  'use strict';

  const byId = id => document.getElementById(id);
  const data = window.M8_PREVIEW;
  const cardsRoot = byId('candidateCards');
  const holoToggle = byId('holoToggle');
  const maskToggle = byId('maskToggle');
  const openButton = byId('openRecipient');
  const resetButton = byId('resetDemo');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const fine = window.matchMedia('(hover: hover) and (pointer: fine)');
  const state = {holo:false, masked:false, proposalStatus:'보냄'};

  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };

  function fail(message) {
    const panel = byId('previewError');
    panel.textContent = message;
    panel.hidden = false;
    for (const control of [holoToggle, maskToggle, openButton, resetButton]) control.disabled = true;
  }

  function recipientName() {
    return state.masked ? data.proposal.maskedRecipientName : data.proposal.recipientName;
  }

  function updateStatus() {
    byId('viewStatus').textContent = (state.holo ? 'A + 홀로 보기' : 'A 기본') + ' · ' + (state.masked ? '이름 가림' : '이름 표시');
    byId('recipientLabel').textContent = recipientName();
    byId('proposalStatus').textContent = state.proposalStatus;
  }

  function updateMotionNote() {
    if (reduced.matches) {
      byId('motionStatus').textContent = '기기의 동작 줄이기 설정을 따릅니다. 카드 기울임과 봉투 전환 없이 편지의 끝 상태를 보여줍니다.';
    } else if (!fine.matches) {
      byId('motionStatus').textContent = '터치 환경에서는 카드가 기울지 않습니다. 홀로 표현과 봉투 열기는 그대로 살펴볼 수 있습니다.';
    } else {
      byId('motionStatus').textContent = '포인터 효과는 홀로를 켰을 때만 반응합니다. 기기의 동작 줄이기 설정도 따릅니다.';
    }
  }

  function renderCards() {
    window.RndplzHolo.destroy(cardsRoot);
    const fragment = document.createDocumentFragment();
    for (const person of data.people) {
      const template = document.createElement('template');
      template.innerHTML = state.masked ? person.maskedCardHTML : person.cardHTML;
      const card = template.content.querySelector('.candidate-card[data-person-id]');
      if (!card || card.dataset.personId !== String(person.id)) {
        throw new Error('선별 카드의 식별자가 고정 자료와 맞지 않습니다.');
      }
      if (person.virtual) {
        const evidence = card.querySelector('.evidence-block');
        if (evidence) {
          evidence.id = 'virtual-evidence';
          evidence.tabIndex = -1;
          evidence.setAttribute('aria-label','가상 현장 근거 기록');
        }
      }
      fragment.append(card);
    }
    cardsRoot.replaceChildren(fragment);
    window.RndplzHolo.decorate(cardsRoot, data.people);
    window.RndplzHolo.setEnabled(state.holo);
    updateStatus();
  }

  function focusVirtualEvidence() {
    window.RndplzEnvelope.close();
    const target = byId('virtual-evidence');
    if (!target) {
      byId('demoNotice').textContent = '가상 근거 영역을 찾지 못했습니다. 제품 API나 외부 자료는 조회하지 않았습니다.';
      return;
    }
    target.scrollIntoView({behavior:reduced.matches ? 'instant' : 'smooth',block:'center'});
    target.focus({preventScroll:true});
  }

  function interceptLocalEvidence(event) {
    const anchor = event.target.closest?.('a');
    if (!anchor || !(cardsRoot.contains(anchor) || anchor.closest('.rd-env-dialog'))) return;
    const href = anchor.getAttribute('href') || '';
    let url = null;
    try { url = new URL(href, location.href); } catch { /* Inert unavailable reference. */ }
    const localHost = url && ['localhost','127.0.0.1','[::1]'].includes(url.hostname);
    const local = !url || !['https:','http:'].includes(url.protocol)
      || url.origin === location.origin || localHost;
    if (!local && !anchor.dataset.record) return;
    event.preventDefault();
    focusVirtualEvidence();
  }

  function openRecipient() {
    const proposal = {...data.proposal, status:state.proposalStatus};
    const view = window.RndplzEnvelope.openRecipient({
      proposal,
      recipientName:recipientName(),
      body:state.masked ? data.proposal.maskedBody : data.proposal.body,
      onStatus:next => {
        if (!['수락','거절'].includes(next)) throw new Error('지원하지 않는 시연 상태입니다.');
        state.proposalStatus = next;
        updateStatus();
        byId('demoNotice').textContent = '페이지 안에서만 ' + next + '으로 표시했습니다. 새로고침 시 초기화 · 실제 저장·발송·통화 예약·본인 확인 없음';
        return {status:next};
      },
      onEvidence:focusVirtualEvidence,
      returnFocus:() => openButton
    });
    const notice = make('p','preview-dialog-note','페이지 안 시연 · 새로고침 시 초기화 · 실제 저장·발송·통화 예약 없음');
    notice.setAttribute('role','note');
    view.element.querySelector('.rd-env-dialog-header').after(notice);
    view.element.querySelector('.rd-env-demo-notice').textContent = '이 페이지 안에서만 바뀌며 새로고침하면 초기화됩니다. 실제 저장·발송·통화 예약·본인 확인은 없습니다.';
  }

  function boot() {
    if (!data || !Array.isArray(data.people) || data.people.length !== 2 || !data.proposal) {
      throw new Error('비교 자료를 불러오지 못했습니다. data.js가 함께 게시되어 있는지 확인해 주세요.');
    }
    if (!window.RndplzHolo || !window.RndplzEnvelope) {
      throw new Error('카드·봉투 표시 모듈을 불러오지 못했습니다. 비교 페이지의 파일 묶음을 확인해 주세요.');
    }
    if (data.people.some(person => !person.cardHTML || !person.maskedCardHTML)
      || !data.proposal.maskedRecipientName || !data.proposal.maskedBody) {
      throw new Error('이름 가림용 고정 자료가 빠져 있어 비교를 시작하지 않았습니다.');
    }
    document.body.dataset.layout = 'fan';
    holoToggle.checked = false;
    maskToggle.checked = false;
    state.proposalStatus = String(data.proposal.status || '보냄');
    byId('sourceCommit').textContent = String(data.commit || '미확인');
    const captured = new Date(data.capturedAt);
    byId('sourceCapturedAt').textContent = Number.isNaN(captured.valueOf()) ? '미확인'
      : new Intl.DateTimeFormat('ko-KR',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Seoul'}).format(captured) + ' (KST)';
    renderCards();
    updateMotionNote();
    for (const control of [holoToggle, maskToggle, openButton, resetButton]) control.disabled = false;

    holoToggle.addEventListener('change',() => {
      state.holo = holoToggle.checked;
      window.RndplzHolo.setEnabled(state.holo);
      updateStatus();
    });
    maskToggle.addEventListener('change',() => {
      state.masked = maskToggle.checked;
      window.RndplzEnvelope.close();
      try { renderCards(); } catch (error) { fail(error.message); }
    });
    openButton.addEventListener('click',openRecipient);
    resetButton.addEventListener('click',() => {
      window.RndplzEnvelope.close();
      state.proposalStatus = String(data.proposal.status || '보냄');
      updateStatus();
      byId('demoNotice').textContent = '페이지 안 시연 상태를 처음으로 돌렸습니다. 새로고침 시 초기화 · 실제 저장·발송 없음';
    });
    document.addEventListener('click',interceptLocalEvidence);
    reduced.addEventListener('change',updateMotionNote);
    fine.addEventListener('change',updateMotionNote);
  }

  try { boot(); } catch (error) { fail(error.message || '비교 화면을 준비하지 못했습니다.'); }
})();
