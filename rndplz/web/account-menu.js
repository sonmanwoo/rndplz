(() => {
  'use strict';
  const toggle=document.getElementById('accountToggle'),menu=document.getElementById('accountMenu');
  if(!toggle||!menu)return;
  const logout=document.getElementById('logoutButton'),note=document.getElementById('accountSessionNote'),error=document.getElementById('accountError');
  let token='',supported=false,ending=false;
  const close=(focus=false)=>{menu.hidden=true;toggle.setAttribute('aria-expanded','false');if(focus)toggle.focus();};
  toggle.addEventListener('click',()=>{menu.hidden=!menu.hidden;toggle.setAttribute('aria-expanded',String(!menu.hidden));if(!menu.hidden)menu.querySelector('button:not(:disabled),a')?.focus();});
  document.addEventListener('click',event=>{if(!event.target.closest('.account-control'))close();else if(event.target.closest('#accountMenu a,#accountMenu button:not(#logoutButton)'))close();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!menu.hidden){event.preventDefault();close(true);}});
  logout.addEventListener('click',async()=>{
    if(!supported||ending)return;
    ending=true;logout.disabled=true;error.textContent='';
    try{
      const response=await fetch('/api/logout',{method:'POST',headers:{'Content-Type':'application/json','X-RnDplz-Token':token},body:'{}'});
      const value=await response.json();if(!response.ok)throw new Error(value.error||'방문자 세션을 끝내지 못했어요.');
      try{localStorage.setItem('rndplz:visitor-ended',String(Date.now()));}catch{}
      location.replace('/');
    }catch(exc){error.textContent=exc.message;ending=false;logout.disabled=false;}
  });
  window.addEventListener('storage',event=>{if(event.key==='rndplz:visitor-ended'&&supported)location.replace('/');});
  fetch('/api/chat/bootstrap').then(async response=>{if(!response.ok)throw new Error();return response.json();}).then(value=>{
    token=value.token;supported=value.logout_supported===true;logout.disabled=!supported;
    note.textContent=supported?'임시 방문자 세션입니다. 로그아웃하면 이 화면에서 저장 기록에 다시 접근할 수 없어요.':'로컬 단일 사용자 모드 · 별도 로그인 세션이 없습니다.';
  }).catch(()=>{note.textContent='세션 상태를 불러오지 못했어요.';});
})();
