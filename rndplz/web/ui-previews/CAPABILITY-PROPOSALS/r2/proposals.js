// Isolated, synthetic UI preview. No network, persistence, or sending actions.
const MOTION_DURATION_MS = 5600;
const MIN_VISIBLE_RATIO = 0.98;
let instanceCount = 0;
const instances = new WeakMap();

const proposals = [
  {
    id: 'demo-a', recipient: '동료 A', monogram: 'A', status: 'sent', waiting: false,
    category: '15분 자문', title: '탈색·탈취 공정의 실험 방향을 함께 살펴보고 싶어요',
    preview: '다음 실험에서 무엇을 먼저 확인하면 좋을까요?', date: '시연 1일차',
    subject: '바이오공정 실험 방향에 관한 짧은 자문',
    body: [
      '안녕하세요, 동료 A님. 원료의 색과 냄새를 줄이는 공정을 가정해 작은 실험 계획을 정리하고 있습니다.',
      '현재 가설과 비교할 조건을 한 장으로 준비했어요. 어떤 변수를 먼저 확인하면 좋을지 15분 정도 의견을 나누고 싶습니다. 편한 방식과 시간은 답장을 받은 뒤 함께 정하려고 합니다.'
    ],
    mood: 'sending', moodTitle: '마음을 담아 보낸 편지',
    moodCopy: '작은 제안에서 대화가 시작될 수 있어요.',
    history: [
      ['시연 1일차 · 10:00', '편지 작성', '대화를 제안할 편지를 준비했어요.'],
      ['시연 1일차 · 10:10', '보냄', '준비한 편지를 보낸 모습이에요.']
    ]
  },
  {
    id: 'demo-b', recipient: '동료 B', monogram: 'B', status: 'sent', waiting: true,
    category: '자료 검토', title: '공정 모델의 가정이 적절한지 의견을 듣고 싶어요',
    preview: '모델의 범위와 확인할 가정을 한 장에 정리했어요.', date: '시연 2일차',
    subject: '공정 모델의 가정과 범위 검토',
    body: [
      '안녕하세요, 동료 B님. 가상의 공정 모델을 준비하며 어디까지를 모델의 범위로 삼을지 고민하고 있습니다.',
      '계산 결과보다 먼저 가정과 빠진 변수를 확인하고 싶어요. 정리한 자료를 함께 보며 중요한 질문 두세 가지를 짚어 주실 수 있을까요? 구체적인 진행 여부는 답장을 받은 뒤 의논하겠습니다.'
    ],
    mood: 'waiting', moodTitle: '답장이 올 자리를 남겨 두고',
    moodCopy: '지금 확인할 수 있는 것은 보낸 편지의 내용이에요.',
    history: [
      ['시연 1일차 · 14:00', '편지 작성', '함께 살펴볼 자료를 정리했어요.'],
      ['시연 1일차 · 14:10', '보냄', '아직 답장을 받지 않은 모습이에요.']
    ]
  },
  {
    id: 'demo-c', recipient: '동료 C', monogram: 'C', status: 'accepted', waiting: false,
    category: '15분 자문', title: '연구 질문을 다듬는 짧은 대화를 제안했어요',
    preview: '함께 이야기해 보자는 답장을 받은 모습이에요.', date: '시연 3일차',
    subject: '연구 질문과 확인할 자료를 정리하는 대화',
    body: [
      '안녕하세요, 동료 C님. 아직 넓게 열려 있는 연구 질문을 좀 더 구체적으로 만들고 싶습니다.',
      '지금까지 정리한 질문과 참고 자료를 함께 살펴보며, 먼저 확인할 부분에 대한 의견을 듣고 싶어요. 짧은 자문으로 시작하고 이후 필요한 일은 별도로 의논하면 좋겠습니다.'
    ],
    response: '좋아요. 먼저 정리하신 질문을 함께 보며 이야기해요. 일정은 다음에 맞춰 보면 좋겠습니다.',
    mood: 'accepted', moodTitle: '함께 이야기할 수 있게 되었어요',
    moodCopy: '첫 답장이 다음 대화의 문을 열어 주었어요.',
    history: [
      ['시연 2일차 · 09:00', '보냄', '질문을 함께 살펴보자는 편지를 보냈어요.'],
      ['시연 3일차 · 11:00', '수락', '이야기를 나누기로 했어요. 일정은 다음에 의논해요.']
    ]
  },
  {
    id: 'demo-d', recipient: '동료 D', monogram: 'D', status: 'declined', waiting: false,
    category: '실험 설계', title: '비교 실험 설계를 함께 검토할 수 있을지 여쭈었어요',
    preview: '이번에는 함께하기 어렵다는 답장이에요.', date: '시연 3일차',
    subject: '비교 실험 설계에 대한 의견 요청',
    body: [
      '안녕하세요, 동료 D님. 몇 가지 조건을 비교하는 실험을 가정해 계획을 정리하고 있습니다.',
      '비교 기준이 충분한지, 먼저 줄여야 할 불확실성이 무엇인지 의견을 듣고 싶어요. 가능하신 범위에서 짧게 검토를 부탁드리고자 편지를 남깁니다.'
    ],
    response: '제안해 주셔서 고맙습니다. 이번에는 일정상 참여하기 어렵습니다. 준비하시는 연구가 잘 진행되기를 바랍니다.',
    mood: 'declined', moodTitle: '이번 편지는 여기까지',
    moodCopy: '함께하지 못해도 제안의 내용은 차분히 남겨 둘 수 있어요.',
    history: [
      ['시연 2일차 · 16:00', '보냄', '실험 설계에 대한 의견을 부탁했어요.'],
      ['시연 3일차 · 15:00', '거절', '이번에는 참여가 어렵다는 답장을 받았어요.']
    ]
  }
];

