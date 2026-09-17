/* Shared motion language: paper, stickers, correspondence, and a field of records. */
(() => {
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  let quiet = preference.matches, activeCard = null;
  try { const saved=sessionStorage.getItem('rndplz-motion'); if(saved!==null)quiet=saved==='off'; } catch {}
  const subscribers = new Set();
  function setQuiet(value,remember=false) {
    if(remember)try{sessionStorage.setItem('rndplz-motion',value?'off':'on');}catch{}
    quiet = value; document.body.classList.toggle('no-motion', quiet);
    document.querySelectorAll('[data-motion-toggle]').forEach(b => {
      b.setAttribute('aria-pressed', String(quiet));
      b.innerHTML = '<span class="motion-dot"></span> 움직임 ' + (quiet ? '꺼짐' : '켜짐');
    });
    subscribers.forEach(fn => fn());
  }
  preference.addEventListener('change', e => setQuiet(e.matches));
  document.addEventListener('click', e => {
    if (e.target.closest('[data-motion-toggle]')) setQuiet(!quiet,true);
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
    if (!card) return;
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
      this.frame=0;this.last=0;this.visible=true;this.paused=false;this.hover=null;
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
        if(e.button!==0||this.drag)return;
        this.drag={id:e.pointerId,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,moved:false};
        this.blockClick=false;this.velocity={x:0,y:0};this.hover=null;
        canvas.setPointerCapture(e.pointerId);
        canvas.classList.add('is-dragging');this.kick();
      });
      canvas.addEventListener('pointermove',e=>{
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
    togglePause(){this.paused=!this.paused;this.velocity={x:0,y:0};this.syncControls();this.kick();}
    turn(yaw,pitch){this.yaw+=yaw;this.pitch=Math.max(-1.35,Math.min(1.35,this.pitch+pitch));this.hover=null;this.velocity={x:0,y:0};this.kick();}
    reset(){this.yaw=.35;this.pitch=-.16;this.hover=null;this.velocity={x:0,y:0};this.kick();}
    consumeClick(){const blocked=this.blockClick;this.blockClick=false;return blocked;}
    resize(){
      const b=this.canvas.getBoundingClientRect();this.size=b.width;
      const d=Math.min(devicePixelRatio||1,2);
      this.canvas.width=Math.round(b.width*d);this.canvas.height=Math.round(b.width*d);
      this.ctx.setTransform(d,0,0,d,0,0);this.kick();
    }
    setData(nodes,topic='') {
      if(this.signature===topic+'|'+nodes.map(n=>n.id).join(','))return;
      this.signature=topic+'|'+nodes.map(n=>n.id).join(',');this.started=performance.now();this.hover=null;
      const old=new Map(this.points.map(p=>[p.node.id,p]));
      // Stable positions preserve spatial memory. Filtering changes emphasis, not identity or geometry.
      this.points=nodes.map((node,i)=>{
        const position=TileOrbit.position(i,nodes.length),prior=old.get(node.id),selected=!topic||node.topics.includes(topic);
        const length=Math.hypot(position.x,position.z);
        const u={x:position.z/length,y:0,z:-position.x/length};
        const v={x:position.y*u.z,y:position.z*u.x-position.x*u.z,z:-position.y*u.x};
        const width=.052*Math.min(1.25,1+Math.log2(node.record_count+1)*.06);
        const corners=[[-1,-1],[1,-1],[1,1],[-1,1]].map(([a,b])=>({
          x:position.x+u.x*a*width/2+v.x*b*width*.68,
          y:position.y+u.y*a*width/2+v.y*b*width*.68,
          z:position.z+u.z*a*width/2+v.z*b*width*.68
        }));
        return {node,i,position,corners,selected,emphasis:prior?.emphasis??(selected?1:.08),from:prior?.emphasis??(selected?1:.08)};
      });
      this.kick();
    }
    kick(){if(!this.frame&&this.visible&&!document.hidden)this.frame=requestAnimationFrame(t=>this.draw(t));}
    draw(now) {
      this.frame=0;if(!this.visible||document.hidden||!this.size)return;
      const moving=!quiet&&!this.paused&&!this.drag&&!this.hover;
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
      const progress=quiet?1:Math.min(1,(now-this.started)/650),ease=1-Math.pow(1-progress,3);
      const palette=['#c9aa8a','#33584c','#90abc5','#aa91b9','#d5b557','#e4dcc5','#283e3b'];
      this.rendered=this.points.map(p=>{
        p.emphasis=p.from+((p.selected?1:.08)-p.from)*ease;
        const rotated=TileOrbit.rotate(p.position,this.yaw,this.pitch),screen=TileOrbit.project(rotated,s);
        p.depth=rotated.z;p.drawX=screen.x;p.drawY=screen.y;
        p.screen=p.corners.map(c=>TileOrbit.project(TileOrbit.rotate(c,this.yaw,this.pitch),s));
        return p;
      }).sort((a,b)=>a.depth-b.depth);
      for(const p of this.rendered) {
        const front=p.depth>1/3.6,c=p.screen;
        ctx.globalAlpha=p.emphasis*(front?.6+.4*p.depth:.055+.1*(p.depth+1)/2);
        ctx.fillStyle=p.node.virtual?'#cd503b':palette[p.i%palette.length];
        ctx.beginPath();ctx.moveTo(c[0].x,c[0].y);
        for(let j=1;j<4;j++)ctx.lineTo(c[j].x,c[j].y);ctx.closePath();ctx.fill();
        if(front&&p.emphasis>.2) {
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
      if(moving||progress<1)this.kick();
    }
    hit(event) {
      if(this.drag)return null;
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
  function portrait(profile,name) {
    if(!profile?.portrait)return '';
    const generated=profile.portrait.generated, background=profile.portrait.background;
    return '<div class="portrait-art '+(generated?'is-illustration':'is-photo')+(background?' has-process-art portrait-'+html(profile.slug):'')+'">'+(background?'<img class="portrait-backdrop" src="'+html(background)+'" alt="" aria-hidden="true" loading="lazy">':'')+'<img class="portrait-person" src="'+html(profile.portrait.path)+'" alt="'+html(name)+(generated?'의 AI 생성 초상 일러스트':'의 제공된 프로필 사진')+'" loading="lazy" width="600" height="800"><span class="foil-sheen" aria-hidden="true"></span><span class="foil-glare" aria-hidden="true"></span><span class="portrait-label">'+(generated?'AI ILLUSTRATION':background?'PHOTO + AI ART':'PERSONAL PORTRAIT')+'</span></div>';
  }
  function researcherCard(person,index=0,total=1) {
    const p=person.profile,work=person.evidence.find(e=>e.id===p.featured_work)||person.evidence[0];
    const career=['self_reported','provided_resume'].includes(p.source_type), action=career?'이력과 경력 보기':'이력과 논문 보기';
    return '<article class="researcher-card holo-card" data-tilt><div class="researcher-edition"><span>H:문 / RESEARCH ARCHIVE</span><span>'+String(index+1).padStart(2,'0')+' / '+String(total).padStart(2,'0')+'</span></div>'+portrait(p,person.name)+'<div class="researcher-card-copy"><span class="researcher-korean">'+html(p.display_name)+'</span><h3>'+html(person.name)+'</h3><p class="researcher-tagline">'+html(p.tagline)+'</p><div class="researcher-skills">'+p.skills.map(x=>'<span>'+html(x)+'</span>').join('')+'</div><p class="researcher-paper"><span>'+(career?'CAREER / ':'SELECTED WORK / ')+html(work.date)+'</span>'+html(work.title)+'</p><button class="researcher-open" data-action="person" data-id="'+html(person.id)+'" aria-label="'+html(person.name)+' '+action+'"><span>'+(career?'이력과 경력 ':'이력과 논문 ')+person.record_count+(career?'건':'편')+'</span><span>↗</span></button></div></article>';
  }
  function profileDetails(person) {
    const p=person.profile;if(!p?.curated)return '';
    const sourceLink=(url,label)=>/^https?:\/\//.test(url)?'<a href="'+html(url)+'" target="_blank" rel="noopener noreferrer">'+html(label)+' ↗</a>':(label==='출처'?'':'<span>'+html(label)+'</span>');
    return '<div class="researcher-detail-hero holo-card" data-tilt>'+portrait(p,person.name)+'</div><span class="researcher-korean">'+html(p.display_name)+'</span><h2>'+html(person.name)+'</h2><p>'+html(person.org)+'</p><p class="researcher-bio">'+html(p.biography)+'</p><div class="researcher-skills">'+p.skills.map(x=>'<span>'+html(x)+'</span>').join('')+'</div><p class="scope-note">'+html(p.portrait_note||'AI 일러스트 · 공식 사진 외형을 참고한 생성 초상. 공개 자료 확인: 2026-09-17')+'</p><h3>이력의 발자취</h3><ol class="researcher-timeline">'+p.timeline.map(t=>'<li><span>'+html(t.date)+'</span><div>'+html(t.text)+' '+sourceLink(t.url,'출처')+'</div></li>').join('')+'</ol>'+[['projects','프로젝트 이력'],['education','교육 이력']].map(([key,title])=>p[key]?'<h3>'+title+'</h3><ol class="researcher-timeline">'+p[key].map(x=>'<li><span>'+html(x.date)+'</span><div><strong>'+html(x.title)+'</strong><p>'+html(x.text)+'</p></div></li>').join('')+'</ol>':'').join('')+ (p.skill_groups?'<h3>다룰 수 있는 일</h3>'+p.skill_groups.map(g=>'<h4>'+html(g.name)+'</h4><p>'+g.items.map(html).join(' · ')+'</p>').join(''):'')+(p.interests?'<h3>관심 분야</h3><ul>'+p.interests.map(x=>'<li>'+html(x)+'</li>').join('')+'</ul>':'')+'<div class="researcher-sources">'+p.sources.map(x=>sourceLink(x.url,x.title)).join(' · ')+'</div><p class="scope-note">'+html(p.profile_note||'공개 연구 사례입니다. 사내 구성원이나 협업 가능 인원으로 확인된 것은 아닙니다.')+'</p>';
  }
  window.RndCraft={TileOrbit,deliver,pause,portrait,researcherCard,profileDetails,quiet:()=>quiet};
  setQuiet(quiet);
})();
