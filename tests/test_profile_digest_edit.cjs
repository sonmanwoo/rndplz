'use strict';
// 실제 자료 제안 함수를 최소 DOM에서 실행한다. 브라우저·서버·외부 의존성은 사용하지 않는다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../rndplz/web/profile.js'), 'utf8');
const helpers = source.slice(source.indexOf('  function node('), source.indexOf('  function announce('));
const start = source.indexOf('  // ---- A document the company AI read:');
const end = source.indexOf('  function applyDigest()', start);
assert(start >= 0 && end > start, '실제 자료 제안 함수 구간을 찾는다');
const digestSource = source.slice(start, end);

class Style {
  setProperty(name, value) { this[name] = String(value); }
  getPropertyValue(name) { return this[name] || ''; }
  removeProperty(name) { const old = this[name] || ''; delete this[name]; return old; }
}

function simpleMatch(el, selector) {
  if (!(el instanceof Element)) return false;
  selector = selector.trim();
  const not = selector.match(/:not\(([^)]+)\)/);
  if (not) { if (simpleMatch(el, not[1])) return false; selector = selector.replace(not[0], ''); }
  for (const match of selector.matchAll(/\[([^\]=]+)(?:=["']?([^\]"']*)["']?)?\]/g)) {
    const actual = el.getAttribute(match[1]);
    if (actual === null || (match[2] !== undefined && actual !== match[2])) return false;
  }
  selector = selector.replace(/\[[^\]]+\]/g, '');
  const tag = selector.match(/^[a-z][\w-]*/i);
  if (tag && el.tagName !== tag[0].toUpperCase()) return false;
  for (const match of selector.matchAll(/\.([\w-]+)/g)) if (!el.classList.contains(match[1])) return false;
  const id = selector.match(/#([\w-]+)/);
  return !id || el.id === id[1];
}

function selectorMatch(el, selector) {
  // 이 구간에 쓰이는 태그·클래스·data 속성·후손/직계 선택자만 구현한다.
  const parts = selector.trim().split(/\s+(?![^\[]*\])/);
  let at = el;
  if (!simpleMatch(at, parts.pop())) return false;
  while (parts.length) {
    const part = parts.pop();
    if (part === '>') {
      at = at.parentElement;
      if (!at || !simpleMatch(at, parts.pop())) return false;
    } else {
      at = at.parentElement;
      while (at && !simpleMatch(at, part)) at = at.parentElement;
      if (!at) return false;
    }
  }
  return true;
}

