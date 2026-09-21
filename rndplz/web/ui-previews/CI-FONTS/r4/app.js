(() => {
  'use strict';
  const names={"h5": "H5 · 원래 형태 0°", "h5a": "H5-A · 은은하게 8°", "h5b": "H5-B · 균형 있게 12°", "h5c": "H5-C · 또렷하게 16°"};
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
