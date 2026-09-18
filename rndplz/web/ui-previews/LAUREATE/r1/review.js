/* Independent static preview. No API, storage, sensor or network calls. */
(() => {
  'use strict';
  const people = window.LAUREATES || [];
  const container = document.querySelector('#researchers');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const pointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const slider = document.querySelector('#lightPosition');
  const sweep = document.querySelector('#sweep');
  const status = document.querySelector('#effectStatus');
  let animation = 0;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  const link = (url, label) => /^https:\/\//.test(url || '') ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : esc(label);
  container.innerHTML = people.map((p, i) => `<article class="researcher" data-person="${esc(p.id)}" aria-labelledby="person-${i}"><div class="card-inner">
    <header class="identity"><div class="identity-top"><span class="field">${esc(p.field)}</span><span class="index">${String(i + 1).padStart(2,'0')} / 06</span></div><h2 id="person-${i}">${esc(p.nameKo)}</h2><p class="english-name">${esc(p.name)}</p></header>
    <div class="portrait-scene"><div class="portrait" style="--crop:${esc(p.crop || '50% 36%')}">${p.photoLocal ? `<img src="${esc(p.photoLocal)}" alt="${esc(p.nameKo)}의 실제 사진" width="600" height="600" loading="${i < 3 ? 'eager' : 'lazy'}">` : `<div class="portrait-fallback"><strong>${esc(p.initials)}</strong><span>사진 대신 이니셜로 표시</span></div>`}<div class="foil" aria-hidden="true"></div><div class="glints" aria-hidden="true"></div></div></div>
    <div class="prize"><span class="prize-seal" aria-hidden="true">${esc(p.nobelYear)}</span><div><p class="prize-label">NOBEL LAUREATE</p><p class="prize-title">${esc(p.nobelYear)} 노벨 ${esc(p.categoryKo)}</p></div></div>
    <div class="card-copy"><p class="summary">${esc(p.summary)}</p><ul class="tags">${p.tags.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>
    <details class="history"><summary>수상 이력과 출처</summary><div class="history-content"><h3>${esc(p.nobelYear)} · ${esc(p.categoryOfficial)}</h3><p class="motivation">${esc(p.motivationKo)}</p><p>공식 수상 사유를 한국어로 요약했습니다.</p><p class="source-link">${link(p.nobelUrl,'노벨상 공식 수상 기록 ↗')}</p><h3>대표 연구 기록 · ${esc(p.paper.year)}</h3><p>${link(p.paper.url,p.paper.title)}</p><p>${esc(p.paper.summary)}</p><p class="credit">공동 저자: ${esc(p.paper.authors.join(", "))}</p><p class="credit">${esc(p.paper.contribution)}</p><p>${link(p.profileUrl,"공식 연구자 프로필 ↗")}</p><p class="credit">${esc(p.affiliation)} · ${esc(p.affiliationAsOf)} 확인</p><p class="limit">${esc(p.limit)}</p><h3>사진 출처</h3><p class="credit">${p.photoLocal ? esc(p.photo.credit) : '재사용 사진이 준비되지 않아 이니셜을 표시합니다.'}</p><p class="credit">${link(p.photo.sourcePage,'사진 원본·사용 조건 ↗')} · ${link(p.photo.licenseUrl,p.photo.license || '사용 조건')}</p><p class="credit">${esc(p.photo.changeNote || '')}</p><p class="credit">확인일 ${esc(p.checkedAt)}</p></div></details></div>
  </div></article>`).join('');
  container.querySelectorAll('img').forEach(img => img.addEventListener('error', () => {
    const fallback=document.createElement('div'); fallback.className='portrait-fallback';
    fallback.textContent='사진을 불러오지 못했습니다. 아래 출처에서 원본을 확인해 주세요.';img.replaceWith(fallback);
  },{once:true}));
  const cards=[...container.querySelectorAll('.researcher')];
  function reset(card){['--px','--py','--lean-x','--lean-y'].forEach(p=>card.style.removeProperty(p));}
  function stop(){cancelAnimationFrame(animation);animation=0;sweep.textContent=reduced.matches?'동작 줄이기 적용 중':'빛 움직여 보기 ↗';}
  function position(value){slider.value=String(value);slider.setAttribute('aria-valuetext',`${Math.round(value)}%`);document.documentElement.style.setProperty('--light',`${value}%`);cards.forEach(reset);}
  function sync(){stop();cards.forEach(reset);const finish=document.body.dataset.finish;const disabled=finish==='plain';slider.disabled=disabled;sweep.disabled=disabled||reduced.matches;const names={gold:'금빛 포일',prism:'분광 포일',plain:'효과 끄기'};status.textContent=disabled?'효과를 껐습니다. 사진과 수상 이력은 그대로입니다.':`${names[finish]} · ${reduced.matches?'동작 줄이기 적용 중. 빛의 각도로 정적인 질감을 확인할 수 있습니다.':'카드 위에서 포인터를 움직이거나 빛의 각도를 조절해 보세요.'}`;}
  document.querySelectorAll('[name="finish"]').forEach(input=>input.addEventListener('change',()=>{document.body.dataset.finish=input.value;sync();}));
  slider.addEventListener('input',()=>{stop();position(Number(slider.value));});
  sweep.addEventListener('click',()=>{if(reduced.matches||document.body.dataset.finish==='plain')return;stop();const initial=Number(slider.value),start=performance.now();sweep.textContent='빛을 살펴보는 중…';function frame(now){const progress=Math.min(1,(now-start)/1800);position(initial+Math.sin(progress*Math.PI*2)*Math.min(initial,100-initial,32));if(progress<1){animation=requestAnimationFrame(frame);}else{position(initial);stop();}}animation=requestAnimationFrame(frame);});
  cards.forEach(card=>{card.addEventListener('pointermove',event=>{if(!pointer.matches||reduced.matches||document.body.dataset.finish==='plain'||event.pointerType==='touch')return;stop();const box=card.querySelector('.portrait').getBoundingClientRect();const x=Math.max(0,Math.min(1,(event.clientX-box.left)/box.width));const y=Math.max(0,Math.min(1,(event.clientY-box.top)/box.height));card.style.setProperty('--px',`${x*100}%`);card.style.setProperty('--py',`${y*100}%`);card.style.setProperty('--lean-x',`${(0.5-y)*5}deg`);card.style.setProperty('--lean-y',`${(x-0.5)*5}deg`);});card.addEventListener('pointerleave',()=>reset(card));});
  reduced.addEventListener('change',sync);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){stop();cards.forEach(reset);}});
  window.addEventListener('blur',()=>{stop();cards.forEach(reset);});
  sync();
})();