class Element {
  constructor(tag, document) {
    this.tagName = tag.toUpperCase(); this.ownerDocument = document;
    this.children = []; this.parentElement = null; this.dataset = {};
    this.attributes = new Map(); this.listeners = new Map(); this.style = new Style();
    this.className = ''; this._text = ''; this.hidden = false; this.value = '';
    const values = () => this.className.split(/\s+/).filter(Boolean);
    this.classList = {
      contains: value => values().includes(value),
      add: (...items) => { this.className = [...new Set([...values(), ...items])].join(' '); },
      remove: (...items) => { this.className = values().filter(value => !items.includes(value)).join(' '); },
      toggle: (value, force) => {
        const on = force === undefined ? !values().includes(value) : !!force;
        this.classList[on ? 'add' : 'remove'](value); return on;
      }
    };
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.replaceChildren(); this._text = String(value); }
  get childNodes() { return this.children; }
  get firstChild() { return this.children[0] || null; }
  get firstElementChild() { return this.firstChild; }
  get parentNode() { return this.parentElement; }
  get isConnected() { return this === this.ownerDocument.body || !!this.parentElement?.isConnected; }
  get offsetHeight() { return this.getBoundingClientRect().height; }
  get offsetWidth() { return this.getBoundingClientRect().width; }
  get clientWidth() { return this.offsetWidth; }
  get scrollHeight() { return this.offsetHeight; }
  append(...children) {
    for (let child of children) {
      if (typeof child === 'string') { const text = new Element('text', this.ownerDocument); text._text = child; child = text; }
      child.remove(); child.parentElement = this; this.children.push(child);
    }
  }
  prepend(...children) { const old = [...this.children]; this.replaceChildren(...children, ...old); }
  replaceChildren(...children) { for (const child of this.children) child.parentElement = null; this.children = []; this._text = ''; this.append(...children); }
  replaceWith(...children) {
    const parent = this.parentElement;
    if (!parent) return;
    const index = parent.children.indexOf(this);
    for (const child of children) { child.remove(); child.parentElement = parent; }
    parent.children.splice(index, 1, ...children); this.parentElement = null;
  }
  remove() { if (this.parentElement) { const parent = this.parentElement; parent.children.splice(parent.children.indexOf(this), 1); this.parentElement = null; } }
  setAttribute(name, value) {
    value = String(value);
    if (name === 'class') this.className = value;
    else if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    else this.attributes.set(name, value);
  }
  getAttribute(name) {
    if (name === 'class') return this.className;
    if (name.startsWith('data-')) return this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] ?? null;
    return this.attributes.get(name) ?? null;
  }
  removeAttribute(name) { this.attributes.delete(name); }
  hasAttribute(name) { return this.getAttribute(name) !== null; }
  matches(selector) { return selector.split(',').some(part => selectorMatch(this, part)); }
  closest(selector) { for (let el = this; el; el = el.parentElement) if (el.matches(selector)) return el; return null; }
  contains(other) { for (let el = other; el; el = el.parentElement) if (el === this) return true; return false; }
  querySelectorAll(selector) {
    const found = [];
    const visit = el => { for (const child of el.children) { if (child.matches(selector)) found.push(child); visit(child); } };
    visit(this); return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, listener) { const list = this.listeners.get(type) || []; list.push(listener); this.listeners.set(type, list); }
  removeEventListener(type, listener) { this.listeners.set(type, (this.listeners.get(type) || []).filter(fn => fn !== listener)); }
  dispatchEvent(event) {
    event.target ||= this; event.currentTarget = this;
    event.preventDefault ||= function () { this.defaultPrevented = true; };
    event.stopPropagation ||= function () { this.propagationStopped = true; };
    for (const fn of [...(this.listeners.get(event.type) || [])]) fn(event);
    if (event.bubbles !== false && !event.propagationStopped && this.parentElement) this.parentElement.dispatchEvent(event);
    return !event.defaultPrevented;
  }
  click() { this.dispatchEvent({type: 'click'}); }
  focus(options) { if (this.isConnected) { this.ownerDocument.activeElement = this; this.ownerDocument.focuses.push({element: this, options}); } }
  scrollIntoView(options) { this.ownerDocument.scrolls.push({element: this, options}); }
  getBoundingClientRect() {
    // 고정 기하 fixture다. 실제 CSS 배치·높이·애니메이션 품질은 검증하지 않는다.
    const inherited = this.closest('.digest-row')?.rect;
    const rect = this.rect || inherited || {top: 100, bottom: 360, left: 0, right: this.ownerDocument.width};
    return {...rect, width: rect.width ?? rect.right - rect.left, height: rect.height ?? rect.bottom - rect.top};
  }
}

