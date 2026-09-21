// Draws only the ready records supplied by the host. No lookup or persistence.
const DRAW_MS = 180;
const FLIP_MS = 300;
const IMAGE_READY_MS = 2800;
const VISIBLE_RATIO = 0.98;
const VIEWPORT_MARGIN = 12;
const instances = new WeakMap();
let instanceSerial = 0;

/**
 * @param {HTMLElement} host
 * @param {{onDetail?: Function, onFinish?: Function, quiet?: boolean|Function, bottomBoundary?: HTMLElement, onBoundaryFit?: Function}} options
 * finish/quiet skip animation and viewport waiting, but may wait up to IMAGE_READY_MS
 * for portraits already requested by show(). onFinish signals DOM reveal, not a painted frame.
 * @returns {{show: Function, cancel: Function, finish: Function, setQuiet: Function, refreshBoundary: Function, dispose: Function}}
 */
export function initDraw(host, { onDetail, onFinish, quiet = false, bottomBoundary = null, onBoundaryFit } = {}) {
  if (!host || typeof host.replaceChildren !== 'function') {
    throw new TypeError('카드 결과를 표시할 요소가 필요합니다.');
  }
  instances.get(host)?.();
  const uid = 'cd-' + (++instanceSerial);
  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const timers = new Set();
  let quietSource = quiet;
  let sequence = 0;
  let current = null;
  let listening = false;
  let disposed = false;
  let observer = null;
  let frame = 0;
  let boundaryResize = null;
  let boundaryMutation = null;
  let boundaryListening = false;
  let boundaryFits = null;

  const root = document.createElement('section');
  root.className = 'cd-draw';
  root.setAttribute('aria-label', '준비된 인물 카드');
  root.style.setProperty('--cd-draw-ms', DRAW_MS + 'ms');
  root.style.setProperty('--cd-flip-ms', FLIP_MS + 'ms');
  root.dataset.state = 'idle';
  const grid = document.createElement('ol');
  grid.className = 'cd-grid';
  grid.setAttribute('aria-label', '인물 결과');
  const empty = document.createElement('p');
  empty.className = 'cd-empty';
  empty.textContent = '이번 결과에는 표시할 인물이 없어요.';
  empty.hidden = true;
  const live = document.createElement('p');
  live.className = 'cd-live';
  live.setAttribute('role', 'status');
  live.setAttribute('aria-live', 'polite');
  live.setAttribute('aria-atomic', 'true');
  root.append(grid, empty, live);
  host.replaceChildren(root);

  function isCurrent(run) {
    return !disposed && current === run && run.token === sequence && !run.cancelled;
  }

  function isQuiet() {
    if (motionPreference.matches) return true;
    try {
      return Boolean(typeof quietSource === 'function' ? quietSource() : quietSource);
    } catch {
      // A missing host preference must not leave a half-open card.
      return true;
    }
  }

  function clearTimers() {
    timers.forEach((timer) => clearTimeout(timer));
    timers.clear();
  }

  function stopListening() {
    observer?.disconnect();
    observer = null;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (listening) {
      motionPreference.removeEventListener('change', onMotionChange);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('scroll', queueVisibilityCheck, true);
      window.removeEventListener('resize', onViewportChange);
      window.visualViewport?.removeEventListener('resize', onViewportChange);
      window.visualViewport?.removeEventListener('scroll', queueVisibilityCheck);
    }
    listening = false;
  }

  function schedule(run, delay, callback) {
    const motionToken = run.motionToken;
    const timer = setTimeout(() => {
      timers.delete(timer);
      if (!isCurrent(run) || run.complete || run.motionToken !== motionToken) return;
      if (isQuiet()) finish();
      else if (!fullyVisible(run.cards[run.index])) resetPending(run);
      else callback();
    }, delay);
    timers.add(timer);
  }

  function updateViewportHeight() {
    const height = window.visualViewport?.height || window.innerHeight;
    // Keep the accepted card sizing. A tall dock must not shrink a card to a thumbnail.
    const value = height + 'px';
    if (root.style.getPropertyValue('--cd-viewport-height') !== value) {
      root.style.setProperty('--cd-viewport-height', value);
    }
    if (bottomBoundary && current && !current.cancelled) {
      // Measure even when the host has moved the dock into normal flow. Its height
      // and the unchanged card size make restoration independent of scroll position.
      const dock = boundaryRect(true);
      const cardHeight = Math.max(0, ...current.cards.map(card => card.item.getBoundingClientRect().height));
      const fits = !cardHeight || !dock || cardHeight + dock.height + VIEWPORT_MARGIN * 2 <= height;
      if (fits !== boundaryFits) {
        boundaryFits = fits;
        onBoundaryFit?.(fits);
      }
    }
  }

  function boundaryRect(includeFlow = false) {
    if (!bottomBoundary?.isConnected || !bottomBoundary.getClientRects().length) return null;
    const style = getComputedStyle(bottomBoundary);
    if (style.display === 'none' || style.visibility === 'hidden' ||
        (!includeFlow && !['sticky', 'fixed'].includes(style.position))) return null;
    const rect = bottomBoundary.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 ? rect : null;
  }

  function onBoundaryChange() {
    if (disposed || !current || current.cancelled) return;
    updateViewportHeight();
    queueVisibilityCheck();
  }

  function listenBoundary() {
    if (!bottomBoundary || boundaryListening) return;
    boundaryListening = true;
    // Remain active after finish/quiet: revealed cards must still fit above a
    // growing textarea, profile composer or status message. Cancel/dispose owns cleanup.
    window.addEventListener('resize', onBoundaryChange);
    window.addEventListener('scroll', onBoundaryChange, { passive: true, capture: true });
    window.visualViewport?.addEventListener('resize', onBoundaryChange);
    window.visualViewport?.addEventListener('scroll', onBoundaryChange, { passive: true });
    if ('ResizeObserver' in window) {
      boundaryResize = new ResizeObserver(onBoundaryChange);
      boundaryResize.observe(bottomBoundary);
      // Sibling profile/chat content can move the dock without changing its own size.
      if (bottomBoundary.parentElement) boundaryResize.observe(bottomBoundary.parentElement);
    }
    if ('MutationObserver' in window) {
      boundaryMutation = new MutationObserver(onBoundaryChange);
      boundaryMutation.observe(bottomBoundary, {
        attributes: true, childList: true, characterData: true, subtree: true,
      });
    }
  }

  function stopBoundaryListening() {
    boundaryResize?.disconnect();
    boundaryMutation?.disconnect();
    boundaryResize = null;
    boundaryMutation = null;
    if (boundaryListening) {
      window.removeEventListener('resize', onBoundaryChange);
      window.removeEventListener('scroll', onBoundaryChange, true);
      window.visualViewport?.removeEventListener('resize', onBoundaryChange);
      window.visualViewport?.removeEventListener('scroll', onBoundaryChange);
    }
    boundaryListening = false;
    if (boundaryFits === false) onBoundaryFit?.(true);
    boundaryFits = null;
  }

  function fullyVisible(card) {
    if (!card || document.hidden || !root.isConnected || root.closest('[hidden]')) return false;
    // Measure the stationary slot, not the transforming card.
    const rect = card.item.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    const viewport = window.visualViewport;
    const top = (viewport?.offsetTop || 0) + VIEWPORT_MARGIN;
    const left = viewport?.offsetLeft || 0;
    let bottom = top + (viewport?.height || window.innerHeight) - VIEWPORT_MARGIN * 2;
    const right = left + (viewport?.width || document.documentElement.clientWidth);
    const boundary = boundaryRect();
    if (boundary && boundary.right > left && boundary.left < right && boundary.bottom > top) {
      bottom = Math.min(bottom, boundary.top - VIEWPORT_MARGIN);
    }
    const visibleWidth = Math.max(0, Math.min(rect.right, right) - Math.max(rect.left, left));
    const visibleHeight = Math.max(0, Math.min(rect.bottom, bottom) - Math.max(rect.top, top));
    return rect.top >= top && rect.bottom <= bottom &&
      visibleWidth * visibleHeight / (rect.width * rect.height) >= VISIBLE_RATIO &&
      getComputedStyle(card.item).visibility !== 'hidden';
  }

  function resetPending(run) {
    if (!isCurrent(run) || run.complete || run.finishRequested) return;
    clearTimers();
    run.motionToken += 1;
    run.playing = false;
    const card = run.cards[run.index];
    if (card && !card.revealed) {
      card.button.classList.remove('cd-is-drawing', 'cd-is-flipping');
      card.button.dataset.state = 'waiting';
      card.front.replaceChildren();
      card.populated = false;
    }
    root.dataset.state = 'waiting';
    root.setAttribute('aria-busy', 'false');
  }

  function queueVisibilityCheck() {
    if (frame || !current || current.complete || disposed) return;
    const run = current;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!isCurrent(run) || run.complete) return;
      if (isQuiet() || run.finishRequested) { complete(run); return; }
      const visible = fullyVisible(run.cards[run.index]);
      if (run.playing && !visible) resetPending(run);
      else if (!run.playing && visible && run.ioVisible) startCard(run);
    });
  }

  function onVisibilityChange() {
    if (document.hidden && current && !current.complete) resetPending(current);
    else queueVisibilityCheck();
  }

  function onViewportChange() {
    updateViewportHeight();
    queueVisibilityCheck();
  }

  function listen(run) {
    motionPreference.addEventListener('change', onMotionChange);
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('scroll', queueVisibilityCheck, { passive: true, capture: true });
    window.addEventListener('resize', onViewportChange);
    window.visualViewport?.addEventListener('resize', onViewportChange);
    window.visualViewport?.addEventListener('scroll', queueVisibilityCheck, { passive: true });
    listening = true;
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver((entries) => {
        if (!isCurrent(run) || run.complete || run.finishRequested) return;
        const pending = run.cards[run.index];
        const entry = entries.find((candidate) => candidate.target === pending?.item);
        if (!entry) return;
        run.ioVisible = entry.isIntersecting && entry.intersectionRatio >= VISIBLE_RATIO;
        if (run.playing && !run.ioVisible) resetPending(run);
        queueVisibilityCheck();
      }, { threshold: [0, VISIBLE_RATIO, 1], rootMargin: '-12px 0px' });
    }
  }

  function cardBack() {
    const back = document.createElement('span');
    back.className = 'cd-back';
    back.setAttribute('aria-hidden', 'true');
    back.innerHTML = '<span class="cd-back-border"></span><span class="cd-back-corner cd-back-corner--top"><span class="susomun-ci susomun-ci--back" aria-hidden="true"><span class="susomun-ci-h">H</span></span></span><span class="cd-back-emblem"><span class="susomun-ci susomun-ci--back susomun-ci--emblem" aria-hidden="true"><span class="susomun-ci-h">H</span></span></span><span class="cd-back-word">수소문</span><span class="cd-back-corner cd-back-corner--bottom"><span class="susomun-ci susomun-ci--back" aria-hidden="true"><span class="susomun-ci-h">H</span></span></span>';
    return back;
  }

  function createCard(record, index, run) {
    const item = document.createElement('li');
    item.className = 'cd-item';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'cd-card';
    button.disabled = true;
    button.tabIndex = -1;
    button.setAttribute('aria-hidden', 'true');
    button.setAttribute('aria-label', '인물 카드 공개 전');
    button.dataset.state = 'waiting';
    const turn = document.createElement('span');
    turn.className = 'cd-turn';
    const front = document.createElement('span');
    front.className = 'cd-front';
    front.setAttribute('aria-hidden', 'true');
    front.inert = true;
    turn.append(cardBack(), front);
    button.append(turn);
    item.append(button);
    const card = {
      record, item, button, front, index, populated: false, revealed: false, asset: null,
    };
    button.addEventListener('click', () => {
      if (isCurrent(run) && card.revealed && !button.disabled) onDetail?.(record);
    });
    return card;
  }

  function preparePortrait(card, run) {
    // Keep the preload detached: waiting cards contain neither names nor images.
    const asset = { state: 'pending', image: null, message: '', dispose: null };
    card.asset = asset;
    let image = null;
    let timeout = 0;
    let decoding = false;
    let resolveReady;
    const ready = new Promise((resolve) => { resolveReady = resolve; });

    function cleanListeners() {
      if (timeout) clearTimeout(timeout);
      timeout = 0;
      image?.removeEventListener('load', onLoad);
      image?.removeEventListener('error', onError);
    }

    function settle(state, message = '') {
      if (asset.state !== 'pending' || !isCurrent(run)) return;
      cleanListeners();
      asset.state = state;
      asset.message = message;
      if (state === 'ready') asset.image = image;
      else {
        image?.removeAttribute('src');
        asset.image = null;
      }
      resolveReady();
    }

    function onError() {
      settle('failed', '초상을 불러오지 못했어요');
    }

    function onLoad() {
      if (asset.state !== 'pending' || !isCurrent(run) || decoding) return;
      if (!image.naturalWidth || !image.naturalHeight) { onError(); return; }
      decoding = true;
      try {
        if (typeof image.decode !== 'function') {
          settle('failed', '이 환경에서 초상 준비를 확인하지 못했어요');
          return;
        }
        Promise.resolve(image.decode()).then(() => {
          if (image.naturalWidth && image.naturalHeight) settle('ready');
          else onError();
        }, () => settle('failed', '초상을 표시하지 못했어요'));
      } catch {
        settle('failed', '초상을 표시하지 못했어요');
      }
    }

    asset.dispose = ({ retainImage = false } = {}) => {
      cleanListeners();
      const pending = asset.state === 'pending';
      asset.state = 'cancelled';
      if (!retainImage) image?.removeAttribute('src');
      asset.image = null;
      if (pending) resolveReady();
    };

    ready.then(() => {
      if (!isCurrent(run) || run.complete) return;
      if (run.finishRequested || isQuiet()) complete(run);
      else queueVisibilityCheck();
    });

    const source = typeof card.record.portrait === 'string' ? card.record.portrait.trim() : '';
    if (!source) {
      settle('failed', '등록된 초상이 없어요');
      return;
    }
    try {
      image = new Image();
      image.alt = '';
      image.setAttribute('aria-hidden', 'true');
      image.decoding = 'async';
      image.draggable = false;
      image.addEventListener('load', onLoad);
      image.addEventListener('error', onError);
      // Loading and decoding share one bound; offscreen resets do not restart it.
      timeout = setTimeout(() => settle('failed', '초상 로딩 시간이 초과됐어요'), IMAGE_READY_MS);
      image.src = source;
      if (image.complete) {
        if (image.naturalWidth && image.naturalHeight) onLoad();
        else onError();
      }
    } catch {
      onError();
    }
  }

  function populateFront(card, run) {
    if (!isCurrent(run) || card.populated || card.asset?.state === 'pending') return;
    const name = document.createElement('span');
    name.className = 'cd-name';
    name.id = uid + '-' + run.token + '-name-' + card.index;
    name.textContent = card.record.name;
    const portrait = document.createElement('span');
    portrait.className = 'cd-portrait';
    if (card.asset?.state === 'ready' && card.asset.image) {
      // Reuse the very same decoded image; no second src assignment or clone.
      portrait.append(card.asset.image);
    } else {
      portrait.classList.add('cd-portrait--empty');
      portrait.textContent = card.asset?.message || '초상을 불러오지 못했어요';
    }
    const capability = document.createElement('span');
    capability.className = 'cd-capability';
    capability.id = uid + '-' + run.token + '-capability-' + card.index;
    capability.textContent = card.record.capability || '연결된 기록을 확인해 주세요';
    capability.title = card.record.capability || '';
    card.front.append(name, portrait, capability);
    card.populated = true;
  }

  function revealCard(card, run) {
    if (!isCurrent(run) || card.revealed || card.asset?.state === 'pending') return;
    populateFront(card, run);
    card.button.classList.remove('cd-is-drawing', 'cd-is-flipping');
    card.button.classList.add('cd-is-revealed');
    card.button.dataset.state = 'revealed';
    card.button.dataset.recordId = card.record.id;
    card.front.inert = false;
    card.front.removeAttribute('aria-hidden');
    card.button.removeAttribute('aria-hidden');
    card.button.removeAttribute('aria-label');
    card.button.setAttribute('aria-labelledby', uid + '-' + run.token + '-name-' + card.index);
    card.button.setAttribute('aria-describedby', uid + '-' + run.token + '-capability-' + card.index);
    card.button.disabled = false;
    card.button.tabIndex = 0;
    card.revealed = true;
  }

  function complete(run) {
    if (!isCurrent(run) || run.complete) return;
    clearTimers();
    stopListening();
    run.finishRequested = true;
    run.playing = false;
    run.motionToken += 1;
    run.cards.forEach((card) => revealCard(card, run));
    if (run.cards.some((card) => !card.revealed)) {
      root.setAttribute('aria-busy', 'true');
      root.dataset.state = 'loading';
      live.textContent = '초상 이미지를 준비하고 있어요. 잠시 뒤 카드가 표시됩니다.';
      return;
    }
    run.complete = true;
    if (!bottomBoundary) root.style.removeProperty('--cd-viewport-height');
    root.setAttribute('aria-busy', 'false');
    root.dataset.state = run.cards.length ? 'complete' : 'empty';
    live.textContent = run.cards.length
      ? '인물 카드 ' + run.cards.length + '장을 표시했습니다. 카드를 선택하면 상세를 볼 수 있어요.'
      : '이번 결과에는 표시할 인물이 없어요.';
    // Mark complete first: a host callback may start a different show immediately.
    onFinish?.({ key: run.key, count: run.cards.length });
  }

  function drawNext(run, index) {
    if (!isCurrent(run) || run.complete) return;
    if (isQuiet() || run.finishRequested || index >= run.cards.length) { complete(run); return; }
    run.index = index;
    run.playing = false;
    run.ioVisible = !observer;
    root.dataset.state = 'waiting';
    root.setAttribute('aria-busy', 'false');
    observer?.disconnect();
    observer?.observe(run.cards[index].item);
    queueVisibilityCheck();
  }

  function startCard(run) {
    if (!isCurrent(run) || run.complete || run.playing || run.finishRequested) return;
    const index = run.index;
    const card = run.cards[index];
    if (card.asset?.state === 'pending') {
      root.dataset.state = 'loading';
      root.setAttribute('aria-busy', 'true');
      live.textContent = '카드의 초상을 준비하고 있어요.';
      return;
    }
    run.playing = true;
    run.motionToken += 1;
    root.dataset.state = 'drawing';
    root.setAttribute('aria-busy', 'true');
    card.button.dataset.state = 'drawing';
    live.textContent = '';
    // Commit the decoded face immediately before starting the visible draw.
    // It remains inert and aria-hidden until the flip has finished.
    populateFront(card, run);
    card.button.classList.add('cd-is-drawing');
    schedule(run, DRAW_MS, () => {
      card.button.classList.remove('cd-is-drawing');
      card.button.classList.add('cd-is-flipping');
      card.button.dataset.state = 'flipping';
      schedule(run, FLIP_MS, () => {
        revealCard(card, run);
        drawNext(run, index + 1);
      });
    });
  }

  function cancel({ clear = true } = {}) {
    sequence += 1;
    const run = current;
    current = null;
    if (run) {
      run.cancelled = true;
      run.cards.forEach((card) => card.asset?.dispose({ retainImage: !clear && card.revealed }));
    }
    clearTimers();
    stopListening();
    stopBoundaryListening();
    if (bottomBoundary) root.style.removeProperty('--cd-viewport-height');
    root.setAttribute('aria-busy', 'false');
    root.dataset.state = clear ? 'idle' : 'cancelled';
    live.textContent = '';
    if (clear) {
      grid.replaceChildren();
      empty.hidden = true;
    } else if (run) {
      run.cards.forEach((card) => {
        card.button.classList.remove('cd-is-drawing', 'cd-is-flipping');
        card.button.disabled = true;
        card.button.tabIndex = -1;
        if (!card.revealed) {
          card.front.replaceChildren();
          card.front.inert = true;
          card.front.setAttribute('aria-hidden', 'true');
          card.button.dataset.state = 'cancelled';
        }
      });
    }
  }

  function show(records, key) {
    if (disposed) return;
    // Same-key host renders preserve both finished cards and pending progress.
    if (current && !current.cancelled && Object.is(current.key, key)) return;
    if (!Array.isArray(records)) throw new TypeError('준비된 인물 목록이 필요합니다.');
    const ready = records.map((record) => {
      if (!record || typeof record.id !== 'string' || !record.id ||
          typeof record.name !== 'string' || !record.name.trim()) {
        throw new TypeError('인물 카드에는 등록 ID와 이름이 필요합니다.');
      }
      return { ...record };
    });
    cancel();
    const run = {
      token: sequence, key, complete: false, cancelled: false, cards: [],
      index: 0, playing: false, motionToken: 0, ioVisible: false, finishRequested: false,
    };
    current = run;
    run.cards = ready.map((record, index) => createCard(record, index, run));
    run.cards.forEach((card) => preparePortrait(card, run));
    grid.dataset.count = String(run.cards.length);
    grid.append(...run.cards.map((card) => card.item));
    empty.hidden = Boolean(run.cards.length);
    listenBoundary();
    updateViewportHeight();
    root.setAttribute('aria-busy', 'true');
    root.dataset.state = 'waiting';
    if (!run.cards.length || isQuiet()) { complete(run); return; }
    listen(run);
    drawNext(run, 0);
  }

  function finish() {
    if (current && !current.cancelled) complete(current);
  }

  function setQuiet(value) {
    if (arguments.length) quietSource = value;
    const quietNow = isQuiet();
    if (quietNow) finish();
    return quietNow;
  }

  function onMotionChange() {
    if (motionPreference.matches) finish();
  }

  function dispose() {
    cancel();
    disposed = true;
    root.remove();
    if (instances.get(host) === dispose) instances.delete(host);
  }
  instances.set(host, dispose);
  return { show, cancel, finish, setQuiet, refreshBoundary: onBoundaryChange, dispose };
}