const filters = [
  { id: 'all', label: '전체', match: () => true },
  { id: 'waiting', label: '응답 대기', match: (item) => item.status === 'sent' },
  { id: 'accepted', label: '수락', match: (item) => item.status === 'accepted' },
  { id: 'declined', label: '거절', match: (item) => item.status === 'declined' }
];

const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[char]);

function statusLabel(item) {
  if (item.waiting) return '응답 대기';
  return { sent: '보냄', accepted: '수락', declined: '거절' }[item.status];
}

const replayIcon = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5.1 5.3A6.1 6.1 0 1 1 4 12M5.1 5.3V1.9M5.1 5.3H1.8"/></svg>';
const arrowIcon = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h11M11 5l5 5-5 5"/></svg>';

function scene(item) {
  const glyph = item.status === 'accepted'
    ? '<path d="m7 13 4 4 8-9"/>'
    : item.status === 'declined' ? '<path d="m8 8 10 10M18 8 8 18"/>' : '';
  return '<div class="pr-scene pr-scene--' + item.mood + '" data-motion-state="queued" data-motion-run="0" aria-hidden="true">' +
    '<div class="pr-horizon"></div><div class="pr-cloud pr-cloud--one"></div>' +
    '<div class="pr-cloud pr-cloud--two"></div><div class="pr-cloud pr-cloud--three"></div>' +
    '<svg class="pr-plane" viewBox="0 0 70 55"><path d="M4 23 65 5 39 48 29 31Z" fill="#fffdf7"/><path d="m29 31 36-26-28 30 2 13" fill="#d5c9e7"/><path d="m4 23 25 8L65 5" fill="none" stroke="#fffdf7" stroke-width="1.5"/></svg>' +
    '<svg class="pr-rain" viewBox="0 0 300 170"><g><path d="m28 48-5 15m58-22-5 15m61-6-5 15m63-21-5 15m56-8-5 15m-168 22-5 15m61 3-5 15m62-22-5 15m52-3-5 15"/></g></svg>' +
    '<div class="pr-orbit"></div><div class="pr-envelope"><div class="pr-envelope-back"></div>' +
    '<div class="pr-note"><span>함께 생각해 볼까요</span><i></i><i></i><i></i><small>' + escapeHTML(item.recipient) + '에게</small></div>' +
    '<div class="pr-envelope-front"></div><div class="pr-envelope-flap"></div>' +
    '<div class="pr-seal"><svg viewBox="0 0 24 24"><path d="M8 15c5 1 9-3 9-9-6 0-10 4-9 9Zm0 0-3 4m3-4 5-5"/></svg></div></div>' +
    (glyph ? '<div class="pr-status-glyph"><svg viewBox="0 0 26 26" aria-hidden="true">' + glyph + '</svg></div>' : '') +
    '<span class="pr-scene-caption">A SMALL NOTE, A NEW CONVERSATION</span></div>';
}