function fixture({reduced = false, width = 700} = {}) {
  const document = {width, activeElement: null, focuses: [], scrolls: [], createElement: tag => new Element(tag, document)};
  document.body = document.createElement('body');
  const host = document.createElement('div'); host.id = 'digestView'; document.body.append(host);
  document.getElementById = id => id === 'digestView' ? host : null;
  document.querySelector = selector => document.body.querySelector(selector);
  document.querySelectorAll = selector => document.body.querySelectorAll(selector);
  const draft = {fields: {name:'기존 이름',organization:'기존 소속',department:'기존 부서',role:'기존 직위',aliases:['Old Name'],tagline:'기존 한 줄 소개',bio: '현재 소개\n둘째 줄', skills: '증류, 추출', interests: '촉매'}, careers: [
    {title: '탈색 공정 개발', period: '2023.01 — 현재'}, {title: '두 번째 경력'}, {title: '세 번째 경력'}
  ]};
  const digest = {name: '시험 자료',source_id:'source-fixture', editing: null, skip: new Set(), proposal: {
    name:'제안 이름',organization:'제안 소속',department:'제안 부서',role:'제안 직위',aliases:['New Name'],tagline:'제안 한 줄 소개',
    bio_addition: '새 소개', skills: ['공정 모델링', '실험 설계'], interests: ['막 분리'],
    careers: [{title: '새 프로젝트', organization: '조직', period: '2026', role: '설계', description: '한 일과 적용 조건'},
      {title: '다음 프로젝트', organization: '', period: '', role: '', description: ''}]
  }};
  const timers = new Map(); let timerId = 0;
  const setTimeout = (fn, ms = 0) => { const id = ++timerId; timers.set(id, {fn, ms}); return id; };
  const clearTimeout = id => timers.delete(id);
  const matchMedia = query => ({matches: query.includes('prefers-reduced-motion') && reduced});
  const getComputedStyle = el => ({getPropertyValue: name => el.style.getPropertyValue(name) || (name === '--digest-gap' ? (width <= 700 ? '6px' : '10px') : ''), columnGap: width <= 700 ? '6px' : '10px'});
  const window = {innerHeight: 800, innerWidth: width, matchMedia, getComputedStyle, visualViewport: {height: 800, offsetTop: 0}};
  const context = vm.createContext({document, window, matchMedia, getComputedStyle, setTimeout, clearTimeout,
    requestAnimationFrame: fn => setTimeout(fn, 16), cancelAnimationFrame: clearTimeout,
    draft, digest, digestTicket: 0, busy: false, uncertain: null,
    view: {limits: {fields: {bio: 2000}, career_fields: {title: 160, organization: 160, period: 80, role: 160, description: 2000}}},
    $: id => document.getElementById(id), cardMode: () => false, applyDigest: () => {}, sourceNote: () => {},
    careerLabels: {title: '경력·프로젝트명', organization: '소속·조직', period: '기간', role: '맡은 역할', description: '한 일과 적용 조건'}
  });
  vm.runInContext(helpers + digestSource, context, {filename: 'profile.js (자료 제안 실제 함수)'});
  Object.assign(context, vm.runInContext('({digestRowKey,digestCurrentSummary})', context));
  context.renderDigest();
  const flush = () => {
    let steps = 0;
    while (timers.size) {
      assert(++steps < 100, '전환 타이머는 유한하게 끝난다');
      const [id, timer] = timers.entries().next().value;
      timers.delete(id); timer.fn();
    }
  };
  const row = key => host.querySelector(`[data-digest-row="${key}"]`);
  const item = id => host.querySelector(`[data-proposal-id="${id}"]`);
  const pen = id => item(id)?.querySelector('.digest-edit');
  const editor = () => host.querySelector('.digest-editor');
  const action = text => editor().querySelectorAll('button').find(button => button.textContent === text);
  return {context, document, host, draft, digest, timers, flush, row, item, pen, editor, action};
}

function assertFocus(f, expected, message) {
  assert.equal(f.document.activeElement, expected, message);
  assert.equal(f.document.focuses.at(-1)?.options?.preventScroll, true, '초점 이동은 자동 스크롤을 억제한다');
}

