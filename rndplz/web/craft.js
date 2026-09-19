/* Shared motion language: paper, stickers, correspondence, and a field of records. */
(() => {
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  let motionDisabled = false, quiet = preference.matches, activeCard = null;
  let laureateEffect = 'off'; // Page-session choice survives every card/detail render.
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
      b.innerHTML = '<span class="motion-dot"></span> 움직임 ' + (quiet ? '꺼짐' : '켜짐');
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
      subscribers.add(()=>{this.velocity={x:0,y:0};this.syncControls();this.kick();});
      this.resize();this.syncControls();
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
      const palette=['#c9aa8a','#33584c','#90abc5','#aa91b9','#d5b557','#e4dcc5','#283e3b'];
      this.rendered=this.points.map(p=>{
        const rotated=TileOrbit.rotate(p.position,this.yaw,this.pitch),screen=TileOrbit.project(rotated,s);
        p.depth=rotated.z;p.drawX=screen.x;p.drawY=screen.y;
        p.screen=p.corners.map(c=>TileOrbit.project(TileOrbit.rotate(c,this.yaw,this.pitch),s));
        return p;
      }).sort((a,b)=>a.depth-b.depth);
      for(const p of this.rendered) {
        const front=p.depth>1/3.6,c=p.screen;
        ctx.globalAlpha=front?.6+.4*p.depth:.055+.1*(p.depth+1)/2;
        ctx.fillStyle=p.node.virtual?'#cd503b':palette[p.i%palette.length];
        ctx.beginPath();ctx.moveTo(c[0].x,c[0].y);
        for(let j=1;j<4;j++)ctx.lineTo(c[j].x,c[j].y);ctx.closePath();ctx.fill();
        if(front) {
          // Paper detail follows the same projected plane.
          ctx.strokeStyle='#fff9';ctx.lineWidth=Math.max(.5,s/900);
          ctx.beginPath();
          ctx.moveTo(c[0].x*.72+c[3].x*.28,c[0].y*.72+c[3].y*.28);
          ctx.lineTo(c[1].x*.72+c[2].x*.28,c[1].y*.72+c[2].y*.28);ctx.stroke();
          if(this.hover===p) {ctx.globalAlpha=1;ctx.strokeStyle='#c84c38';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(c[0].x,c[0].y);for(let j=1;j<4;j++)ctx.lineTo(c[j].x,c[j].y);ctx.closePath();ctx.stroke();}
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
    scene.innerHTML='<button class="scene-close" aria-label="완료 화면 닫기">×</button><div class="dispatch-art" aria-hidden="true"><div class="dispatch-note"><span>H:문 / CORRESPONDENCE</span><strong></strong><i></i><i></i><i></i></div><div class="dispatch-envelope"><div class="envelope-flap"></div><div class="envelope-pocket"></div><span class="envelope-seal">H</span></div></div><div class="dispatch-copy"><span class="micro">SAFELY FILED · '+count+' LETTER'+(count>1?'S':'')+'</span><h2>연결의 첫 문장을 남겼어요.</h2><p>제안함에 시연 기록으로 보관했습니다.</p><a class="primary" href="/explore#inbox">제안함 열기 ↗</a><button class="text-button scene-done">대화로 돌아가기</button></div>';
    scene.querySelector('.dispatch-note strong').textContent=name+'님께';
    document.body.append(scene);scene.addEventListener('close',()=>scene.remove());
    scene.querySelectorAll('.scene-close,.scene-done').forEach(b=>b.addEventListener('click',()=>scene.close()));
    scene.showModal();scene.querySelector('.scene-close').focus();
  }
  const html = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const isLaureate = profile => profile?.award?.name === 'Nobel Prize';
  const isPersonalIllustration = profile => ['LOCAL-MANWOO','LOCAL-JINHO'].includes(profile?.id) && ['self_reported','provided_resume'].includes(profile?.source_type) && profile?.portrait?.kind==='personal_illustration' && profile.portrait.generated===true;
  const sourceLink = (url,label) => {
    try { if(['http:','https:'].includes(new URL(url).protocol))return '<a href="'+html(url)+'" target="_blank" rel="noopener noreferrer">'+html(label)+' ↗</a>'; } catch {}
    return label==='출처'?'':'<span>'+html(label)+'</span>';
  };
  const artPath = value => typeof value==='string' && /^\/portraits\/[a-zA-Z0-9_.-]+\.(?:png|jpe?g|webp)$/.test(value) ? value : '';
  function effectiveLaureateEffect(){return quiet?'off':laureateEffect;}
  function effectHint(){return preference.matches?'기기의 움직임 줄이기 설정에 따라 효과가 꺼져 있습니다.':quiet?'화면 움직임이 꺼져 있어 일러스트 효과도 쉬고 있습니다.':'선택한 표현 효과는 연구 역량이나 협업 가능성을 뜻하지 않습니다.';}
  function effectControls(profile,name) {
    if(!isLaureate(profile))return '';
    return '<div class="laureate-effect-controls"><label><span>일러스트 효과</span><select data-laureate-effect-control aria-label="'+html(name)+' 일러스트 효과"'+(quiet?' disabled':'')+' title="'+html(effectHint())+'">'+[['off','끄기'],['gold','금빛'],['prism','분광']].map(([value,label])=>'<option value="'+value+'"'+(laureateEffect===value?' selected':'')+'>'+label+'</option>').join('')+'</select></label><p class="laureate-effect-help" data-laureate-effect-help>'+html(effectHint())+'</p></div>';
  }
  function syncLaureateEffects(){
    document.querySelectorAll('[data-laureate-card],.laureate-portrait').forEach(node=>node.dataset.laureateEffect=effectiveLaureateEffect());
    document.querySelectorAll('[data-laureate-effect-control]').forEach(select=>{select.value=laureateEffect;select.disabled=quiet;select.title=effectHint();});
    document.querySelectorAll('[data-laureate-effect-help]').forEach(node=>node.textContent=effectHint());
  }
  document.addEventListener('change',event=>{
    const select=event.target.closest('[data-laureate-effect-control]');
    if(!select || quiet || !['off','gold','prism'].includes(select.value))return;
    laureateEffect=select.value;resetCard();syncLaureateEffects();
  });
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
  function portrait(profile,name) {
    const nobel=isLaureate(profile), personal=isPersonalIllustration(profile), path=artPath(profile?.portrait?.path);
    if(!path && !nobel && !personal)return '<div class="portrait-art portrait-unavailable"><strong>초상 미제공</strong><p>이력과 연구 기록을 살펴보세요.</p></div>';
    const generated=profile?.portrait?.generated, background=artPath(profile?.portrait?.background);
    if(personal) {
      const art=profile.portrait, width=Number.isSafeInteger(art.width)&&art.width>0?art.width:600, height=Number.isSafeInteger(art.height)&&art.height>0?art.height:800;
      return '<div class="portrait-art is-illustration personal-illustration" data-asset="'+(path?'loading':'missing')+'" aria-busy="'+Boolean(path)+'"><div class="portrait-status" role="status">'+(path?'일러스트를 불러오는 중입니다.':'일러스트 미제공 · 이력과 근거를 확인해 주세요.')+'</div>'+(path?'<img class="portrait-person" data-personal-image src="'+html(path)+'" alt="'+html(name)+'의 AI 생성 초상 일러스트" loading="lazy" decoding="async" width="'+width+'" height="'+height+'">':'')+'<span class="foil-sheen" aria-hidden="true"></span><span class="foil-glare" aria-hidden="true"></span><span class="portrait-label">AI ILLUSTRATION</span></div>';
    }
    if(nobel) {
      return '<div class="portrait-art laureate-portrait '+(generated?'is-illustration':'is-photo')+'" data-laureate-effect="'+effectiveLaureateEffect()+'" data-asset="'+(path?'loading':'missing')+'" aria-busy="'+Boolean(path)+'"><div class="portrait-status" role="status">'+(path?'일러스트를 불러오는 중입니다.':'일러스트 미제공 · 이력과 근거를 확인해 주세요.')+'</div>'+(path?'<img class="portrait-person" data-laureate-image src="'+html(path)+'" alt="'+html(name)+(generated?'의 AI 생성 초상 일러스트':'의 프로필 사진')+'" loading="lazy" decoding="async" width="600" height="800">':'')+'<span class="foil-sheen" aria-hidden="true"></span><span class="foil-glare" aria-hidden="true"></span>'+(generated?'<span class="portrait-label">AI ILLUSTRATION</span>':'')+'</div>';
    }
    return '<div class="portrait-art '+(generated?'is-illustration':'is-photo')+(background?' has-process-art portrait-'+html(profile.slug):'')+'">'+(background?'<img class="portrait-backdrop" src="'+html(background)+'" alt="" aria-hidden="true" loading="lazy" decoding="async">':'')+'<img class="portrait-person" src="'+html(path)+'" alt="'+html(name)+(generated?'의 AI 생성 초상 일러스트':'의 제공된 프로필 사진')+'" loading="lazy" decoding="async" width="600" height="800"><span class="foil-sheen" aria-hidden="true"></span><span class="foil-glare" aria-hidden="true"></span><span class="portrait-label">'+(generated?'AI ILLUSTRATION':background?'PHOTO + AI ART':'PERSONAL PORTRAIT')+'</span></div>';
  }
  function awardSummary(profile){
    if(!isLaureate(profile))return '';
    const award=profile.award;
    return '<section class="laureate-award" aria-label="확인된 수상 이력"><p class="laureate-award-label"><span aria-hidden="true">✦</span> '+html(award.label_ko||'Nobel Prize')+'</p><p class="laureate-award-domain">'+html(award.year)+' · '+html(award.discipline)+'</p><p>'+html(award.summary)+'</p>'+sourceLink(award.facts_url,'공식 수상 기록')+'<small>수상 이력은 개인 수행·현재 협업 가능성 확인과 구분합니다.</small></section>';
  }
  function portraitSources(profile){
    if(!profile.portrait || (!isLaureate(profile) && profile.portrait.generated!==true))return '';
    const p=profile.portrait,r=p.reference||{};
    const referenceUrl=r.url||p.reference_url||p.photo_url;
    const reference=referenceUrl?'<h4>외형 참고 사진</h4><p>'+sourceLink(referenceUrl,r.title||'참고 사진 출처')+'</p>'+(r.author?'<p>촬영·저작: '+html(r.author)+'</p>':'')+(r.credit?'<p>'+html(r.credit)+'</p>':'')+(r.license?'<p>참고 사진 이용 조건: '+sourceLink(r.license_url,r.license)+'</p>':'')+'<p>참고 사진은 외형 자료이며 이 카드의 표시 이미지는 별도 일러스트입니다.</p>':'';
    return '<details class="portrait-provenance"><summary>일러스트 제작·참고 사진 출처</summary><div><h4>카드에 표시한 생성물</h4><p>'+html(p.generated?'AI 생성 초상 일러스트':p.label||'프로필 이미지')+'</p>'+(p.generated_credit?'<p>'+html(p.generated_credit)+'</p>':'')+(p.generated_license?'<p>생성물 이용 조건: '+sourceLink(p.generated_license_url,p.generated_license)+'</p>':'')+(p.change_note?'<p>변경 이력: '+html(p.change_note)+'</p>':'')+reference+(p.reference_note?'<p>참고 자료 설명: '+html(p.reference_note)+'</p>':'')+'</div></details>';
  }
  function laureateAttributes(profile){return isLaureate(profile)?' data-laureate-card data-laureate-effect="'+effectiveLaureateEffect()+'"':'';}
  function nameBlock(person,heading='h3',className='laureate-name'){
    const p=person.profile||{};
    return '<div class="'+html(className)+'"><'+heading+'>'+html(person.name)+'</'+heading+'>'+(p.display_name&&p.display_name!==person.name?'<span class="researcher-korean">'+html(p.display_name)+'</span>':'')+'<p class="candidate-org">'+html(person.org)+'</p>'+(p.current_role?'<p class="laureate-role">'+html(p.current_role)+(p.affiliation_as_of?' · 공개 프로필 확인 '+html(p.affiliation_as_of):'')+'</p>':'')+'</div>';
  }
  function personalPortraitNote(profile,detailed=false){
    if(!isPersonalIllustration(profile))return '';
    const p=profile.portrait,r=p.reference||{};
    const note='<p class="personal-portrait-note">'+html(profile.portrait_note||'제공된 사진의 외형을 참고한 AI 생성 일러스트입니다.')+'</p>';
    if(!detailed)return note;
    return note+'<details class="personal-portrait-provenance"><summary>일러스트 제작·참고 자료</summary><div><h4>카드에 표시한 생성물</h4><p>AI 생성 초상 일러스트</p>'+(p.generated_credit?'<p>'+html(p.generated_credit)+'</p>':'')+(p.change_note?'<p>변경 이력: '+html(p.change_note)+'</p>':'')+'<h4>외형 참고 사진</h4><p>'+html(r.title||'제공된 프로필 사진')+'</p>'+(r.usage?'<p>'+html(r.usage)+'</p>':'')+'</div></details>';
  }
  function researcherCard(person,index=0,total=1) {
    const p=person.profile||{},work=(person.evidence||[]).find(e=>e.id===p.featured_work)||person.evidence?.[0],nobel=isLaureate(p),personal=isPersonalIllustration(p);
    const career=['self_reported','provided_resume'].includes(p.source_type), action=career?'이력과 경력 보기':'이력과 논문 보기';
    return '<article class="researcher-card holo-card'+(nobel?' laureate-card':'')+'" data-person-id="'+html(person.id)+'" data-tilt'+laureateAttributes(p)+'><div class="researcher-edition"><span>H:문 / RESEARCH ARCHIVE</span><span>'+String(index+1).padStart(2,'0')+' / '+String(total).padStart(2,'0')+'</span></div>'+(nobel?nameBlock(person):nameBlock(person,'h3',personal?'personal-name':'researcher-name'))+portrait(p,person.name)+'<div class="researcher-card-copy">'+(nobel?awardSummary(p)+effectControls(p,person.name):personal?personalPortraitNote(p):'')+'<p class="researcher-tagline">'+html(p.tagline)+'</p><div class="researcher-skills">'+(p.skills||[]).map(x=>'<span>'+html(x)+'</span>').join('')+'</div>'+(work?'<p class="researcher-paper"><span>'+(career?'CAREER / ':'SELECTED WORK / ')+html(work.date)+'</span>'+html(work.title)+'</p>':'')+'<button class="researcher-open" data-action="person" data-id="'+html(person.id)+'" aria-label="'+html(person.name)+' '+action+'"><span>'+(career?'이력과 경력 ':'이력과 논문 ')+person.record_count+(career?'건':'편')+'</span><span>↗</span></button></div></article>';
  }
  function profileDetails(person) {
    const p=person.profile;if(!p?.curated)return '';
    const nobel=isLaureate(p),personal=isPersonalIllustration(p);
    const hero='<div class="researcher-detail-hero holo-card'+(nobel?' laureate-card':'')+'" data-tilt'+laureateAttributes(p)+'>'+portrait(p,person.name)+'</div>';
    const heading=nameBlock(person,'h2',nobel?'laureate-name':personal?'personal-name':'researcher-name');
    return heading+hero+(nobel?awardSummary(p)+effectControls(p,person.name)+portraitSources(p):personal?personalPortraitNote(p,true):portraitSources(p))+'<p class="researcher-bio">'+html(p.biography)+'</p><div class="researcher-skills">'+(p.skills||[]).map(x=>'<span>'+html(x)+'</span>').join('')+'</div>'+(personal?'':'<p class="scope-note">'+html(p.portrait_note||(p.portrait?.generated?'AI 생성 초상 일러스트':p.portrait?.path?'출처에 표시된 프로필 사진':'사진 미제공 · 공개 프로필과 논문 기록을 확인해 주세요.'))+'</p>')+((p.timeline||[]).length?'<h3>이력의 발자취</h3><ol class="researcher-timeline">'+p.timeline.map(t=>'<li><span>'+html(t.date)+'</span><div>'+html(t.text)+' '+sourceLink(t.url,'출처')+'</div></li>').join('')+'</ol>':'')+[['projects','프로젝트 이력'],['education','교육 이력']].map(([key,title])=>p[key]?'<h3>'+title+'</h3><ol class="researcher-timeline">'+p[key].map(x=>'<li><span>'+html(x.date)+'</span><div><strong>'+html(x.title)+'</strong><p>'+html(x.text)+'</p></div></li>').join('')+'</ol>':'').join('')+(p.skill_groups?'<h3>다룰 수 있는 일</h3>'+p.skill_groups.map(g=>'<h4>'+html(g.name)+'</h4><p>'+g.items.map(html).join(' · ')+'</p>').join(''):'')+(p.interests?'<h3>관심 분야</h3><ul>'+p.interests.map(x=>'<li>'+html(x)+'</li>').join('')+'</ul>':'')+'<div class="researcher-sources">'+(p.sources||[]).map(x=>sourceLink(x.url,x.title)).join(' · ')+'</div><p class="scope-note">'+html(p.profile_note||'공개 연구 사례입니다. 사내 구성원이나 협업 가능 인원으로 확인된 것은 아닙니다.')+'</p>';
  }
  window.RndCraft={TileOrbit,deliver,pause,portrait,researcherCard,profileDetails,isLaureate,isPersonalIllustration,personalPortraitNote,awardSummary,effectControls,laureateAttributes,nameBlock,quiet:()=>quiet};
  setQuiet(quiet);
})();