/** Mount the isolated preview. Call the returned function before removing it. */
export function initProposals(container) {
  if (!container || typeof container.replaceChildren !== 'function') {
    throw new TypeError('제안함을 표시할 요소가 필요합니다.');
  }
  instances.get(container)?.();
  const uid = 'pr-' + (++instanceCount);
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let filterId = 'all';
  let selectedId = proposals[0].id;
  let playTimer = null;
  let playFrame = null;
  let motionEpoch = 0;
  let observationEpoch = 0;
  let sceneNode = null;
  let sceneObserver = null;
  let sceneIntersects = false;
  let paneVisible = false;
  let disposed = false;
  const root = document.createElement('section');
  root.className = 'pr-workspace';
  root.setAttribute('aria-label', '보낸 제안함 가상 시안');
  container.replaceChildren(root);
  root.innerHTML =
    '<p class="pr-demo-note"><span class="pr-demo-chip">가상 제안 시안 · 실제 발송 없음</span>인물과 편지, 답장은 모두 가상 예시입니다.</p>' +
    '<div class="pr-layout"><aside class="pr-sidebar" aria-label="제안 목록"><div class="pr-list-heading"><h2>보낸 편지</h2><span>예시 4개</span></div>' +
    '<div class="pr-tabs" role="tablist" aria-label="제안 상태">' + filters.map((filter, index) =>
      '<button type="button" role="tab" id="' + uid + '-tab-' + filter.id + '" aria-controls="' + uid + '-list-panel" aria-selected="' + (index === 0) + '" tabindex="' + (index === 0 ? '0' : '-1') + '" data-pr-filter="' + filter.id + '">' + filter.label + '<span>' + proposals.filter(filter.match).length + '</span></button>'
    ).join('') + '</div><div class="pr-list-panel" id="' + uid + '-list-panel" role="tabpanel" aria-labelledby="' + uid + '-tab-all"><ul class="pr-list"></ul></div>' +
    '<p class="pr-filter-note">응답 대기는 답장이 없는 보낸 편지의 화면 분류예요. 상대의 읽음이나 검토 여부를 뜻하지 않습니다.</p></aside>' +
    '<div class="pr-detail-host"></div></div><p class="pr-live" role="status" aria-live="polite" aria-atomic="true"></p>';

  const list = root.querySelector('.pr-list');
  const detail = root.querySelector('.pr-detail-host');
  const live = root.querySelector('.pr-live');
  const tabButtons = Array.from(root.querySelectorAll('[data-pr-filter]'));

  function renderList() {
    const currentFilter = filters.find((filter) => filter.id === filterId);
    const visible = proposals.filter(currentFilter.match);
    if (!visible.some((item) => item.id === selectedId)) selectedId = visible[0]?.id;
    list.innerHTML = visible.map((item) =>
      '<li><button type="button" class="pr-list-item" data-pr-item="' + item.id + '" aria-pressed="' + (item.id === selectedId) + '" aria-controls="' + uid + '-detail"><span class="pr-item-top"><span class="pr-avatar" aria-hidden="true">' + item.monogram + '</span><span class="pr-recipient">' + item.recipient + '<small>가상 인물</small></span><span class="pr-status pr-status--' + item.mood + '">' + statusLabel(item) + '</span></span><span class="pr-item-title">' + escapeHTML(item.title) + '</span><span class="pr-item-preview">' + escapeHTML(item.preview) + '</span><span class="pr-item-meta"><span>' + item.category + '</span><span>' + item.date + '</span></span></button></li>'
    ).join('');
  }

  function isCurrentScene(node) {
    return !disposed && node === sceneNode && node?.isConnected && detail.contains(node);
  }

  function visibleRatio(node) {
    const rect = node.getBoundingClientRect();
    if (!rect.width || !rect.height) return 0;
    const width = Math.max(0, Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0));
    const height = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
    return (width * height) / (rect.width * rect.height);
  }

  function paneCanBeSeen(node) {
    return isCurrentScene(node) && paneVisible && !document.hidden && !node.closest('[hidden]');
  }

  function canPlay(node) {
    return paneCanBeSeen(node) && sceneIntersects && visibleRatio(node) >= MIN_VISIBLE_RATIO;
  }

  function revealScene() {
    if (paneCanBeSeen(sceneNode) && visibleRatio(sceneNode) < MIN_VISIBLE_RATIO) {
      sceneNode.scrollIntoView({ behavior: reducedMotion.matches ? 'auto' : 'smooth', block: 'center', inline: 'nearest' });
    }
  }

  function setMotionHint(text) {
    const hint = detail.querySelector('.pr-motion-hint');
    if (hint) hint.textContent = text;
  }

  function cancelPlayback() {
    motionEpoch += 1;
    if (playFrame !== null) cancelAnimationFrame(playFrame);
    if (playTimer !== null) clearTimeout(playTimer);
    playFrame = null;
    playTimer = null;
  }

  function stopObservation() {
    observationEpoch += 1;
    sceneObserver?.disconnect();
    sceneObserver = null;
    sceneIntersects = false;
  }

  function pauseMotion() {
    cancelPlayback();
    if (sceneNode?.dataset.motionState === 'playing') {
      sceneNode.classList.remove('pr-is-playing', 'pr-is-complete');
      sceneNode.dataset.motionState = 'queued';
    }
  }

  function detachScene() {
    stopObservation();
    pauseMotion();
    sceneNode = null;
  }

  function applyReducedMotion() {
    cancelPlayback();
    if (!isCurrentScene(sceneNode)) return;
    sceneNode.classList.remove('pr-is-playing');
    sceneNode.classList.add('pr-is-complete');
    sceneNode.dataset.motionState = 'reduced';
    setMotionHint('움직임 없이 작은 편지를 보여 드려요.');
  }

  function startWhenVisible(node) {
    if (!isCurrentScene(node) || node.dataset.motionState !== 'queued' || playFrame !== null) return;
    if (reducedMotion.matches) { applyReducedMotion(); return; }
    if (!canPlay(node)) return;
    const epoch = ++motionEpoch;
    playFrame = requestAnimationFrame(() => {
      if (epoch !== motionEpoch || !isCurrentScene(node)) return;
      playFrame = null;
      if (!canPlay(node)) return;
      if (reducedMotion.matches) { applyReducedMotion(); return; }
      node.classList.remove('pr-is-complete');
      node.classList.add('pr-is-playing');
      node.dataset.motionState = 'playing';
      node.dataset.motionRun = String(Number(node.dataset.motionRun || 0) + 1);
      setMotionHint('마음을 담은 편지가 자리를 찾아가요.');
      playTimer = setTimeout(() => {
        if (epoch !== motionEpoch || !isCurrentScene(node)) return;
        playTimer = null;
        if (reducedMotion.matches) { applyReducedMotion(); return; }
        if (!canPlay(node)) { pauseMotion(); return; }
        node.classList.remove('pr-is-playing');
        node.classList.add('pr-is-complete');
        node.dataset.motionState = 'complete';
        setMotionHint('작은 편지가 자리를 잡았어요.');
      }, MOTION_DURATION_MS);
    });
  }

  function observeScene() {
    stopObservation();
    const node = sceneNode;
    if (!isCurrentScene(node)) return;
    if (reducedMotion.matches) { applyReducedMotion(); return; }
    if (!paneCanBeSeen(node)) { pauseMotion(); return; }
    if (['complete', 'reduced'].includes(node.dataset.motionState)) return;
    if (typeof IntersectionObserver !== 'function') {
      cancelPlayback();
      node.classList.remove('pr-is-playing');
      node.classList.add('pr-is-complete');
      node.dataset.motionState = 'complete';
      setMotionHint('작은 편지에 마음을 담았어요.');
      return;
    }
    const epoch = observationEpoch;
    sceneObserver = new IntersectionObserver((entries) => {
      if (epoch !== observationEpoch || !isCurrentScene(node)) return;
      const entry = entries.find((item) => item.target === node);
      if (!entry) return;
      sceneIntersects = entry.isIntersecting && entry.intersectionRatio >= MIN_VISIBLE_RATIO;
      if (!sceneIntersects || !paneCanBeSeen(node)) pauseMotion();
      else startWhenVisible(node);
    }, { threshold: [0, MIN_VISIBLE_RATIO, 1] });
    sceneObserver.observe(node);
  }

  function attachScene() {
    sceneNode = detail.querySelector('.pr-scene');
    setMotionHint('작은 편지에 마음을 담았어요.');
    observeScene();
  }

  function replay() {
    const node = sceneNode;
    if (!isCurrentScene(node)) return;
    stopObservation();
    cancelPlayback();
    node.classList.remove('pr-is-playing', 'pr-is-complete');
    node.dataset.motionState = 'queued';
    if (paneCanBeSeen(node) && visibleRatio(node) < MIN_VISIBLE_RATIO) {
      node.scrollIntoView({ behavior: reducedMotion.matches ? 'auto' : 'smooth', block: 'center', inline: 'nearest' });
    }
    if (reducedMotion.matches) {
      applyReducedMotion();
      live.textContent = '움직임 없이 작은 편지를 표시했습니다.';
    } else {
      live.textContent = '편지의 움직임을 다시 보여 드려요. 제안 상태는 바뀌지 않습니다.';
      observeScene();
    }
  }

  function renderDetail() {
    detachScene();
    const item = proposals.find((proposal) => proposal.id === selectedId);
    if (!item) return;
    detail.innerHTML = '<article class="pr-detail" id="' + uid + '-detail" aria-labelledby="' + uid + '-detail-title">' +
      '<header class="pr-detail-heading"><div><p class="pr-eyebrow">' + item.category + ' · 제안 편지</p><h2 id="' + uid + '-detail-title" tabindex="-1">' + item.recipient + '에게 보낸 편지</h2></div><span class="pr-status pr-status--' + item.mood + '">' + statusLabel(item) + '</span></header>' +
      '<section class="pr-atmosphere" aria-label="상태 분위기 시안">' + scene(item) +
      '<div class="pr-atmosphere-copy"><div><p class="pr-mood-title">' + item.moodTitle + '</p><p>' + item.moodCopy + '</p></div><button type="button" class="pr-replay" data-pr-action="replay">' + replayIcon + '모션 다시 보기</button></div><p class="pr-motion-hint"></p></section>' +
      '<section class="pr-letter" aria-labelledby="' + uid + '-letter-title"><div class="pr-letter-meta"><span>TO. ' + item.recipient + ' · 가상 인물</span><span>FROM. 나 · 시안 속 작성자</span></div><h3 id="' + uid + '-letter-title">' + escapeHTML(item.subject) + '</h3>' + item.body.map((paragraph) => '<p>' + escapeHTML(paragraph) + '</p>').join('') + '<p class="pr-signature">함께 생각할 기회를 바라며,<br>시안 속 작성자 드림</p></section>' +
      (item.response ? '<section class="pr-response" aria-label="답장 예시"><p class="pr-eyebrow">' + item.recipient + '의 답장</p><blockquote>' + escapeHTML(item.response) + '</blockquote></section>' : '') +
      '<section class="pr-history" aria-labelledby="' + uid + '-history-title"><div class="pr-history-heading"><h3 id="' + uid + '-history-title">편지의 발자취</h3><span>시안 예시</span></div><ol>' + item.history.map((entry) => '<li><span class="pr-history-dot" aria-hidden="true"></span><p class="pr-history-time">' + entry[0] + '</p><h4>' + entry[1] + '</h4><p>' + entry[2] + '</p></li>').join('') + '</ol>' +
      '</section><footer class="pr-detail-footer"><span>작은 편지에서 시작하는 대화</span><button type="button" class="pr-back" data-pr-action="back">목록으로 돌아가기' + arrowIcon + '</button></footer></article>';
    root.querySelectorAll('[data-pr-item]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.prItem === selectedId));
    });
    attachScene();
  }

  function setFilter(id, moveFocus) {
    filterId = id;
    tabButtons.forEach((button) => {
      const active = button.dataset.prFilter === id;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
      if (active && moveFocus) button.focus();
    });
    root.querySelector('.pr-list-panel').setAttribute('aria-labelledby', uid + '-tab-' + id);
    renderList();
    renderDetail();
    revealScene();
    const filter = filters.find((entry) => entry.id === id);
    live.textContent = filter.label + ' 예시 ' + proposals.filter(filter.match).length + '개. ' + proposals.find((item) => item.id === selectedId).recipient + '의 편지를 표시했습니다.';
  }

  function onClick(event) {
    const button = event.target.closest('button');
    if (!button || !root.contains(button)) return;
    if (button.dataset.prFilter) {
      setFilter(button.dataset.prFilter, false);
    } else if (button.dataset.prItem) {
      selectedId = button.dataset.prItem;
      renderDetail();
      const item = proposals.find((entry) => entry.id === selectedId);
      live.textContent = item.recipient + '의 편지, ' + statusLabel(item) + '. 편지 내용을 표시했습니다.';
      if (event.detail === 0 || window.matchMedia('(max-width: 760px)').matches) {
        const title = detail.querySelector('h2');
        title.focus({ preventScroll: true });
      }
      revealScene();
    } else if (button.dataset.prAction === 'replay') {
      replay();
    } else if (button.dataset.prAction === 'back') {
      const selected = root.querySelector('[data-pr-item="' + selectedId + '"]');
      selected?.focus({ preventScroll: true });
      selected?.scrollIntoView({ behavior: reducedMotion.matches ? 'auto' : 'smooth', block: 'nearest' });
    }
  }

  function onKeydown(event) {
    if (!event.target.matches('[role="tab"]')) return;
    const index = tabButtons.indexOf(event.target);
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % filters.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + filters.length) % filters.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = filters.length - 1;
    else return;
    event.preventDefault();
    setFilter(filters[next].id, true);
  }

  function onMotionChange() {
    stopObservation();
    cancelPlayback();
    if (reducedMotion.matches) {
      applyReducedMotion();
    } else if (isCurrentScene(sceneNode)) {
      // Changing the OS setting does not replay an already static scene.
      if (sceneNode.dataset.motionState === 'reduced') {
        sceneNode.dataset.motionState = 'complete';
        setMotionHint('모션 다시 보기로 편지의 움직임을 볼 수 있어요.');
      }
      observeScene();
    }
  }

  function onVisibilityChange() {
    if (document.hidden) {
      stopObservation();
      pauseMotion();
    } else {
      observeScene();
    }
  }
  root.addEventListener('click', onClick);
  root.addEventListener('keydown', onKeydown);
  reducedMotion.addEventListener('change', onMotionChange);
  document.addEventListener('visibilitychange', onVisibilityChange);
  renderList();
  renderDetail();

  function destroy() {
    if (disposed) return;
    disposed = true;
    detachScene();
    root.removeEventListener('click', onClick);
    root.removeEventListener('keydown', onKeydown);
    reducedMotion.removeEventListener('change', onMotionChange);
    document.removeEventListener('visibilitychange', onVisibilityChange);
    root.remove();
    if (instances.get(container) === destroy) instances.delete(container);
  }
  destroy.setVisible = (value) => {
    if (disposed) return;
    const nextVisible = Boolean(value);
    if (nextVisible === paneVisible) return;
    paneVisible = nextVisible;
    if (!paneVisible) {
      stopObservation();
      pauseMotion();
    } else {
      observeScene();
    }
  };
  instances.set(container, destroy);
  return destroy;
}