const cases = [['name','name'],['organization','organization'],['department','department'],['role','role'],['tagline','tagline'],['aliases:0','aliases'],['bio', 'bio'], ['skills:0', 'skills'], ['interests:0', 'interests'], ['career:0', 'careers']];
let transitions = 0;
for (const width of [390, 1200]) for (const [id, key] of cases) for (const ending of ['완료', '취소', '닫기', 'Escape']) {
  const f = fixture({width});
  const rows = f.host.querySelectorAll('.digest-row');
  const untouched = rows.filter(row => row.dataset.digestRow !== key).map(row => [row, row.firstChild, row.textContent]);
  const originalRow = f.row(key);
  f.pen(id).click();
  assert.equal(f.digest.editing, id);
  assert.equal(f.row(key), originalRow, '편집 행 DOM을 유지해 가로 전환을 이어간다');
  assert.deepEqual(f.host.querySelectorAll('.digest-row.is-editing').map(row => row.dataset.digestRow), [key], '편집하는 한 줄만 넓어진다');
  const current = originalRow.querySelector('.is-current');
  assert.equal(current.inert, true, '접힌 현재값은 키보드 초점에서 제외한다');
  assert.equal(current.getAttribute('aria-hidden'), 'true', '편집 중 비교 기준은 요약으로만 읽는다');
  for (const [row, first, text] of untouched) {
    assert(row.isConnected, '다른 행은 교체하지 않는다');
    assert.equal(row.firstChild, first, '다른 행 내용 DOM도 유지한다');
    assert.equal(row.textContent, text);
  }
  const editor = f.editor();
  const input = editor.querySelector('input,textarea');
  assertFocus(f, input, '편집 시작 즉시 첫 입력칸에 초점을 둔다');
  const summary = editor.querySelector('.digest-current-summary');
  assert(summary && summary.textContent.startsWith('지금 카드: '), '편집기에 현재값 요약을 표시한다');
  assert.equal(summary.querySelector('button,a'), null, '요약은 펼치기 동작 없는 텍스트다');
  input.value = '고친 내용';
  if (ending === '완료') f.action('고치기 완료').click();
  else if (ending === '취소') f.action('취소').click();
  else if (ending === '닫기') editor.querySelector('[aria-label="고치기 취소"]').click();
  else { const event = {type: 'keydown', key: 'Escape'}; input.dispatchEvent(event); assert(event.defaultPrevented); }
  assert.equal(f.digest.editing, null);
  assert.equal(f.host.querySelectorAll('.digest-row.is-editing').length, 0, '종료하면 좌우 비교로 돌아간다');
  assert.equal(f.row(key), originalRow, '종료 전환에도 행 DOM을 유지한다');
  assert.equal(current.inert, false, '종료하면 현재값의 비활성 상태를 해제한다');
  assert.equal(current.getAttribute('aria-hidden'), 'false');
  assertFocus(f, f.pen(id), '종료 후 같은 항목의 연필로 초점을 돌린다');
  const value = key === 'bio' ? f.digest.proposal.bio_addition : key === 'careers' ? f.digest.proposal.careers[0].title : Array.isArray(f.digest.proposal[key])?f.digest.proposal[key][0]:f.digest.proposal[key];
  assert.equal(value === '고친 내용', ending === '완료', '완료만 편집 내용을 반영한다');
  f.flush();
  assert(!originalRow.classList.contains('is-transitioning'), '타이머로 전환 중 상태를 정리한다');
  assert.equal(originalRow.style.getPropertyValue('--digest-transition-height'), '');
  assert.equal(originalRow.style.getPropertyValue('--digest-current-width'), '');
  assert.equal(f.document.activeElement, f.pen(id), '전환 정리 이후에도 종료 초점이 유지된다');
  assert.equal(f.document.scrolls.length, 0, '화면 안에서 편집할 때 스크롤하지 않는다');
  transitions++;
}

