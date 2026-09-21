(() => {
  'use strict';
  const names={h0:'H0 · 현재 기준',h1:'H1 · 같은 목소리',h2:'H2 · 유려한 서체',h3:'H3 · 곧은 고전',h4:'H4 · 선명한 대비',h5:'H5 · 간결한 구조'};
  const hero=document.getElementById('heroPreview');
  document.querySelectorAll('[data-preview-h]').forEach(button=>button.addEventListener('click',()=>{
    const key=button.dataset.previewH;
    if(!Object.hasOwn(names,key))return;
    document.getElementById('stopAll').click();
    Object.keys(names).forEach(name=>hero.classList.toggle(name,name===key));
    document.getElementById('previewName').textContent=names[key];
    document.getElementById('previewChoice').textContent=names[key]+'를 크게 보고 있습니다. H 선택은 저장되지 않습니다.';
    document.querySelectorAll('[data-preview-h]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    hero.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'center'});
    hero.focus({preventScroll:true});
  }));
})();
