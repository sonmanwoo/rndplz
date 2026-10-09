/* Shared motion language: paper, stickers, correspondence, and a field of records. */
(() => {
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  let motionDisabled = false, quiet = preference.matches, activeCard = null;
  try { motionDisabled=sessionStorage.getItem('rndplz-motion')==='off'; } catch {}
  const subscribers = new Set();
  function setQuiet(value,remember=false) {
    if(remember) {
      motionDisabled=Boolean(value);
      try{sessionStorage.setItem('rndplz-motion',motionDisabled?'off':'on');}catch{}
    }
    quiet = preference.matches || motionDisabled;
    document.body.classList.toggle('no-motion', quiet);
    document.querySelectorAll('[data-motion-toggle]').forEach(b => {
      b.setAttribute('aria-pressed', String(quiet));
      b.disabled=preference.matches;
      b.title=preference.matches?'기기의 움직임 줄이기 설정을 따릅니다.':'화면 움직임 켜기 또는 끄기';
      const label = b.querySelector('[data-motion-label]');
      if (label) label.textContent = '움직임 ' + (quiet ? '꺼짐' : '켜짐');
      else b.innerHTML = '<span class="motion-dot"></span> 움직임 ' + (quiet ? '꺼짐' : '켜짐');
    });
    subscribers.forEach(fn => fn());
    syncLaureateEffects();
  }
  preference.addEventListener('change', () => setQuiet(motionDisabled));
  document.addEventListener('click', e => {
    if (e.target.closest('[data-motion-toggle]') && !preference.matches) setQuiet(!quiet,true);
  });
  const resetCard = () => {
    if (!activeCard) return;
    activeCard.style.removeProperty('--rx'); activeCard.style.removeProperty('--ry');
    activeCard.style.removeProperty('--light-x'); activeCard.style.removeProperty('--light-y');
    activeCard = null;
  };
  document.addEventListener('pointermove', e => {
    if (quiet || e.pointerType === 'touch') return;
    const card = e.target.closest('[data-tilt]');
    if (activeCard !== card) resetCard();
    if (!card || (card.matches('[data-laureate-card]') && effectiveLaureateEffect()==='off')) return;
    activeCard = card;
    const r = card.getBoundingClientRect(), x = (e.clientX-r.left)/r.width, y = (e.clientY-r.top)/r.height;
    card.style.setProperty('--rx', ((.5-y)*7).toFixed(2)+'deg');
    card.style.setProperty('--ry', ((x-.5)*9).toFixed(2)+'deg');
    card.style.setProperty('--light-x', (x*100)+'%'); card.style.setProperty('--light-y', (y*100)+'%');
  }, {passive:true});
  document.addEventListener('pointerout', e => { if (activeCard && !activeCard.contains(e.relatedTarget)) resetCard(); });
  subscribers.add(resetCard);

  // Unit sphere -> yaw/pitch -> perspective. Every point keeps its real person ID.
  class TileOrbit {
    static position(index, count) {
      const y=1-2*(index+.5)/Math.max(1,count), r=Math.sqrt(1-y*y), a=index*2.399963229728653;
      return {x:Math.cos(a)*r,y,z:Math.sin(a)*r};
    }
    static rotate(p,yaw,pitch) {
      const x=p.x*Math.cos(yaw)+p.z*Math.sin(yaw), z=-p.x*Math.sin(yaw)+p.z*Math.cos(yaw);
      return {x,y:p.y*Math.cos(pitch)-z*Math.sin(pitch),z:p.y*Math.sin(pitch)+z*Math.cos(pitch)};
    }
    static project(p,size) {
      const scale=3.6/(3.6-p.z);
      return {x:size*(.5+p.x*.395*scale),y:size*(.46+p.y*.395*scale),scale};
    }
    static contains(corners,x,y) {
      let sign=0;
      for(let i=0;i<4;i++) {
        const a=corners[i],b=corners[(i+1)%4],cross=(b.x-a.x)*(y-a.y)-(b.y-a.y)*(x-a.x);
        if(Math.abs(cross)<.0001)continue;
        if(sign&&Math.sign(cross)!==sign)return false;
        sign=Math.sign(cross);
      }
      return !!sign;
    }
    constructor(canvas) {
      this.canvas=canvas;this.ctx=canvas.getContext('2d');this.points=[];this.rendered=[];
      this.yaw=.35;this.pitch=-.16;this.velocity={x:0,y:0};
      this.frame=0;this.last=0;this.visible=true;this.suspended=false;this.paused=false;this.hover=null;
      this.drag=null;this.blockClick=false;this.samples=[];this.intervals=[];this.measured=false;
      this.started=performance.now();
      this.controls=canvas.closest('.orbit-container');
      this.controls?.querySelectorAll('[data-orbit]').forEach(button=>button.addEventListener('click',()=>{
        const action=button.dataset.orbit;
        if(action==='pause')this.togglePause();
        else if(action==='reset')this.reset();
        else this.turn(action==='left'?-.22:.22,0);
      }));
      canvas.addEventListener('pointerdown',e=>{
        if(this.suspended||e.button!==0||this.drag)return;
        this.drag={id:e.pointerId,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,moved:false};
        this.blockClick=false;this.velocity={x:0,y:0};this.hover=null;
        canvas.setPointerCapture(e.pointerId);
        canvas.classList.add('is-dragging');this.kick();
      });
      canvas.addEventListener('pointermove',e=>{
        if(this.suspended)return;
        if(this.drag?.id===e.pointerId) {
          const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;
          if(Math.hypot(e.clientX-this.drag.startX,e.clientY-this.drag.startY)>5)this.drag.moved=true;
          const factor=3.2/Math.max(1,this.size);
          this.yaw+=dx*factor;this.pitch=Math.max(-1.35,Math.min(1.35,this.pitch+dy*factor));
          this.velocity={x:Math.max(-.075,Math.min(.075,dx*factor)),y:Math.max(-.055,Math.min(.055,dy*factor))};this.drag.x=e.clientX;this.drag.y=e.clientY;
          this.hover=null;this.kick();
        } else {
          this.hover=this.hit(e);canvas.style.cursor=this.hover?'pointer':'grab';this.kick();
        }
      });
      const end=e=>{
        if(this.drag?.id!==e.pointerId)return;
        this.blockClick=this.drag.moved||e.type==='pointercancel';
        if(!this.drag.moved||quiet||this.paused||e.type==='pointercancel')this.velocity={x:0,y:0};
        this.drag=null;canvas.classList.remove('is-dragging');
        if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);
        this.kick();
      };
      canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',end);
      canvas.addEventListener('lostpointercapture',end);
      canvas.addEventListener('pointerleave',()=>{this.hover=null;this.kick();});
      canvas.addEventListener('keydown',e=>{
        if(this.suspended)return;
        const steps={ArrowLeft:[-.16,0],ArrowRight:[.16,0],ArrowUp:[0,-.16],ArrowDown:[0,.16]};
        if(steps[e.key]){e.preventDefault();this.turn(...steps[e.key]);}
        else if(e.key===' '){e.preventDefault();this.togglePause();}
        else if(e.key==='Home'){e.preventDefault();this.reset();}
      });
      this.observer=new IntersectionObserver(entries=>{
        this.visible=entries[0].isIntersecting;this.last=0;this.kick();
      });this.observer.observe(canvas);
      this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(canvas);
      document.addEventListener('visibilitychange',()=>{this.last=0;this.kick();});
      this.syncPalette();
      window.addEventListener('susomun:themechange',()=>{this.syncPalette();this.kick();});
      subscribers.add(()=>{this.velocity={x:0,y:0};this.syncControls();this.kick();});
      this.resize();this.syncControls();
    }
    syncPalette() {
      const style=getComputedStyle(this.canvas);
      const color=(name,fallback)=>style.getPropertyValue(name).trim()||fallback;
      this.palette=['#c9aa8a','#33584c','#90abc5','#aa91b9','#d5b557','#e4dcc5','#283e3b'].map((value,i)=>color('--orbit-'+(i+1),value));
      this.virtualColor=color('--orbit-virtual','#cd503b');
      this.detailColor=color('--orbit-detail','#fff9');
      this.hoverColor=color('--orbit-hover','#c84c38');
    }
    syncControls() {
      const button=this.controls?.querySelector('[data-orbit="pause"]');
      if(button) {
        button.textContent=quiet?'자동 회전 꺼짐':this.paused?'자동 회전 재생':'자동 회전 일시정지';
        button.setAttribute('aria-pressed',String(quiet||this.paused));
        button.disabled=quiet;
      }
    }
    togglePause(){if(this.suspended)return;this.paused=!this.paused;this.velocity={x:0,y:0};this.syncControls();this.kick();}
    turn(yaw,pitch){if(this.suspended)return;this.yaw+=yaw;this.pitch=Math.max(-1.35,Math.min(1.35,this.pitch+pitch));this.hover=null;this.velocity={x:0,y:0};this.kick();}
    reset(){if(this.suspended)return;this.yaw=.35;this.pitch=-.16;this.hover=null;this.velocity={x:0,y:0};this.kick();}
    consumeClick(){const blocked=this.suspended||this.blockClick;this.blockClick=false;return blocked;}
    clearInteraction(blockClick=false){
      const drag=this.drag;this.drag=null;this.blockClick=blockClick;
      if(drag&&this.canvas.hasPointerCapture(drag.id))this.canvas.releasePointerCapture(drag.id);
      this.canvas.classList.remove('is-dragging');this.canvas.style.cursor='grab';
      this.hover=null;this.rendered=[];this.velocity={x:0,y:0};
      const tooltip=this.controls?.querySelector('.map-tooltip');
      if(tooltip){tooltip.hidden=true;tooltip.textContent='';}
    }
    suspend(){
      this.suspended=true;
      if(this.frame)cancelAnimationFrame(this.frame);
      this.frame=0;this.last=0;this.clearInteraction();this.points=[];this.signature=null;
      if(this.size)this.ctx.clearRect(0,0,this.size,this.size);
    }
    resume(nodes,topic=''){
      const returning=this.suspended;
      this.suspended=false;
      if(returning){this.yaw=.35;this.pitch=-.16;this.last=0;}
      this.setData(nodes,topic);
      if(returning||!this.size)this.resize();
    }
    resize(){
      if(this.suspended)return;
      const b=this.canvas.getBoundingClientRect();
      const d=Math.min(devicePixelRatio||1,2),width=Math.round(b.width*d);
      if(this.size===b.width&&this.canvas.width===width)return;
      this.clearInteraction(Boolean(this.drag));this.size=b.width;
      this.canvas.width=width;this.canvas.height=width;
      this.ctx.setTransform(d,0,0,d,0,0);this.kick();
    }
    setData(nodes,topic='') {
      if(this.suspended)return;
      const visibleNodes=topic?nodes.filter(node=>(node.topics||[]).includes(topic)):nodes;
      const signature=topic+'|'+visibleNodes.map(n=>n.id).join(',');
      if(this.signature===signature)return;
      this.signature=signature;this.started=performance.now();this.last=0;
      // Removed people must leave both the drawing and picking buffers immediately.
      this.clearInteraction(Boolean(this.drag));
      if(visibleNodes.length===1){this.yaw=0;this.pitch=0;}
      this.points=visibleNodes.map((node,i)=>{
        const position=visibleNodes.length===1?{x:0,y:0,z:1}:TileOrbit.position(i,visibleNodes.length);
        const length=Math.hypot(position.x,position.z);
        const u={x:position.z/length,y:0,z:-position.x/length};
        const v={x:position.y*u.z,y:position.z*u.x-position.x*u.z,z:-position.y*u.x};
        const width=.052*Math.min(1.25,1+Math.log2(node.record_count+1)*.06);
        const corners=[[-1,-1],[1,-1],[1,1],[-1,1]].map(([a,b])=>({
          x:position.x+u.x*a*width/2+v.x*b*width*.68,
          y:position.y+u.y*a*width/2+v.y*b*width*.68,
          z:position.z+u.z*a*width/2+v.z*b*width*.68
        }));
        return {node,i,position,corners,selected:true};
      });
      this.kick();
    }
    kick(){if(!this.suspended&&!this.frame&&this.visible&&!document.hidden)this.frame=requestAnimationFrame(t=>this.draw(t));}
    draw(now) {
      this.frame=0;if(this.suspended||!this.visible||document.hidden||!this.size)return;
      const moving=this.points.length>1&&!quiet&&!this.paused&&!this.drag&&!this.hover;
      if(moving&&this.last&&now-this.last<28){this.kick();return;}
      const interval=this.last?now-this.last:0,dt=Math.min(interval||16.7,50)/16.7;this.last=now;
      if(moving) {
        this.yaw+=.0016*dt+this.velocity.x*dt;
        this.pitch=Math.max(-1.35,Math.min(1.35,this.pitch+this.velocity.y*dt));
        this.velocity.x*=Math.pow(.89,dt);this.velocity.y*=Math.pow(.89,dt);
      }
      const begun=performance.now(),ctx=this.ctx,s=this.size;
      ctx.clearRect(0,0,s,s);
      // A very light atmosphere and ground shadow support depth without a central panel.
      const halo=ctx.createRadialGradient(s*.44,s*.39,0,s*.5,s*.46,s*.415);
      halo.addColorStop(0,'#ffffff00');halo.addColorStop(.68,'#8a968105');halo.addColorStop(.92,'#65745d0c');halo.addColorStop(1,'#65745d00');
      ctx.fillStyle=halo;ctx.fillRect(0,0,s,s);
      const shadow=ctx.createRadialGradient(s*.5,s*.92,0,s*.5,s*.92,s*.23);
      shadow.addColorStop(0,'#37412b18');shadow.addColorStop(1,'#37412b00');
      ctx.save();ctx.translate(0,s*.92);ctx.scale(1,.11);ctx.translate(0,-s*.92);
      ctx.fillStyle=shadow;ctx.fillRect(s*.2,s*.65,s*.6,s*.55);ctx.restore();
      const palette=this.palette;
      this.rendered=this.points.map(p=>{
        const rotated=TileOrbit.rotate(p.position,this.yaw,this.pitch),screen=TileOrbit.project(rotated,s);
        p.depth=rotated.z;p.drawX=screen.x;p.drawY=screen.y;
        p.screen=p.corners.map(c=>TileOrbit.project(TileOrbit.rotate(c,this.yaw,this.pitch),s));
        return p;
      }).sort((a,b)=>a.depth-b.depth);
      for(const p of this.rendered) {
        const front=p.depth>1/3.6,c=p.screen;
        ctx.globalAlpha=front?.6+.4*p.depth:.055+.1*(p.depth+1)/2;
        ctx.fillStyle=p.node.virtual?this.virtualColor:palette[p.i%palette.length];
        ctx.beginPath();ctx.moveTo(c[0].x,c[0].y);
        for(let j=1;j<4;j++)ctx.lineTo(c[j].x,c[j].y);ctx.closePath();ctx.fill();
        if(front) {
          // Paper detail follows the same projected plane.
          ctx.strokeStyle=this.detailColor;ctx.lineWidth=Math.max(.5,s/900);
          ctx.beginPath();
          ctx.moveTo(c[0].x*.72+c[3].x*.28,c[0].y*.72+c[3].y*.28);
          ctx.lineTo(c[1].x*.72+c[2].x*.28,c[1].y*.72+c[2].y*.28);ctx.stroke();
          if(this.hover===p) {ctx.globalAlpha=1;ctx.strokeStyle=this.hoverColor;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(c[0].x,c[0].y);for(let j=1;j<4;j++)ctx.lineTo(c[j].x,c[j].y);ctx.closePath();ctx.stroke();}
        }
      }
      ctx.globalAlpha=1;
      // Bounded developer diagnostics: render CPU and real frame intervals, never profile content.
      if(moving&&!this.measured&&interval>0&&interval<120) {
        this.samples.push(performance.now()-begun);this.intervals.push(interval);
        if(this.samples.length===120) {
          const sorted=[...this.samples].sort((a,b)=>a-b);
          console.info('[research sphere]',JSON.stringify({tiles:this.points.length,width:Math.round(s),samples:120,drawMeanMs:+(this.samples.reduce((a,b)=>a+b,0)/120).toFixed(2),drawP95Ms:+sorted[113].toFixed(2),frameMeanMs:+(this.intervals.reduce((a,b)=>a+b,0)/120).toFixed(2)}));
          this.measured=true;
        }
      }
      if(moving)this.kick();
    }
    hit(event) {
      if(this.suspended||this.drag)return null;
      const b=this.canvas.getBoundingClientRect(),x=event.clientX-b.left,y=event.clientY-b.top;
      // Front-most selectable paper wins; back faces never intercept a visible profile.
      for(let i=this.rendered.length-1;i>=0;i--) {
        const p=this.rendered[i];
        if(p.selected&&p.depth>1/3.6&&TileOrbit.contains(p.screen,x,y))return p;
      }
      return null;
    }
  }
  const pause = ms => new Promise(resolve=>setTimeout(resolve,quiet?0:ms));
  function deliver(name,count=1){
    const scene=document.createElement('dialog');scene.className='delivery-scene';scene.setAttribute('aria-label','제안 보관 완료');
    scene.innerHTML='<button class="scene-close" aria-label="완료 화면 닫기">×</button><div class="dispatch-art" aria-hidden="true"><div class="dispatch-note"><span class="service-name">수소문 / CORRESPONDENCE</span><strong></strong><i></i><i></i><i></i></div><div class="dispatch-envelope"><div class="envelope-flap"></div><div class="envelope-pocket"></div><span class="envelope-seal">H</span></div></div><div class="dispatch-copy"><span class="micro">SAFELY FILED · '+count+' LETTER'+(count>1?'S':'')+'</span><h2>연결의 첫 문장을 남겼어요.</h2><p>제안함에 시연 기록으로 보관했습니다.</p><a class="primary" href="/explore#inbox">제안함 열기 ↗</a><button class="text-button scene-done">대화로 돌아가기</button></div>';
    scene.querySelector('.dispatch-note strong').textContent=name+'님께';
    document.body.append(scene);scene.addEventListener('close',()=>scene.remove());
    scene.querySelectorAll('.scene-close,.scene-done').forEach(b=>b.addEventListener('click',()=>scene.close()));
    scene.showModal();scene.querySelector('.scene-close').focus();
  }
  const html = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const isLaureate=profile=>window.RndPersonView.isLaureate(profile);
  const isPersonalIllustration=profile=>window.RndPersonView.isPersonalIllustration(profile);
  function effectiveLaureateEffect(){return 'off';}
  function effectControls(profile,name) {return '';}
  function syncLaureateEffects(){
    document.querySelectorAll('[data-laureate-card],.laureate-portrait').forEach(node=>node.dataset.laureateEffect=effectiveLaureateEffect());
  }
  // A single capture listener handles images inserted by either product renderer.
  function portraitState(event){
    const img=event.target;
    if(!img.matches?.('img[data-laureate-image],img[data-personal-image]'))return;
    const frame=img.closest('.laureate-portrait,.personal-illustration');
    if(!frame)return;
    const ready=event.type==='load' && img.naturalWidth>0;
    frame.dataset.asset=ready?'ready':'failed';frame.setAttribute('aria-busy','false');
    const status=frame.querySelector('.portrait-status');
    if(status){status.hidden=ready;status.textContent=ready?'':'일러스트를 불러오지 못했습니다. 이력과 근거는 아래에서 읽을 수 있습니다.';}
  }
  document.addEventListener('load',portraitState,true);
  document.addEventListener('error',portraitState,true);
  function portrait(profile,name){return window.RndPersonView.portrait(profile,name);}
  function awardSummary(profile){return window.RndPersonView.awardSummary(profile);}
  function laureateAttributes(profile){return window.RndPersonView.laureateAttributes(profile);}
  function nameBlock(person,heading='h3',className='laureate-name',options={}){return window.RndPersonView.nameBlock(person,heading,className,options);}
  function personalPortraitNote(profile,detailed=false){return window.RndPersonView.personalPortraitNote(profile,detailed);}
  function researcherCard(person,index=0,total=1) {
    const view=window.RndPersonView,name=view.displayName(person),line=view.capability(person);
    const face=view.portrait(person.profile,name,{variant:'card',className:'simple-portrait',loading:'lazy'});
    person={...person,name};
    return '<button type="button" class="researcher-card simplified-person" data-action="person" data-id="'+html(person.id)+'" aria-label="'+html(person.name)+' 상세 보기"><span class="simple-person-name">'+html(person.name)+'</span>'+face+'<span class="simple-person-capability" title="'+html(line)+'">'+html(line)+'</span></button>';
  }
  function profileDetails(person,options={}){return window.RndPersonView.render(person,options);}
  window.RndCraft={TileOrbit,deliver,pause,portrait,researcherCard,profileDetails,isLaureate,isPersonalIllustration,personalPortraitNote,awardSummary,effectControls,laureateAttributes,nameBlock,quiet:()=>quiet};
  setQuiet(quiet);
})();
/* grape-egg:start — 이스터에그: 가운데 카드 10번 → 포도알 → 비밀번호 → 편지 */
(() => {
  const hero = document.querySelector('.hero-object');
  const card = hero && hero.querySelector('.mini-sheet:nth-child(2)');
  if (!card) return;
  const LOCK = {"iter": 200000, "salt": "b3KvExAgLxEmAkKC9vr13Q==", "iv": "J3W+iEerL/gLVuUf", "data": "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"};
  const HINT = '해커톤 개발자 리그 오프라인 모임의 날짜는?';
  const EXAMPLE = 'Ex. 20600101';
  const NEED = 10;
  const NS = 'http://www.w3.org/2000/svg';
  const POS = [[60,118],[45,93],[75,93],[30,68],[60,68],[90,68],[15,43],[45,43],[75,43],[105,43]];
  let taps = 0, dialog = null;

  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const svg = (box, inner) => { const s = document.createElementNS(NS, 'svg'); s.setAttribute('viewBox', box); s.setAttribute('aria-hidden', 'true'); s.innerHTML = inner; return s; };

  function grapeMark() {
    return svg('0 0 62 82',
      '<path d="M31 24C31 16 29 10 27 5" stroke="#7A6046" stroke-width="3" fill="none" stroke-linecap="round"/>' +
      '<path d="M28 11C37 3 49 5 52 10C47 17 36 18 28 11Z" fill="#4E7A3A"/>' +
      '<circle cx="31" cy="50" r="25" fill="#6D3B94"/><circle cx="22" cy="40" r="6.5" fill="#fff" fill-opacity=".45"/>');
  }

  function bunch() {
    let inner = '<path d="M60 30C60 20 57 12 54 5" stroke="#7A6046" stroke-width="3" fill="none" stroke-linecap="round"/><path d="M56 12C68 2 84 4 88 10C82 20 66 22 56 12Z" fill="#4E7A3A"/>';
    POS.forEach(([x, y]) => { inner += '<circle cx="' + x + '" cy="' + y + '" r="12" fill="#6D3B94"/><circle cx="' + (x - 4) + '" cy="' + (y - 4.5) + '" r="3.2" fill="#fff" fill-opacity=".45"/>'; });
    const s = svg('0 0 120 136', inner); s.setAttribute('class', 'egg-bunch'); return s;
  }

  async function unlock(password) {
    const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey']);
    const key = await crypto.subtle.deriveKey({ name: 'PBKDF2', salt: b64(LOCK.salt), iterations: LOCK.iter, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(LOCK.iv) }, key, b64(LOCK.data));
    return JSON.parse(new TextDecoder().decode(plain));
  }

  function line(parent, text) {
    text.split(/(~~.+?~~)/).forEach(part => {
      if (!part) return;
      if (part.startsWith('~~')) parent.appendChild(el('s', '', part.slice(2, -2)));
      else parent.appendChild(document.createTextNode(part));
    });
  }

  function showLetters(letters) {
    const lock = dialog.querySelector('.egg-lock');
    const host = dialog.querySelector('.egg-letters');
    const tabs = el('div', 'egg-tabs'), paper = el('article', 'egg-paper');
    const pick = i => {
      [...tabs.children].forEach((b, n) => b.setAttribute('aria-pressed', String(n === i)));
      paper.replaceChildren();
      const paras = letters[i].paras;
      paras.forEach((p, n) => {
        const node = el('p', n === 0 ? 'greet' : n === paras.length - 1 ? 'sign' : '');
        p.split('\n').forEach((l, k) => { if (k) node.appendChild(document.createElement('br')); line(node, l); });
        paper.appendChild(node);
      });
      paper.appendChild(bunch());
      paper.scrollTop = 0;
    };
    letters.forEach((l, i) => { const b = el('button', 'egg-tab', l.to); b.type = 'button'; b.addEventListener('click', () => pick(i)); tabs.appendChild(b); });
    host.replaceChildren(tabs, paper);
    pick(0);
    lock.hidden = true; host.hidden = false;
    dialog.querySelector('h2').textContent = '포도알 편지';
    dialog.scrollTop = 0;
  }

  function openDialog() {
    if (!dialog) {
      dialog = el('dialog', 'egg-dialog');
      const head = el('div', 'dialog-heading');
      const title = el('h2', '', '포도알'), close = el('button', 'icon-button close', '×');
      close.type = 'button'; close.setAttribute('aria-label', '닫기'); close.addEventListener('click', () => dialog.close());
      head.append(title, close);
      const form = el('form', 'egg-lock');
      const hint = el('p', 'egg-hint', HINT); hint.appendChild(el('small', '', EXAMPLE));
      const input = el('input'); input.type = 'text'; input.inputMode = 'numeric'; input.maxLength = 8; input.autocomplete = 'off'; input.setAttribute('aria-label', '비밀번호');
      const go = el('button', 'outline', '열기'); go.type = 'submit';
      const err = el('p', 'egg-error', '아직 아니에요. 힌트를 다시 읽어 보세요.'); err.hidden = true; err.setAttribute('role', 'alert');
      form.append(hint, input, go, err);
      form.addEventListener('submit', async ev => {
        ev.preventDefault(); err.hidden = true; go.disabled = true;
        try { showLetters(await unlock(input.value.trim())); }
        catch { err.textContent = window.crypto && crypto.subtle ? '아직 아니에요. 힌트를 다시 읽어 보세요.' : '이 주소에서는 열 수 없어요. 보안 연결(https)로 접속해 주세요.'; err.hidden = false; input.select(); }
        go.disabled = false;
      });
      const letters = el('div', 'egg-letters'); letters.hidden = true;
      dialog.append(head, form, letters);
      dialog.addEventListener('close', () => { form.hidden = false; letters.hidden = true; letters.replaceChildren(); title.textContent = '포도알'; input.value = ''; err.hidden = true; });
      document.body.appendChild(dialog);
    }
    dialog.showModal();
    const input = dialog.querySelector('input');
    if (input && !dialog.querySelector('.egg-lock').hidden) input.focus();
  }

  card.addEventListener('click', () => {
    if (card.classList.contains('egg-grape')) return openDialog();
    if (++taps < NEED) return;
    card.classList.add('egg-grape');
    card.replaceChildren(grapeMark());
  });
})();
/* grape-egg:end */
