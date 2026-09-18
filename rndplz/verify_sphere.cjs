/* Focused geometry and gesture regressions; no browser or service state required. */
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const sourcePath=process.env.RNDPLZ_SPHERE_SOURCE||join(__dirname,'web/craft.js');

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
  vm.runInNewContext(readFileSync(sourcePath,'utf8'),context);
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
test('topic filters rebuild selectable tiles, clear stale state, and handle empty/all/single views',()=>{
  const {sphere,nodes,frame,pointer,captures,callbacks}=fixture();frame();
  const oldFront=sphere.rendered.at(-1),oldEvent={clientX:oldFront.drawX,clientY:oldFront.drawY};
  pointer('pointermove',oldEvent.clientX,oldEvent.clientY);
  assert.ok(sphere.hover);assert.equal(sphere.canvas.style.cursor,'pointer');
  const expected=new Set(nodes.filter(n=>n.topics.includes('materials')).map(n=>n.id));
  assert.equal(expected.size,139);
  sphere.setData(nodes,'materials');
  // No animation frame has run: the previous geometry must already be unpickable.
  assert.equal(sphere.rendered.length,0,'old rendered tiles remain before the next frame');
  assert.equal(sphere.hit(oldEvent),null,'previous frame remains clickable after topic change');
  assert.equal(sphere.hover,null);assert.equal(sphere.canvas.style.cursor,'grab');
  assert.equal(sphere.points.length,139);
  assert.deepEqual(new Set(sphere.points.map(p=>p.node.id)),expected);
  frame(2000);
  assert.equal(sphere.rendered.length,139);
  assert.deepEqual(new Set(sphere.rendered.map(p=>p.node.id)),expected);
  assert.ok(sphere.rendered.every(p=>p.selected));
  let hits=0;
  for(const tile of sphere.rendered){
    const hit=sphere.hit({clientX:tile.drawX,clientY:tile.drawY});
    if(hit){hits++;assert.ok(expected.has(hit.node.id),'a filtered-out person is selectable');}
  }
  assert.ok(hits>0,'filtered people must still be selectable');
  // Repeating the same data must not discard visible tiles or interrupt hover.
  const front=sphere.rendered.at(-1),filteredEvent={clientX:front.drawX,clientY:front.drawY};
  pointer('pointermove',filteredEvent.clientX,filteredEvent.clientY);
  const points=sphere.points,rendered=sphere.rendered,hover=sphere.hover,scheduled=callbacks.size;
  sphere.setData(nodes,'materials');
  assert.equal(sphere.points,points);assert.equal(sphere.rendered,rendered);
  assert.equal(sphere.hover,hover);assert.equal(callbacks.size,scheduled);
  // Changing filter during a drag releases the obsolete gesture and its inertia.
  pointer('pointerdown',150,180);pointer('pointermove',260,205);
  assert.equal(captures.size,1);assert.ok(sphere.drag);assert.ok(sphere.velocity.x!==0);
  sphere.setData(nodes,'no-matching-topic');
  assert.equal(sphere.points.length,0);assert.equal(sphere.rendered.length,0);
  assert.equal(sphere.hit(filteredEvent),null);assert.equal(sphere.hover,null);
  assert.equal(sphere.canvas.style.cursor,'grab');assert.equal(sphere.drag,null);
  assert.equal(captures.size,0);assert.equal(sphere.velocity.x,0);assert.equal(sphere.velocity.y,0);
  frame(3000);
  assert.equal(sphere.rendered.length,0);assert.equal(sphere.hit(filteredEvent),null);
  assert.equal(callbacks.size,0,'an empty view must not auto-rotate');
  sphere.setData(nodes);assert.equal(sphere.rendered.length,0);frame(4000);
  assert.equal(sphere.points.length,1045);assert.equal(sphere.rendered.length,1045);
  assert.deepEqual(new Set(sphere.rendered.map(p=>p.node.id)),new Set(nodes.map(n=>n.id)));
  // One person must start facing the viewer even after the previous globe was rotated.
  const only=nodes.at(-1);only.topics=['single-person'];sphere.turn(Math.PI,1.1);
  sphere.setData(nodes,'single-person');
  assert.equal(sphere.points.length,1);assert.equal(sphere.rendered.length,0);
  frame(5000);
  assert.equal(sphere.rendered.length,1);
  const single=sphere.rendered[0];assert.equal(single.node.id,only.id);assert.ok(single.depth>.9);
  assert.ok(single.drawX>0&&single.drawX<sphere.size&&single.drawY>0&&single.drawY<sphere.size);
  assert.equal(sphere.hit({clientX:single.drawX,clientY:single.drawY}).node.id,only.id);
  assert.equal(callbacks.size,0,'a single person must not rotate away automatically');
  const initial=[single.drawX,single.drawY,single.depth];frame(7000);
  assert.deepEqual([single.drawX,single.drawY,single.depth],initial);
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