// 전환 종료 이벤트는 해당 grid 열에서 발생한 경우에만 임시 높이·너비를 정리한다.
{
  const f = fixture();
  const row = f.row('careers'), cols = row.querySelector('.digest-cols');
  f.pen('career:0').click();
  assert(row.classList.contains('is-transitioning'));
  assert(row.style.getPropertyValue('--digest-transition-height').endsWith('px'), '가로 전환 동안 행 높이를 고정한다');
  assert(row.style.getPropertyValue('--digest-current-width').endsWith('px'), '접히는 현재값은 비교 칸 너비를 유지한다');
  assert.equal(f.timers.size, 1, '종료 이벤트가 오지 않을 때 정리할 타이머를 둔다');
  row.querySelector('.digest-current-body').dispatchEvent({type: 'transitionend', propertyName: 'grid-template-columns'});
  assert(row.classList.contains('is-transitioning'), '자식의 전환 종료는 행 전환을 끝내지 않는다');
  cols.dispatchEvent({type: 'transitionend', propertyName: 'column-gap'});
  assert(row.classList.contains('is-transitioning'), '다른 속성의 전환 종료는 행 전환을 끝내지 않는다');
  cols.dispatchEvent({type: 'transitionend', propertyName: 'grid-template-columns'});
  assert(!row.classList.contains('is-transitioning'));
  assert.equal(row.style.getPropertyValue('--digest-transition-height'), '');
  assert.equal(row.style.getPropertyValue('--digest-current-width'), '');
  assert.equal(f.timers.size, 0, '정상 종료 이벤트 뒤 타이머를 취소한다');
  assert(row.classList.contains('is-editing'), '임시 상태 정리 후 편집 상태를 유지한다');
  assertFocus(f, f.editor().querySelector('input'), '전환 종료는 입력 초점을 옮기지 않는다');
  f.action('취소').click();
  assert(row.classList.contains('is-transitioning'), '돌아오는 전환도 실행한다');
  f.flush();
  assert(!row.classList.contains('is-transitioning'));
  assert.equal(row.style.getPropertyValue('--digest-transition-height'), '');
  assert.equal(row.style.getPropertyValue('--digest-current-width'), '');
}

// 선택/해제와 편집 결과의 포함 규칙을 함께 확인한다.
for (const [id] of cases) {
  const f = fixture();
  const proposal = () => f.item(id).querySelector('.digest-add');
  assert.equal(proposal().getAttribute('aria-pressed'), 'true');
  proposal().click(); assert(f.digest.skip.has(id));
  assert.equal(proposal().getAttribute('aria-pressed'), 'false');
  proposal().click(); assert(!f.digest.skip.has(id));
  proposal().click();
  f.pen(id).click(); f.action('취소').click();
  assert(f.digest.skip.has(id), '취소는 원래 제외 상태를 유지한다');
  f.pen(id).click(); f.action('고치기 완료').click();
  assert(!f.digest.skip.has(id), '편집 완료한 항목은 넣는 쪽으로 바뀐다');
  assert.equal(proposal().getAttribute('aria-pressed'), 'true');
  f.flush();
}

{
  const f = fixture();
  f.pen('skills:0').click();
  const input = f.editor().querySelector('input'); input.value = 'Enter로 고침';
  const enter = {type: 'keydown', key: 'Enter'}; input.dispatchEvent(enter);
  assert(enter.defaultPrevented); assert.equal(f.digest.proposal.skills[0], 'Enter로 고침');
  assertFocus(f, f.pen('skills:0'), '한 줄 입력의 Enter는 완료 후 초점을 복원한다');
  f.pen('bio').click();
  const textarea = f.editor().querySelector('textarea');
  const newline = {type: 'keydown', key: 'Enter'}; textarea.dispatchEvent(newline);
  assert(!newline.defaultPrevented); assert.equal(f.digest.editing, 'bio', '여러 줄 입력의 Enter는 편집을 끝내지 않는다');
  f.action('취소').click(); f.flush();
}

{
  const f = fixture();
  assert.equal(f.context.digestRowKey('career:1'), 'careers');
  assert.equal(f.context.digestCurrentSummary('careers'), '지금 카드: 2023.01 — 현재 · 탈색 공정 개발 외 2건');
  assert.equal(f.context.digestCurrentSummary('bio'), '지금 카드: 현재 소개 둘째 줄', '현재 소개의 줄바꿈은 한 줄로 정리한다');
  for (const key of ['name','organization','department','role','tagline','aliases','bio', 'skills', 'interests']) f.draft.fields[key] = '';
  f.draft.careers = [];
  for (const [id, key] of cases) {
    f.pen(id).click();
    assert.equal(f.editor().querySelector('.digest-current-summary').textContent, '지금 카드: 비어 있어요');
    f.action('취소').click();
  }
  f.flush();
}

