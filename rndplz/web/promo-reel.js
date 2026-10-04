// 헤더의 15초 소개 영상 아이콘 — 누르면 페이지 위 창에서 바로 재생한다.
(() => {
  let dialog = null;
  function build() {
    dialog = document.createElement('dialog');
    dialog.id = 'promoReelDialog';
    dialog.setAttribute('aria-label', '수소문 15초 소개 영상');
    dialog.innerHTML = '<div class="promo-reel-box"><div class="promo-reel-head"><strong>수소문 15초 소개 영상</strong>'
      + '<button type="button" class="icon-button" data-reel-close aria-label="영상 닫기">×</button></div>'
      + '<video controls playsinline preload="metadata" poster="/video/susomun-reel-poster.webp" src="/video/susomun-reel-15s.mp4"></video></div>';
    document.body.appendChild(dialog);
    const video = dialog.querySelector('video');
    dialog.querySelector('[data-reel-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => video.pause());
  }
  document.addEventListener('click', event => {
    if (!event.target.closest('[data-promo-reel]')) return;
    if (!dialog) build();
    const video = dialog.querySelector('video');
    dialog.showModal();
    video.currentTime = 0;
    video.play().catch(() => {});
  });
})();
