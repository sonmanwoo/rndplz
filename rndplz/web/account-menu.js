(() => {
  'use strict';
  const toggle=document.getElementById('accountToggle'),menu=document.getElementById('accountMenu');
  const plainIcon=toggle?.innerHTML||'';
  // A signed-in account bound to a map card shows that card's portrait instead of the outline icon.
  function accountIcon(account){
   const path=typeof account?.portrait==='string'&&/^\/portraits\/[a-z0-9-]+-thumb\.webp$/i.test(account.portrait)?account.portrait:'';
   if(!toggle||toggle.dataset.photo===path)return;toggle.dataset.photo=path;toggle.classList.toggle('has-photo',Boolean(path));
   if(!path){toggle.innerHTML=plainIcon;return;}
   const img=document.createElement('img');img.src=path;img.alt='';img.decoding='async';
   img.addEventListener('error',()=>{toggle.classList.remove('has-photo');toggle.innerHTML=plainIcon;},{once:true});
   toggle.replaceChildren(img);
  }
  if(!toggle||!menu)return;
  const logout=document.getElementById('logoutButton'),note=document.getElementById('accountSessionNote'),error=document.getElementById('accountError');
  const identity=document.getElementById('accountIdentity'),login=document.getElementById('googleLogin'),unavailable=document.getElementById('accountLoginUnavailable'),verifySession=document.getElementById('accountVerifySession');
  let token='',supported=false,ending=false,invalidated=false,principal=null,accountAPI=null,checking=false,requestEpoch=0;
  const inertBefore=new Map();
  let announceLogin=false;
  let logoutUncertain=false,sessionExpired=false;
  let pendingNotice=false;
  try{
    const url=new URL(location.href);announceLogin=url.searchParams.get('account_changed')==='1';pendingNotice=url.searchParams.get('account_pending')==='1';
    if(url.searchParams.has('account_changed')||url.searchParams.has('account_pending')){url.searchParams.delete('account_changed');url.searchParams.delete('account_pending');window.history.replaceState(window.history.state,'',url.pathname+url.search+url.hash);}
  }catch{}
  const show=(node,visible)=>{if(node){node.hidden=!visible;node.style.display=visible?'':'none';}};
  const close=(focus=false)=>{menu.hidden=true;toggle.setAttribute('aria-expanded','false');if(focus)toggle.focus();};
  const fire=(type,detail)=>window.dispatchEvent(new CustomEvent(type,{detail}));
  // Read-only account credit view. Never derive a balance from the recent rows.
  let moleAccount=null,moleEpoch=0,moleController=null,moleBusy=false,moleLoadAfterSession=false;
  const moleNode=(tag,id,className,text)=>{
    const node=document.createElement(tag);if(id)node.id=id;if(className)node.className=className;
    if(text)node.textContent=text;return node;
  };
  const moleEntry=moleNode('button','moleEntry','mole-entry');moleEntry.type='button';
  moleEntry.setAttribute('aria-haspopup','dialog');moleEntry.setAttribute('aria-controls','moleDialog');
  const moleEntryValue=moleNode('span','moleEntryValue','','확인 중');
  moleEntry.append(moleNode('span','','','mole'),moleEntryValue);
  const moleUnavailable=moleNode('p','moleUnavailable','account-note','계정 확인 중');
  show(moleEntry,false);menu.insertBefore(moleEntry,identity?.nextSibling||menu.firstChild);moleEntry.after(moleUnavailable);
  const moleDialog=moleNode('dialog','moleDialog','mole-dialog');
  moleDialog.setAttribute('aria-labelledby','moleTitle');moleDialog.setAttribute('aria-describedby','moleMeaning');
  const moleHeading=moleNode('header','','mole-heading'),moleTitle=moleNode('h2','moleTitle','','내 mole');
  const moleClose=moleNode('button','moleClose','mole-close','×');moleClose.type='button';moleClose.autofocus=true;moleClose.setAttribute('aria-label','mole 내역 닫기');
  moleHeading.append(moleTitle,moleClose);
  const moleBalance=moleNode('p','moleBalance','mole-balance','확인 중');moleBalance.setAttribute('aria-live','polite');
  const moleMeaning=moleNode('p','moleMeaning','mole-note','참여 포인트 · 현금 가치 없음');
  const molePolicy=moleNode('p','','mole-note mole-policy','경험 내용과 내 역할을 처음 등록하면 1 mole · 계정당 1회');
  const moleHistory=moleNode('div','','mole-history-heading'),moleRefresh=moleNode('button','moleRefresh','mole-refresh','다시 확인');moleRefresh.type='button';
  moleHistory.append(moleNode('h3','','','적립 내역'),moleRefresh);
  const moleStatus=moleNode('p','moleStatus','mole-status');moleStatus.setAttribute('role','status');
  const moleExtent=moleNode('p','moleExtent','mole-note'),moleEntries=moleNode('ol','moleEntries','mole-entries');
  moleDialog.append(moleHeading,moleBalance,moleMeaning,molePolicy,moleHistory,moleStatus,moleExtent,moleEntries);document.body.append(moleDialog);
  function clearMole(label){
    moleEpoch++;moleController?.abort();moleController=null;moleBusy=false;
    moleEntryValue.textContent=label;moleBalance.textContent=label;moleEntries.replaceChildren();moleExtent.textContent='';moleStatus.textContent='';
    moleRefresh.removeAttribute('aria-busy');moleRefresh.removeAttribute('aria-disabled');
  }
  function closeMole(){if(moleDialog.open)moleDialog.close();}
  function setMoleAccount(id,message=''){
    const focusedEntry=document.activeElement===moleEntry;
    if(id!==moleAccount){clearMole(id?'확인 전':'확인할 수 없음');moleAccount=id;closeMole();}
    show(moleEntry,!!id);show(moleUnavailable,!id);moleUnavailable.textContent=id?'':message;
    if(!id&&focusedEntry&&!ending&&!invalidated)toggle.focus({preventScroll:true});
  }
  function validMole(value,id){
    const utc=value=>typeof value==='string'&&value.endsWith('Z')&&Number.isFinite(Date.parse(value));
    if(!value||value.account_id!==id||value.unit!=='mole'||!Number.isSafeInteger(value.balance)||value.balance<0||!utc(value.as_of)||value.limit!==20||typeof value.has_more!=='boolean'||!Array.isArray(value.entries)||value.entries.length>20)return false;
    if(value.policy?.first_experience_amount!==1||value.policy?.once_per_account!==true||value.policy?.non_cash!==true)return false;
    const ids=new Set();return value.entries.every(row=>{
      if(!row||typeof row.id!=='string'||!row.id||ids.has(row.id)||!['grant','reversal'].includes(row.kind)||row.delta!==(row.kind==='grant'?1:-1)||typeof row.activity!=='string'||!row.activity.trim()||!utc(row.occurred_at))return false;
      ids.add(row.id);return true;
    });
  }
  async function loadMole(){
    if(!moleAccount||ending||invalidated||moleBusy)return;
    clearMole('확인 중');moleBusy=true;moleRefresh.setAttribute('aria-busy','true');moleRefresh.setAttribute('aria-disabled','true');
    moleStatus.textContent='잔액과 내역을 불러오고 있어요.';
    const id=moleAccount,epoch=moleEpoch,controller=new AbortController();moleController=controller;
    const current=()=>epoch===moleEpoch&&id===moleAccount&&principal==='account:'+id&&!ending&&!invalidated;
    try{
      const response=await fetch('/api/account/mole',{credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if(!current())return;
      if(response.status===401){setMoleAccount(null,'로그인 상태를 다시 확인하고 있어요.');await refreshSession();return;}
      if(!response.ok)throw new Error('read');
      const value=await response.json();if(!current())return;
      if(value?.account_id!==id){setMoleAccount(null,'계정 상태를 다시 확인하고 있어요.');await refreshSession();return;}
      if(!validMole(value,id))throw new Error('schema');
      const amount=value.balance.toLocaleString('ko-KR')+' mole';moleEntryValue.textContent=amount;moleBalance.textContent=amount;
      moleStatus.textContent=value.entries.length?'':'아직 적립 내역이 없습니다.';
      moleExtent.textContent=(value.has_more?'최근 '+value.entries.length+'건 · ':'')+new Date(value.as_of).toLocaleString('ko-KR')+' 기준';
      for(const row of value.entries){
        const item=moleNode('li'),label=moleNode('span','','mole-activity',row.activity),time=moleNode('time','','mole-time',new Date(row.occurred_at).toLocaleString('ko-KR'));
        time.dateTime=row.occurred_at;
        const delta=moleNode('span','','mole-delta'+(row.delta<0?' mole-negative':''),(row.delta>0?'+':'−')+Math.abs(row.delta)+' mole');
        item.append(label,time,delta);moleEntries.append(item);
      }
    }catch(exc){if(!current()||exc.name==='AbortError')return;moleEntryValue.textContent='조회 불가';moleBalance.textContent='조회 불가';moleStatus.textContent='잔액과 내역을 확인하지 못했어요. 잠시 후 다시 확인해 주세요.';}
    finally{if(current()){moleBusy=false;moleController=null;moleRefresh.removeAttribute('aria-busy');moleRefresh.removeAttribute('aria-disabled');}}
  }
  moleEntry.addEventListener('click',()=>{if(!moleAccount||ending||invalidated)return;close();moleDialog.showModal();loadMole();});
  moleClose.addEventListener('click',closeMole);
  moleDialog.addEventListener('close',()=>{if(!ending&&!invalidated&&toggle.isConnected)toggle.focus({preventScroll:true});});
  moleRefresh.addEventListener('click',loadMole);
  window.addEventListener('rndplz:account-navigation',event=>{if(['begin','invalidate'].includes(event.detail?.phase)){clearMole('확인 전');closeMole();}});

  // Open sign-up: a Google account outside the team becomes a request that the administrator
  // decides here. Visitors only see how it works; logging in is what sends the request.
  const signupNote=moleNode('p','accountSignupNote','account-note','처음이라면 로그인할 때 가입 요청이 관리자에게 전달되고, 승인 후 이용할 수 있어요.');
  show(signupNote,false);login?.after(signupNote);
  const pendingNote=moleNode('p','accountPendingNote','account-note account-pending','가입 요청을 보냈어요. 관리자가 승인하면 ‘Google 계정으로 로그인’을 다시 눌러 주세요.');
  pendingNote.setAttribute('role','status');show(pendingNote,pendingNotice);menu.insertBefore(pendingNote,menu.firstChild);
  const requestsEntry=moleNode('button','requestsEntry','requests-entry','가입 요청');requestsEntry.type='button';
  requestsEntry.setAttribute('aria-haspopup','dialog');requestsEntry.setAttribute('aria-controls','requestsDialog');
  show(requestsEntry,false);moleUnavailable.after(requestsEntry);
  const requestsDialog=moleNode('dialog','requestsDialog','mole-dialog requests-dialog');requestsDialog.setAttribute('aria-labelledby','requestsTitle');
  const requestsHeading=moleNode('header','','mole-heading'),requestsClose=moleNode('button','requestsClose','mole-close','×');
  requestsClose.type='button';requestsClose.setAttribute('aria-label','가입 요청 닫기');
  requestsHeading.append(moleNode('h2','requestsTitle','','가입 요청'),requestsClose);
  const requestsStatus=moleNode('p','requestsStatus','mole-status');requestsStatus.setAttribute('role','status');
  const requestsList=moleNode('ol','requestsList','mole-entries requests-list');
  requestsDialog.append(requestsHeading,moleNode('p','','mole-note','Google 계정으로 가입을 요청한 사람입니다. 승인하면 다음 로그인부터 이용할 수 있고, 거절한 계정은 다시 요청할 수 없어요.'),requestsStatus,requestsList);
  document.body.append(requestsDialog);
  const requestErrors={person_already_bound:'이미 다른 계정에 연결된 프로필이에요.',request_not_pending:'이미 처리된 요청이에요.',admin_required:'관리자 계정만 처리할 수 있어요.',account_required:'로그인 상태를 다시 확인해 주세요.',decision_invalid:'연결할 프로필을 다시 골라 주세요.'};
  let requestsBusy=false;
  function setRequestsCount(count){requestsEntry.textContent=count>0?'가입 요청 '+count+'건':'가입 요청 없음';requestsEntry.classList.toggle('has-requests',count>0);}
  function renderRequests(value){
    const rows=Array.isArray(value?.requests)?value.requests:[],people=Array.isArray(value?.people)?value.people:[];
    requestsList.replaceChildren();
    for(const row of rows){
      const item=moleNode('li','','request-item'),who=moleNode('div','','request-who');
      const when=Number.isSafeInteger(row.requested_at)?new Date(row.requested_at*1000).toLocaleString('ko-KR'):'';
      who.append(moleNode('strong','','',row.display_name||'이름 없음'),moleNode('span','','mole-time',[row.email||'이메일 미확인',when].filter(Boolean).join(' · ')));
      const select=document.createElement('select');select.setAttribute('aria-label',(row.display_name||'요청자')+' 승인 시 연결할 공개 프로필');
      select.append(new Option('공개 프로필과 연결 안 함',''));
      // Preselect only an exact name match; the administrator still confirms it.
      for(const person of people)if(!person.bound)select.append(new Option(person.name+' 프로필과 연결',person.person_id,false,person.name===row.display_name));
      const actions=moleNode('div','','request-actions'),approve=moleNode('button','','request-approve','승인'),reject=moleNode('button','','request-reject','거절');
      approve.type='button';reject.type='button';const controls=[select,approve,reject];
      approve.addEventListener('click',()=>decide(row,'approve',select.value||null,controls));
      reject.addEventListener('click',()=>{if(window.confirm((row.display_name||'이 계정')+'의 가입 요청을 거절할까요? 거절한 계정은 다시 요청할 수 없어요.'))decide(row,'reject',null,controls);});
      actions.append(approve,reject);item.append(who,select,actions);requestsList.append(item);
    }
    return rows.length;
  }
  async function loadRequests(){
    if(requestsBusy)return null;
    requestsBusy=true;requestsStatus.textContent='요청을 불러오고 있어요.';
    try{
      const response=await fetch('/api/account/requests',{credentials:'same-origin',cache:'no-store'});
      const value=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(requestErrors[value?.code]||'요청을 불러오지 못했어요.');
      const count=renderRequests(value);setRequestsCount(count);requestsStatus.textContent=count?'':'기다리는 요청이 없어요.';return count;
    }catch(exc){requestsList.replaceChildren();requestsStatus.textContent=exc.message||'요청을 불러오지 못했어요.';return null;}
    finally{requestsBusy=false;}
  }
  async function decide(row,decision,personId,controls){
    if(requestsBusy)return;
    for(const node of controls)node.disabled=true;requestsStatus.textContent='처리하고 있어요.';
    try{
      const response=await fetch('/api/account/requests/decide',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-RnDplz-Token':token},body:JSON.stringify({account_id:row.account_id,decision,person_id:personId})});
      const value=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(requestErrors[value?.code]||'처리하지 못했어요.');
      const done=(decision==='approve'?'승인했어요: ':'거절했어요: ')+(row.display_name||'이름 없음')+'.';
      const left=await loadRequests();if(left!==null)requestsStatus.textContent=done+(left?'':' 남은 요청이 없어요.');
    }catch(exc){for(const node of controls)node.disabled=false;requestsStatus.textContent=exc.message||'처리하지 못했어요.';}
  }
  requestsEntry.addEventListener('click',()=>{if(ending||invalidated)return;close();requestsDialog.showModal();loadRequests();});
  requestsClose.addEventListener('click',()=>requestsDialog.close());
  requestsDialog.addEventListener('close',()=>{if(!ending&&!invalidated&&toggle.isConnected)toggle.focus({preventScroll:true});});
  window.addEventListener('rndplz:account-navigation',event=>{if(['begin','invalidate'].includes(event.detail?.phase)&&requestsDialog.open)requestsDialog.close();});
  // Policies for everyone who opens the menu, including visitors about to sign up.
  const legal=moleNode('p','accountLegal','account-note account-legal'),privacyLink=moleNode('a','','','개인정보처리방침'),termsLink=moleNode('a','','','이용약관');
  privacyLink.href='/privacy';termsLink.href='/terms';legal.append(privacyLink,' · ',termsLink);menu.append(legal);

  function permitNavigation(action){
    const detail={action,dirty:false,message:'',checkedScopes:[]};
    const event=new CustomEvent('rndplz:before-account-navigation',{cancelable:true,detail});
    window.dispatchEvent(event);
    const required=document.getElementById('profileForm')?'profile':document.getElementById('chatForm')?'chat':null;
    if(event.defaultPrevented){error.textContent=detail.message||'진행 중인 작업의 결과를 먼저 확인해 주세요.';return false;}
    if(required&&!detail.checkedScopes.includes(required)){error.textContent='작성 중인 내용을 확인하지 못했어요. 페이지를 새로 연 뒤 다시 시도해 주세요.';return false;}
    if(!required&&document.querySelector('dialog[open],main [aria-busy="true"]')){error.textContent='열린 작업을 마무리한 뒤 다시 시도해 주세요.';return false;}
    if(detail.dirty&&!window.confirm('저장하지 않은 입력과 선택이 있습니다. 저장하지 않고 이 화면을 떠날까요?'))return false;
    error.textContent='';return true;
  }
  function beginNavigation(action){
    ending=true;logout.disabled=true;
    for(const node of document.querySelectorAll('main,dialog')){inertBefore.set(node,node.inert);node.inert=true;}
    fire('rndplz:account-navigation',{phase:'begin',action});
  }
  function cancelNavigation(){
    ending=false;logout.disabled=!supported;
    for(const [node,prior] of inertBefore)node.inert=prior;inertBefore.clear();
    fire('rndplz:account-navigation',{phase:'cancel'});
  }
  function replaceAccountContext(){
    if(invalidated)return;
    invalidated=true;requestEpoch++;ending=true;
    fire('rndplz:account-navigation',{phase:'invalidate'});
    // Keep old-account content invisible even when the full navigation is delayed.
    document.documentElement.style.visibility='hidden';document.documentElement.inert=true;
    location.replace('/');
  }
  function broadcast(){try{localStorage.setItem('rndplz:account-changed',String(Date.now())+'-'+Math.random().toString(36).slice(2));}catch{}}
  function applyExpiredSession(value){
    if(principal!==null&&principal!=='expired'){replaceAccountContext();return;}
    principal='expired';token='';supported=false;logout.disabled=true;announceLogin=false;
    if(sessionExpired)return;
    sessionExpired=true;identity.textContent='';show(identity,false);
    // A confirmed missing account context is not a network error. Invalidate
    // owner requests before removing their DOM, then leave a fresh login page.
    fire('rndplz:account-navigation',{phase:'invalidate'});
    const recovery=document.createElement('section');
    recovery.className='paper';recovery.setAttribute('aria-labelledby','accountRecoveryTitle');
    recovery.style.maxWidth='32rem';recovery.style.margin='12vh auto';recovery.style.padding='2rem';
    const heading=document.createElement('h1');heading.id='accountRecoveryTitle';heading.textContent='로그인이 필요합니다';
    const explanation=document.createElement('p');explanation.textContent=value.enabled?'로그인 세션이 만료되었어요. Google 계정으로 다시 로그인해 주세요.':'이전 로그인 세션을 사용할 수 없어요. 팀원 로그인 준비 중입니다.';
    recovery.append(heading,explanation);
    if(value.enabled&&value.login_url==='/auth/google/start'){
      const entry=document.createElement('a');entry.href='/auth/google/start';entry.textContent='Google 계정으로 로그인';recovery.append(entry);
    }else{
      const unavailableNote=document.createElement('p');unavailableNote.textContent='로그인 연결을 확인하지 못했어요. 잠시 후 페이지를 다시 열어 주세요.';recovery.append(unavailableNote);
    }
    document.body.replaceChildren(recovery);
  }
  function applySession(value){
    if(!value||typeof value.enabled!=='boolean'||typeof value.authenticated!=='boolean')throw new Error('계정 상태를 확인하지 못했어요.');
    if(value.authenticated===false&&value.account===null&&value.token===null){applyExpiredSession(value);return;}
    if(typeof value.token!=='string'||!value.token)throw new Error('계정 상태를 확인하지 못했어요.');
    const account=value.account;
    if(value.authenticated&&(!account||typeof account.id!=='string'||!account.id))throw new Error('계정 상태를 확인하지 못했어요.');
    const next=value.authenticated?'account:'+account.id:'visitor:'+value.token;
    if(principal!==null&&next!==principal){replaceAccountContext();return;}
    principal=next;token=value.token;supported=true;logout.disabled=ending;
    setMoleAccount(value.authenticated?account.id:null,value.enabled?'로그인 후 확인할 수 있어요.':'팀원 로그인 준비 중');
    if(moleLoadAfterSession){moleLoadAfterSession=false;if(value.authenticated&&!menu.hidden)loadMole();}
    if(announceLogin){announceLogin=false;if(value.authenticated)broadcast();}
    show(identity,value.authenticated);show(login,false);show(unavailable,false);show(signupNote,false);
    const admin=value.authenticated&&value.admin===true;show(requestsEntry,admin);
    if(admin)setRequestsCount(Number.isSafeInteger(value.pending_requests)?value.pending_requests:0);else if(requestsDialog.open)requestsDialog.close();
    if(value.authenticated)show(pendingNote,false);
    accountIcon(value.authenticated?account:null);
    if(value.authenticated){
      identity.textContent=(typeof account.display_name==='string'&&account.display_name.trim())||'Google 계정';
      note.textContent=account.person_id?'연구맵 공개 카드와 연결된 계정이에요. 내 프로필에서 저장한 내용이 카드에 바로 반영돼요.':'본인 계정의 비공개 프로필입니다. 공개 인물 카드와 자동으로 연결되지 않습니다.';
    }else{
      note.textContent='임시 방문자 세션입니다. 로그인해도 기존 방문자 기록이 계정으로 자동 이동하지 않습니다.';
      if(value.enabled&&value.login_url==='/auth/google/start'){show(login,true);show(signupNote,value.signup_requests===true);}
      else{show(unavailable,true);unavailable.textContent='팀원 로그인 준비 중';if(typeof value.disabled_reason==='string'&&value.disabled_reason.trim())unavailable.textContent+=' · '+value.disabled_reason;}
      // After a sign-up request, open the menu once so the visitor sees what happens next.
      if(pendingNotice){pendingNotice=false;menu.hidden=false;toggle.setAttribute('aria-expanded','true');}
    }
  }
  async function legacyBootstrap(epoch){
    const response=await fetch('/api/chat/bootstrap',{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw new Error('세션 상태를 불러오지 못했어요.');
    const value=await response.json();if(epoch!==requestEpoch||invalidated)return;
    const nextToken=typeof value.token==='string'?value.token:'';
    if(principal!==null&&principal!=='visitor:'+nextToken){replaceAccountContext();return;}
    setMoleAccount(null,'로그인 연결을 확인한 뒤 이용할 수 있어요.');
    token=nextToken;principal='visitor:'+token;supported=value.logout_supported===true&&!!token;logout.disabled=ending||!supported;
    show(identity,false);show(login,false);show(unavailable,false);
    note.textContent=supported?'임시 방문자 세션입니다. 로그아웃하면 이 화면에서 저장 기록에 다시 접근할 수 없어요.':'로컬 단일 사용자 모드 · 별도 로그인 세션이 없습니다.';
  }
  async function refreshSession(verifyLogout=false){
    if((checking&&!verifyLogout)||(ending&&!verifyLogout)||invalidated)return;
    checking=true;const epoch=++requestEpoch;
    if(verifySession)verifySession.disabled=true;
    try{
      const response=await fetch('/api/account/session',{credentials:'same-origin',cache:'no-store'});
      if(epoch!==requestEpoch||invalidated)return;
      if(response.status===404){accountAPI=false;await legacyBootstrap(epoch);}
      else{
        if(!response.ok)throw new Error('계정 상태를 불러오지 못했어요.');
        const value=await response.json();if(epoch!==requestEpoch||invalidated)return;
        applySession(value);accountAPI=true;
      }
      if(verifyLogout&&epoch===requestEpoch&&!invalidated){
        logoutUncertain=false;show(verifySession,false);cancelNavigation();
        error.textContent='같은 세션이 유지되고 있습니다. 작성 중인 내용을 계속할 수 있어요.';
      }
    }catch(exc){if(epoch!==requestEpoch||invalidated)return;supported=false;logout.disabled=true;show(login,false);show(signupNote,false);show(requestsEntry,false);moleLoadAfterSession=false;setMoleAccount(null,'계정 상태를 확인하지 못했어요. 메뉴를 다시 열면 다시 확인합니다.');note.textContent=exc.message||'계정 상태를 불러오지 못했어요.';}
    finally{if(epoch===requestEpoch){checking=false;if(verifySession)verifySession.disabled=false;}}
  }
  toggle.addEventListener('click',()=>{menu.hidden=!menu.hidden;toggle.setAttribute('aria-expanded',String(!menu.hidden));if(!menu.hidden){if(moleAccount)loadMole();else{moleLoadAfterSession=true;refreshSession();}Array.from(menu.querySelectorAll('button:not(:disabled),a')).find(node=>!node.hidden&&node.style.display!=='none')?.focus();}});
  document.addEventListener('click',event=>{if(!event.target.closest('.account-control'))close();else if(event.target.closest('#accountMenu a,#accountMenu button:not(#logoutButton)')&&!event.defaultPrevented)close();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!menu.hidden){event.preventDefault();close(true);}});
  login?.addEventListener('click',event=>{event.preventDefault();if(login.hidden||ending||invalidated||!permitNavigation('login'))return;beginNavigation('login');location.assign('/auth/google/start');});
  logout.addEventListener('click',async()=>{
    if(!supported||ending||invalidated||!permitNavigation('logout'))return;
    beginNavigation('logout');
    try{
      const response=await fetch('/api/logout',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-RnDplz-Token':token},body:'{}'});
      const value=await response.json();if(!response.ok)throw new Error(typeof value.error==='string'?value.error:'세션을 끝내지 못했어요.');
      broadcast();replaceAccountContext();
    }catch(exc){if(invalidated)return;logoutUncertain=true;show(verifySession,true);error.textContent='로그아웃 결과를 확인하지 못했어요. 입력을 보존하고 계정 상태를 확인할 때까지 편집을 잠급니다.';await refreshSession(true);}
  });
  verifySession?.addEventListener('click',()=>{if(logoutUncertain&&!checking)refreshSession(true);});
  window.addEventListener('storage',event=>{if(event.key==='rndplz:account-changed'||event.key==='rndplz:visitor-ended')replaceAccountContext();});
  window.addEventListener('focus',()=>{if(logoutUncertain||accountAPI!==false)refreshSession(logoutUncertain);});
  window.addEventListener('pageshow',event=>{if(event.persisted)replaceAccountContext();});
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&(logoutUncertain||accountAPI!==false))refreshSession(logoutUncertain);});
  refreshSession();
})();