// 화면 밖 행에만 nearest 보정을 요청한다. 긴 행의 일부가 보이는 경우는 강제로 맞추지 않는다.
for (const rect of [{top: 900, bottom: 1160}, {top: -400, bottom: -100}, {top: -100, bottom: 1000}]) {
  const f = fixture(); f.row('careers').rect = {...rect, left: 0, right: 700};
  f.pen('career:0').click();
  const outside = rect.top >= 800 || rect.bottom <= 0;
  assert.equal(f.document.scrolls.length > 0, outside, '행의 화면 이탈 여부에 따라 스크롤한다');
  for (const scroll of f.document.scrolls) assert.equal(scroll.options.block, 'nearest');
  f.action('취소').click(); f.flush();
}

// 빠른 편집 전환과 전체 닫기 뒤에 이전 타이머가 초점·행 상태를 되돌리지 않는다.
{
  const f = fixture();
  f.pen('career:0').click();
  f.pen('career:1').click();
  assert.equal(f.digest.editing, 'career:1');
  f.pen('skills:0').click();
  const input = f.editor().querySelector('input');
  f.flush();
  assert.deepEqual(f.host.querySelectorAll('.digest-row.is-editing').map(row => row.dataset.digestRow), ['skills']);
  assert.equal(f.document.activeElement, input, '이전 행 정리가 새 편집 초점을 빼앗지 않는다');
  f.context.closeDigest();
  const focusCount = f.document.focuses.length;
  f.flush();
  assert.equal(f.host.hidden, true);
  assert.equal(f.host.children.length, 0);
  assert.equal(f.document.focuses.length, focusCount, '닫힌 제안의 대기 콜백은 초점을 변경하지 않는다');
}

{
  const f = fixture({reduced: true});
  f.pen('career:0').click();
  assert(f.row('careers').classList.contains('is-editing'));
  assert(!f.row('careers').classList.contains('is-transitioning'), '움직임 축소에서는 처음부터 전환 클래스를 붙이지 않는다');
  assert.equal(f.timers.size, 0, '움직임 축소에서는 전환 타이머를 만들지 않는다');
  assert.equal(f.row('careers').style.getPropertyValue('--digest-transition-height'), '');
  assert.equal(f.row('careers').style.getPropertyValue('--digest-current-width'), '');
  assertFocus(f, f.editor().querySelector('input'), '움직임 축소에서도 시작 초점은 즉시 이동한다');
  f.action('취소').click();
  assert(!f.row('careers').classList.contains('is-editing'));
  assert(!f.row('careers').classList.contains('is-transitioning'));
  assert.equal(f.timers.size, 0);
  assertFocus(f, f.pen('career:0'), '움직임 축소에서도 종료 초점은 즉시 돌아온다');
  f.flush();
}

