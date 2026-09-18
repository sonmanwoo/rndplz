'use strict';
(() => {
  const layouts={fan:'A · 이름·역할 우선',evidence:'B · 이유·근거 우선'};
  const devices={desktop:'데스크톱',mobile:'모바일'};
  let layout='evidence';
  let device=matchMedia('(max-width:600px)').matches?'mobile':'desktop';
  const picture=document.getElementById('preview-image');
  const link=document.getElementById('image-link');
  function render(){
    const src=`images/${layout}-${device}.png`;
    picture.src=src;
    picture.alt=`${layouts[layout]} / ${devices[device]} 후보 카드 비교 캡처`;
    picture.width=device==='desktop'?1440:390;
    picture.height=device==='desktop'?1050:844;
    link.href=src;
    link.className=`screenshot ${device}`;
    document.getElementById('preview-label').textContent=`${layouts[layout]} / ${devices[device]}`;
    document.querySelectorAll('[data-layout]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.layout===layout)));
    document.querySelectorAll('[data-device]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.device===device)));
  }
  document.querySelectorAll('[data-layout]').forEach(button=>button.addEventListener('click',()=>{layout=button.dataset.layout;render();}));
  document.querySelectorAll('[data-device]').forEach(button=>button.addEventListener('click',()=>{device=button.dataset.device;render();}));
  render();
})();
