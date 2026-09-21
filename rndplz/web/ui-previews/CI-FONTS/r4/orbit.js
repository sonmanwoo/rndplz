(() => {
  'use strict';

  const definitions = {
    original: { duration: 2000, easing: 'linear', label: '원본' },
    recommended: { duration: 2400, easing: 'ease-in-out', label: '추천안' }
  };
  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const announcement = document.getElementById('om-announcement');
  const notice = document.getElementById('om-motion-notice');
  const playBoth = document.getElementById('om-play-both');
  const playButtons = [...document.querySelectorAll('[data-play]')];
  const panels = new Map(Object.entries(definitions).map(([id, definition]) => {
    const element = document.querySelector(`[data-orbit-panel="${id}"]`);
    return [id, { ...definition, element, electrons: [...element.querySelectorAll('.om-electron')], status: document.getElementById(`${id}-status`), animations: [], generation: 0 }];
  }));
  const supported = typeof Element.prototype.animate === 'function';
  const say = text => { announcement.textContent = text; };

  function stopPanel(panel, { freeze = true, label = '정지' } = {}) {
    panel.generation += 1;
    // Read the live pose before cancel; a stop never completes the remaining orbit.
    const poses = freeze ? panel.electrons.map(el => getComputedStyle(el).transform) : [];
    panel.animations.forEach(animation => animation.cancel());
    panel.animations = [];
    panel.electrons.forEach((el, i) => { el.style.transform = freeze && poses[i] !== 'none' ? poses[i] : 'rotate(45deg)'; });
    panel.element.dataset.playing = 'false';
    panel.status.textContent = label;
  }

  function stopAll(message, freeze = true) {
    panels.forEach(panel => stopPanel(panel, { freeze }));
    if (message) say(message);
  }

  function play(ids) {
    if (motionPreference.matches || !supported || document.hidden) return;
    const startTime = document.timeline.currentTime;
    ids.forEach(id => {
      const panel = panels.get(id);
      if (!panel) return;
      stopPanel(panel, { freeze: false });
      const generation = panel.generation;
      panel.status.textContent = '재생 중';
      panel.element.dataset.playing = 'true';
      panel.animations = panel.electrons.map(el => {
        const animation = el.animate(
          [{ transform: 'rotate(45deg)' }, { transform: 'rotate(405deg)' }],
          { duration: panel.duration, easing: panel.easing, iterations: 1, fill: 'none' }
        );
        if (startTime !== null) animation.startTime = startTime;
        return animation;
      });
      Promise.all(panel.animations.map(animation => animation.finished)).then(() => {
        if (panel.generation !== generation) return;
        panel.animations.forEach(animation => animation.cancel());
        panel.animations = [];
        panel.element.dataset.playing = 'false';
        panel.status.textContent = '한 바퀴 완료';
        say(`${panel.label} ${panel.duration / 1000}초 한 바퀴가 끝났습니다. 반복하지 않습니다.`);
      }).catch(() => {
        // Explicit stop, a new play, hidden page or reduced motion cancels this run.
      });
    });
    say(ids.length === 2 ? '원본과 추천안을 함께 한 번 재생합니다.' : `${panels.get(ids[0]).label}을 한 번 재생합니다.`);
  }

  function syncPreference() {
    const reduced = motionPreference.matches;
    playBoth.disabled = reduced || !supported;
    playButtons.forEach(button => { button.disabled = reduced || !supported; });
    notice.hidden = !reduced && supported;
    if (reduced) {
      stopAll('동작 줄이기 설정에 따라 정지된 심볼을 표시합니다.', false);
      notice.textContent = '기기의 ‘동작 줄이기’ 설정에 따라 정지된 심볼로 비교합니다. 재생하지 않습니다.';
    } else if (!supported) {
      stopAll('이 브라우저에서는 정지된 심볼을 표시합니다.', false);
      notice.textContent = '이 브라우저에서는 모션 재생을 지원하지 않아 정지된 심볼을 표시합니다.';
    } else {
      say('재생 버튼을 누르면 실제 크기와 확대 심볼이 함께 한 바퀴 움직입니다.');
    }
  }

  playBoth.addEventListener('click', () => play([...panels.keys()]));
  playButtons.forEach(button => button.addEventListener('click', () => play([button.dataset.play])));
  document.querySelectorAll('[data-stop]').forEach(button => button.addEventListener('click', () => {
    const panel = panels.get(button.dataset.stop);
    stopPanel(panel);
    say(`${panel.label}을 정지했습니다. 다시 재생하면 출발점부터 시작합니다.`);
  }));
  document.getElementById('om-stop-all').addEventListener('click', () => stopAll('모든 움직임을 정지했습니다. 다시 재생하면 출발점부터 시작합니다.'));
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopAll('페이지가 가려져 움직임을 정지했습니다. 자동으로 다시 재생하지 않습니다.');
  });
  window.addEventListener('pagehide', () => stopAll(null, false));
  motionPreference.addEventListener('change', syncPreference);
  syncPreference();
})();
