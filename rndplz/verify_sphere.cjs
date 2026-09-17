/* Focused geometry and gesture regressions; no browser or service state required. */
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const {test}=require('node:test');

function fixture(reduced=false) {
  const listeners=new Map(),callbacks=new Map();let next=0,clock=0;
  const noop=()=>{},gradient={addColorStop:noop};
  const ctx=new Proxy({}, {get:(_,key)=>key==='createRadialGradient'?()=>gradient:noop,set:()=>true});
  const captures=new Set();
  const canvas={getContext:()=>ctx,closest:()=>null,getBoundingClientRect:()=>({width:525,left:0,top:0}),
    classList:{add:noop,remove:noop},style:{},addEventListener:(name,fn)=>listeners.set(name,fn),
    setPointerCapture:id=>captures.add(id),hasPointerCapture:id=>captures.has(id),releasePointerCapture:id=>captures.delete(id)};
  const document={hidden:false,addEventListener:noop,querySelectorAll:()=>[],body:{classList:{toggle:noop}}};
  const context={window:{},document,console,matchMedia:()=>({matches:reduced,addEventListener:noop}),
    sessionStorage:{getItem:()=>null},performance:{now:()=>clock},devicePixelRatio:1,
    IntersectionObserver:class{observe(){}},ResizeObserver:class{observe(){}},
    requestAnimationFrame:fn=>{callbacks.set(++next,fn);return next;}};
  vm.runInNewContext(readFileSync(join(__dirname,'web/craft.js'),'utf8'),context);
  const Sphere=context.window.RndCraft.TileOrbit,sphere=new Sphere(canvas);
  const nodes=Array.from({length:1045},(_,i)=>({id:'p'+i,name:'Person '+i,record_count:1,topics:i<139?['materials']:[],virtual:i<7}));
  sphere.setData(nodes);
  function frame(at=1000){clock=at;const pending=[...callbacks.values()];callbacks.clear();pending.forEach(fn=>fn(at));}
  function pointer(type,x,y){listeners.get(type)({type,pointerId:1,button:0,clientX:x,clientY:y});}
  return {Sphere,sphere,nodes,frame,pointer,document,callbacks,captures,listeners};
}

test('all 1,045 identities live on a sphere, spanning front and back without a centre hole',()=>{
  const {sphere,nodes,frame}=fixture();frame();
  assert.equal(new Set(sphere.points.map(p=>p.node.id)).size,nodes.length);
  for(const p of sphere.points)assert.ok(Math.abs(Math.hypot(p.position.x,p.position.y,p.position.z)-1)<1e-12);
  assert.ok(sphere.rendered[0].depth<-.99);assert.ok(sphere.rendered.at(-1).depth>.99);
  assert.ok(sphere.rendered.some(p=>p.depth>.9&&Math.hypot(p.drawX-262.5,p.drawY-241.5)<20));
});
test('rotation carries a front tile to the back, and perspective makes nearby tiles larger',()=>{
  const {Sphere}=fixture();
  const back=Sphere.rotate({x:0,y:0,z:1},Math.PI,0);
  assert.ok(Math.abs(back.z+1)<1e-12);
  assert.ok(Sphere.project({x:0,y:0,z:1},525).scale>Sphere.project(back,525).scale);
  assert.ok(Math.abs(Math.hypot(...Object.values(Sphere.rotate({x:0,y:0,z:1},.8,.4)))-1)<1e-12);
});
test('picking uses projected paper bounds and front-most depth; back faces cannot be selected',()=>{
  const {sphere,frame}=fixture();frame();
  const front=sphere.rendered.at(-1);
  assert.equal(sphere.hit({clientX:front.drawX,clientY:front.drawY}).node.id,front.node.id);
  assert.equal(sphere.hit({clientX:0,clientY:0}),null);
  const square=[{x:5,y:5},{x:15,y:5},{x:15,y:15},{x:5,y:15}];
  sphere.rendered=[{selected:true,depth:-.8,screen:square},{selected:true,depth:.5,screen:square,node:{id:'near'}}];
  assert.equal(sphere.hit({clientX:10,clientY:10}).node.id,'near');
  sphere.rendered.pop();assert.equal(sphere.hit({clientX:10,clientY:10}),null);
});
test('topic selection preserves all IDs and coordinates, and only 139 people remain selectable',()=>{
  const {sphere,nodes,frame}=fixture();frame();
  const before=sphere.points.map(p=>JSON.stringify(p.position));
  sphere.setData(nodes,'materials');frame(2000);
  assert.equal(sphere.points.length,1045);assert.equal(sphere.points.filter(p=>p.selected).length,139);
  sphere.points.forEach((p,i)=>assert.equal(JSON.stringify(p.position),before[i]));
  const target=sphere.rendered.filter(p=>!p.selected&&p.depth>.8)[0];
  const hit=sphere.hit({clientX:target.drawX,clientY:target.drawY});assert.ok(!hit||hit.selected);
});
test('drag rotates the geometry and suppresses its click, while a later tap can select',()=>{
  const {sphere,frame,pointer,captures}=fixture();frame();const yaw=sphere.yaw;
  pointer('pointerdown',150,180);pointer('pointermove',260,205);pointer('pointerup',260,205);
  assert.ok(sphere.yaw>yaw);assert.equal(captures.size,0);
  assert.equal(sphere.consumeClick(),true);assert.equal(sphere.consumeClick(),false);
  pointer('pointerdown',230,230);pointer('pointerup',230,230);assert.equal(sphere.consumeClick(),false);
});
test('cancelled gestures release capture and cannot accidentally open a profile',()=>{
  const {sphere,pointer,captures}=fixture();
  pointer('pointerdown',150,180);pointer('pointercancel',150,180);
  assert.equal(sphere.drag,null);assert.equal(captures.size,0);assert.equal(sphere.consumeClick(),true);
});
test('reduced motion stops automatic frames but allows explicit arrow-key rotation',()=>{
  const {sphere,frame,callbacks,listeners}=fixture(true);frame();const yaw=sphere.yaw;
  assert.equal(callbacks.size,0);
  listeners.get('keydown')({key:'ArrowRight',preventDefault(){}});frame(1100);
  assert.ok(sphere.yaw>yaw);assert.equal(callbacks.size,0);
});
test('pause stops frame scheduling and background tabs do not draw',()=>{
  const {sphere,frame,callbacks,document}=fixture();frame();sphere.togglePause();frame(2000);
  assert.equal(callbacks.size,0);const yaw=sphere.yaw;
  document.hidden=true;sphere.togglePause();frame(3000);
  assert.equal(sphere.yaw,yaw);assert.equal(callbacks.size,0);
});
