'use strict';
(() => {
  const data = window.LAUREATE_R3;
  const grid = document.getElementById('researcherCards');
  if (!data || !Array.isArray(data.people) || !data.people.length) {
    grid.textContent = '비교 자료를 불러오지 못했습니다. 페이지를 새로 열어 주세요.';
    document.getElementById('assetStatus').textContent = '자료 파일 확인이 필요합니다.';
    return;
  }
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const safeUrl = value => /^https:\/\//.test(String(value || '')) ? value : '#';
  const link = (url, label, extra = '') => '<a href="' + esc(safeUrl(url)) + '" target="_blank" rel="noopener noreferrer" ' + extra + '>' + esc(label) + ' ↗</a>';
  const assetReady = new Map();
  function sources(person) {
    const art = person.portrait, ref = art.reference;
    const photoLicense = ref.license ? '<p>' + link(ref.licenseUrl, ref.license) + '</p>' : '';
    const photoAuthor = ref.author ? '<p>촬영자: ' + link(ref.authorUrl, ref.author) + '</p>' : '';
    const generatedLicense = art.generatedLicense
      ? '<p>변환 일러스트 이용 조건: ' + link(art.generatedLicenseUrl, art.generatedLicense) + '</p>' : '';
    return '<details class="details-box image-sources" id="sources-' + esc(person.slug) + '"><summary>이미지 제작과 출처</summary><div class="details-body">' +
      '<h3>화면의 AI 생성 일러스트</h3><p class="generated-credit">' + esc(art.generatedCredit) + '</p>' +
      '<p class="generated-change-note">' + esc(art.changeNote) + '</p>' + generatedLicense +
      '<h3>외형을 참고한 사진</h3><p>' + link(ref.sourcePage, ref.title, 'class="reference-source"') + '</p>' +
      photoAuthor + photoLicense + (ref.credit ? '<p class="reference-credit">' + esc(ref.credit) + '</p>' : '') +
      '<p>' + esc(ref.usage) + '</p><p>인물이나 촬영자의 서비스 참여·추천을 뜻하지 않습니다.</p></div></details>';
  }
  function renderCard(person, index) {
    const art = person.portrait;
    return '<article id="card-' + esc(person.slug) + '" class="researcher-card holo-card" data-person-id="' + esc(person.id) +
      '" data-asset="pending" tabindex="0" aria-labelledby="name-' + esc(person.slug) + '" aria-describedby="cardKeyboardHelp">' +
      '<div class="researcher-edition"><span>H:문 / RESEARCH ARCHIVE</span><span>0' + (index + 1) + ' / ' + String(data.people.length).padStart(2, '0') + '</span></div>' +
      '<header class="researcher-name-block"><h2 id="name-' + esc(person.slug) + '">' + esc(person.nameKo) +
      '</h2><p class="researcher-english" lang="en">' + esc(person.name) + '</p><p class="researcher-field">' + esc(person.field) + '</p></header>' +
      '<div class="portrait-art is-illustration"><div class="portrait-placeholder"><span class="placeholder-mark" aria-hidden="true">h</span>' +
      '<strong>' + esc(art.missingNote) + '</strong><small>같은 3:4 초상 창을 유지합니다.</small></div>' +
      '<img class="portrait-person" hidden alt="' + esc(person.nameKo) + '의 AI 생성 초상 일러스트" width="1086" height="1448" decoding="async">' +
      '<span class="foil-sheen" aria-hidden="true"></span><span class="foil-glare" aria-hidden="true"></span>' +
      '<span class="portrait-label">AI ILLUSTRATION · 준비 중</span></div>' +
      '<div class="researcher-card-copy"><p class="art-note">' + esc(art.missingNote) + '</p>' +
      '<p class="award-line"><span class="award-mark" aria-hidden="true">✧</span>' + esc(person.awardLabel) + '</p>' +
      '<p class="award-reason">' + esc(person.motivationKo) + '</p>' +
      '<p class="researcher-tagline">' + esc(person.summary) + '</p>' +
      '<div class="researcher-skills">' + person.tags.map(tag => '<span>' + esc(tag) + '</span>').join('') + '</div>' +
      '<p class="paper-summary"><strong>선별 연구 · ' + esc(person.paper.year) + '</strong><br>' + esc(person.paper.summary) + '</p>' +
      '<details class="details-box fact-sources" id="facts-' + esc(person.slug) + '"><summary>수상·연구 근거</summary><div class="details-body">' +
      '<h3>수상 기록</h3><p>' + link(person.nobelUrl, person.awardLabel + ' · 공식 기록') + '</p><p lang="en">' + esc(person.categoryOfficial) + '</p>' +
      '<h3>선별 논문 · ' + esc(person.paper.year) + '</h3><p class="paper-title" lang="en">' + link(person.paper.url, person.paper.title) + '</p>' +
      '<p>공동 저자: ' + esc(person.paper.authors.join(' · ')) + '</p><p>' + esc(person.paper.contribution) + '</p>' +
      '<h3>공식 프로필</h3><p>' + link(person.profileUrl, person.affiliation) + '</p><p>자료 확인: ' + esc(person.checkedAt) + '</p></div></details>' +
      sources(person) + '<p class="boundary">' + esc(person.limit) + '</p></div></article>';
  }
  grid.innerHTML = data.people.map(renderCard).join('');
  function updateAssetStatus() {
    const ready = data.people.filter(person => assetReady.get(person.slug)).length;
    document.getElementById('assetStatus').textContent = ready === data.people.length
      ? data.people.length + '명의 초상이 준비되었습니다. 제작 방식과 출처를 카드 아래에서 확인할 수 있습니다.'
      : '초상 ' + ready + ' / ' + data.people.length + '장 준비됨 · 준비 중인 이미지는 원사진으로 대체하지 않습니다.';
  }
  data.people.forEach(person => {
    const card = document.getElementById('card-' + person.slug);
    const img = card.querySelector('.portrait-person');
    const update = ready => {
      assetReady.set(person.slug, ready);
      card.dataset.asset = ready ? 'ready' : 'pending';
      img.hidden = !ready;
      card.querySelector('.portrait-placeholder').hidden = ready;
      card.querySelector('.portrait-label').textContent = ready ? person.portrait.label : 'AI ILLUSTRATION · 준비 중';
      card.querySelector('.art-note').textContent = ready ? person.portrait.note : person.portrait.missingNote;
      updateAssetStatus();
    };
    img.addEventListener('load', () => update(img.naturalWidth > 0), {once:true});
    img.addEventListener('error', () => update(false), {once:true});
    // Only packaged PNGs are requested; reference photos never become a fallback src.
    img.src = person.portrait.path;
  });

  const effectToggle = document.getElementById('effectToggle');
  const motionToggle = document.getElementById('motionToggle');
  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const cards = Array.from(grid.querySelectorAll('.researcher-card'));
  let effectEnabled = false, effectStyle = 'gold', manualMotionOff = false;
  const motionReduced = () => motionPreference.matches || manualMotionOff;
  function resetCard(card) {
    ['--rx','--ry','--light-x','--light-y'].forEach(property => card.style.removeProperty(property));
    delete card.dataset.lightX;
    delete card.dataset.lightY;
  }
  function updateControls(announce = true) {
    document.body.dataset.effect = effectEnabled ? effectStyle : 'off';
    document.body.dataset.motion = motionReduced() ? 'reduced' : 'full';
    effectToggle.setAttribute('aria-pressed', String(effectEnabled));
    effectToggle.textContent = effectEnabled ? '특별 효과 끄기' : '특별 효과 켜기';
    motionToggle.setAttribute('aria-pressed', String(motionReduced()));
    motionToggle.disabled = motionPreference.matches;
    motionToggle.textContent = motionPreference.matches ? 'OS 설정 · 움직임 꺼짐' : manualMotionOff ? '움직임 켜기' : '움직임 끄기';
    document.getElementById('motionStatus').textContent = motionReduced()
      ? '움직임을 줄였습니다. 효과를 켜면 고정된 빛만 표시됩니다.'
      : '카드 위에서 포인터를 움직이거나, 카드에 초점을 두고 방향키를 눌러 빛을 살펴보세요.';
    if (announce) document.getElementById('effectStatus').textContent = effectEnabled ? (effectStyle === 'gold' ? '금빛' : '분광') + ' 효과 켜짐' : '특별 효과 꺼짐';
    cards.forEach(resetCard);
  }
  effectToggle.addEventListener('click', () => { effectEnabled = !effectEnabled; updateControls(); });
  document.querySelectorAll('input[name="effectStyle"]').forEach(input => input.addEventListener('change', () => {
    effectStyle = input.value;
    updateControls();
  }));
  motionToggle.addEventListener('click', () => { manualMotionOff = !manualMotionOff; updateControls(); });
  motionPreference.addEventListener('change', () => updateControls(false));
  function setLight(card, x, y) {
    if (!effectEnabled || motionReduced() || card.dataset.asset !== 'ready') return;
    x = Math.max(0, Math.min(1, x)); y = Math.max(0, Math.min(1, y));
    card.dataset.lightX = String(x); card.dataset.lightY = String(y);
    card.style.setProperty('--rx', ((.5-y)*7).toFixed(2) + 'deg');
    card.style.setProperty('--ry', ((x-.5)*9).toFixed(2) + 'deg');
    card.style.setProperty('--light-x', (x*100) + '%');
    card.style.setProperty('--light-y', (y*100) + '%');
  }
  cards.forEach(card => {
    card.addEventListener('pointermove', event => {
      if (event.pointerType === 'touch') return;
      const box = card.querySelector('.portrait-art').getBoundingClientRect();
      setLight(card, (event.clientX-box.left)/box.width, (event.clientY-box.top)/box.height);
    }, {passive:true});
    card.addEventListener('pointerleave', () => resetCard(card));
    card.addEventListener('focusout', event => { if (!card.contains(event.relatedTarget)) resetCard(card); });
    card.addEventListener('keydown', event => {
      if (event.target !== card) return;
      if (event.key === 'Escape') { resetCard(card); return; }
      const delta = {ArrowLeft:[-.12,0],ArrowRight:[.12,0],ArrowUp:[0,-.12],ArrowDown:[0,.12]}[event.key];
      if (!delta || !effectEnabled || motionReduced() || card.dataset.asset !== 'ready') return;
      event.preventDefault();
      setLight(card, Number(card.dataset.lightX ?? .5)+delta[0], Number(card.dataset.lightY ?? .35)+delta[1]);
    });
  });
  updateControls(false);
})();