// 기존 행 동작을 기본 정보에도 적용하고, 경고와 채택 출처가 저장 직전까지 이어지는지 확인한다.
{
  const f=fixture();
  f.pen('role').click();f.action('고치기 완료').click();
  assert(!f.digest.edited?.has('role'),'값을 그대로 완료하면 사용자 수정으로 표시하지 않는다');
  f.digest.proposal.warnings=[{message:'원문에서 확인되지 않은 숫자를 확인 필요로 표시했습니다.'}];
  f.context.renderDigest();
  assert(f.host.textContent.includes(f.digest.proposal.warnings[0].message));
  f.pen('organization').click();f.editor().querySelector('input').value='사용자가 고친 소속';f.action('고치기 완료').click();
  assert(f.row('organization').textContent.includes('자료 기반 + 사용자 수정'));
  f.item('name').querySelector('.digest-add').click();
  const apply=source.slice(source.indexOf('  function applyDigest(){'),source.indexOf('  function renderHistory()'));
  const cleaners=source.slice(source.indexOf('  function cleanCareers('),source.indexOf('  function hasChanges('));
  let serial=0;
  Object.assign(f.context,{requestId:()=>`new-${++serial}`,renderFields:()=>{},renderCareers:()=>{},updateControls:()=>{},cardEditing:null,cardBefore:null});
  const originalLookup=f.context.$;
  f.context.$=id=>id==='basics'?f.host:originalLookup(id);
  f.context.view.profile={fields:JSON.parse(JSON.stringify(f.draft.fields)),careers:[],provenance:{bio:{source_ids:['old-source']}}};
  f.context.view.limits.careers=20;
  vm.runInContext(cleaners+apply,f.context);
  vm.runInContext('applyDigest()',f.context);
  assert.equal(f.draft.fields.name,'기존 이름','뺀 기본 정보는 현재값을 유지한다');
  assert.equal(f.draft.fields.organization,'사용자가 고친 소속');
  assert.deepEqual([...f.draft.fields.aliases],['Old Name','New Name'],'별칭을 배열로 채택한다');
  assert.equal(f.draft.field_sources.organization.edited,true);
  assert.deepEqual([...f.draft.field_sources.bio.source_ids],['old-source','source-fixture'],'누적 문장의 이전 출처를 유지한다');
  f.draft.fields.department='채택 후 직접 수정';
  const fields=vm.runInContext('fieldSources(manualChanges().fields)',f.context);
  assert.equal(fields.department.edited,true,'채택 이후 편집도 사용자 수정으로 구분한다');
  assert(!fields.name,'제외한 필드의 출처를 보내지 않는다');
  f.draft.careers.at(-1).description='직접 고친 설명';
  const careers=vm.runInContext('cleanCareers(draft.careers)',f.context);
  assert.deepEqual([...careers.at(-1).source_ids],['source-fixture']);
  assert.equal(careers.at(-1).edited,true);
  assert.equal(careers.at(-2).edited,false);
  assert(!('_sourceValue' in careers.at(-1)),'내부 비교용 값은 저장 페이로드에 넣지 않는다');
  f.draft.fields.bio+=' 직접 고친 문장';
  f.context.digest={source_id:'second-source',name:'둘째 자료',proposal:{bio_addition:'두 번째 추가'},skip:new Set()};
  vm.runInContext('applyDigest()',f.context);
  assert.equal(f.draft.field_sources.bio.edited,true,'직접 고친 뒤 다른 자료를 누적해도 수정 표시를 유지한다');
  assert.deepEqual([...f.draft.field_sources.bio.source_ids],['old-source','source-fixture','second-source']);
  const block=source.slice(source.indexOf('  function blockEditor('),source.indexOf('  function editableField('));
  Object.assign(f.context,{labels:{organization:'소속'},clone:value=>JSON.parse(JSON.stringify(value)),fieldOrigin:()=>'',editableField:()=>f.document.createElement('input'),closeBlock:()=>{},cancelBlock:()=>{},renderCard:()=>{}});
  f.context.$=id=>['basics','cardView'].includes(id)?f.host:originalLookup(id);
  vm.runInContext(block,f.context);
  const editor=vm.runInContext('blockEditor({label:"이름·소속",fields:["organization"]})',f.context);
  editor.querySelectorAll('button').find(button=>button.textContent==='이 항목 되돌리기').click();
  assert.equal(f.draft.fields.organization,'기존 소속');
  assert(!f.draft.field_sources.organization,'저장값으로 되돌리면 새 자료의 출처 연결도 제거한다');
}

console.log(JSON.stringify({통과: true, 화면폭: [390, 1200], 시작종료전환: transitions, 검사: '기본 정보·별칭·행 유지·초점·선택·경고·출처 채택·사용자 수정·움직임 축소'}));
