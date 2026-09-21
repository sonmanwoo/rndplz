(() => {
  'use strict';

  function initMotion() {
    const playAll = document.getElementById('playAll');
    const stopAll = document.getElementById('stopAll');
    const note = document.getElementById('motionNote');
    const buttons = [...document.querySelectorAll('[data-play-h]')];
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const supported = typeof Element.prototype.animate === 'function';
    const cards = [...document.querySelectorAll('[data-h-card]')].map((element, index) => ({
      element,
      keys: [element.dataset.hCard, element.id].filter(Boolean),
      label: element.querySelector('h2, h3')?.textContent.trim() || `H 비교 ${index + 1}`,
      electrons: [...element.querySelectorAll('.brand-symbol .electron')],
      status: element.querySelector('[data-motion-status]'),
      animations: [],
      generation: 0,
      running: false
    }));
    const findCard = key => {
      const matches = cards.filter(card => card.keys.includes(key));
      return matches.length === 1 ? matches[0] : null;
    };
    const playable = cards.filter(card => card.electrons.length > 0);
    let batchGeneration = 0;

    if (note) {
      note.setAttribute('role', 'status');
      note.setAttribute('aria-live', 'polite');
      note.setAttribute('aria-atomic', 'true');
    }
    const announce = text => { if (note) note.textContent = text; };

    function updateButtons() {
      const unavailable = preference.matches || !supported;
      buttons.forEach(button => {
        const card = findCard(button.dataset.playH);
        button.disabled = unavailable || !card || card.electrons.length === 0;
        // Keep the active button focusable; repeated clicks cannot start another run.
        button.setAttribute('aria-disabled', String(button.disabled || card?.running || false));
      });
      if (playAll) {
        playAll.disabled = unavailable || playable.length === 0;
        playAll.setAttribute('aria-disabled', String(playAll.disabled || playable.every(card => card.running)));
      }
    }

    function cancelCard(card, freeze, status = '정지') {
      card.generation += 1;
      const poses = freeze ? card.electrons.map(el => getComputedStyle(el).transform) : [];
      card.animations.forEach(animation => animation.cancel());
      card.animations = [];
      card.running = false;
      card.electrons.forEach((el, index) => {
        el.style.transform = freeze && poses[index] && poses[index] !== 'none'
          ? poses[index] : 'rotate(45deg)';
      });
      card.element.dataset.motionPlaying = 'false';
      if (card.status) card.status.textContent = status;
    }

    function cancelAll(message, freeze = true) {
      batchGeneration += 1;
      cards.forEach(card => cancelCard(card, freeze));
      updateButtons();
      if (message) announce(message);
    }

    function startCard(card, startTime) {
      cancelCard(card, false);
      const generation = card.generation;
      card.running = true;
      card.element.dataset.motionPlaying = 'true';
      if (card.status) card.status.textContent = '재생 중 · 2.4초';
      try {
        // Fixed selected motion 02: one clockwise turn, with no autoplay or loop.
        card.electrons.forEach(el => {
          const animation = el.animate(
            [{ transform: 'rotate(45deg)' }, { transform: 'rotate(405deg)' }],
            { duration: 2400, easing: 'ease-in-out', iterations: 1, fill: 'none' }
          );
          // Observe cancellation immediately, including a partial setup failure.
          animation.finished.catch(() => {});
          card.animations.push(animation);
          if (startTime !== null) animation.startTime = startTime;
        });
      } catch (_) {
        cancelCard(card, false, '재생할 수 없음');
        updateButtons();
        return Promise.resolve(false);
      }
      return Promise.all(card.animations.map(animation => animation.finished)).then(() => {
        if (generation !== card.generation) return false;
        card.animations.forEach(animation => animation.cancel());
        card.animations = [];
        card.running = false;
        card.element.dataset.motionPlaying = 'false';
        if (card.status) card.status.textContent = '한 바퀴 완료';
        updateButtons();
        return true;
      }).catch(() => false);
    }

    function play(cardsToPlay) {
      if (!supported || preference.matches || document.hidden || !cardsToPlay.length) return;
      // No overlapping runs or restart jumps on an already-playing control.
      if (cardsToPlay.every(card => card.running)) return;
      const batch = ++batchGeneration;
      const startTime = document.timeline.currentTime;
      const results = cardsToPlay.map(card => startCard(card, startTime));
      updateButtons();
      announce(cardsToPlay.length === 1
        ? `${cardsToPlay[0].label}: 선택한 02 모션을 한 번 재생합니다.`
        : '모든 H 글꼴에서 선택한 02 모션을 함께 한 번 재생합니다.');
      Promise.all(results).then(completed => {
        if (batch !== batchGeneration) return;
        if (completed.every(Boolean)) {
          announce('2.4초 한 바퀴 재생이 끝났습니다. 자동으로 반복하지 않습니다.');
        } else if (!playable.some(card => card.running)) {
          announce('재생이 끝나거나 중단됐습니다. 각 카드의 상태를 확인해 주세요.');
        }
      });
    }

    function syncPreference() {
      if (preference.matches) {
        cancelAll('동작 줄이기 설정에 따라 정지된 심볼을 표시합니다. 모션은 재생하지 않습니다.', false);
      } else if (!supported) {
        cancelAll('이 브라우저에서는 정지된 심볼을 표시합니다. 모션 재생을 지원하지 않습니다.', false);
      } else {
        updateButtons();
        announce('선택한 02 모션 · 2.4초 · 부드럽게 한 바퀴. 재생을 누르기 전에는 정지합니다.');
      }
    }

    buttons.forEach(button => button.addEventListener('click', () => {
      const card = findCard(button.dataset.playH);
      if (card && card.electrons.length) play([card]);
    }));
    playAll?.addEventListener('click', () => play(playable));
    stopAll?.addEventListener('click', () => {
      cancelAll('모든 움직임을 그 위치에서 정지했습니다. 다시 재생하면 출발점부터 시작합니다.');
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) cancelAll('페이지가 가려져 정지했습니다. 돌아와도 자동으로 다시 재생하지 않습니다.');
    });
    window.addEventListener('pagehide', () => cancelAll(null, false));
    preference.addEventListener('change', syncPreference);
    cards.forEach(card => cancelCard(card, false));
    syncPreference();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMotion, { once: true });
  } else {
    initMotion();
  }
})();
