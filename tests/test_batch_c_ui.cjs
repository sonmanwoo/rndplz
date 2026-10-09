'use strict';
// 합성 DOM으로 닫기 경로와 초점 복귀를 확인한다. 브라우저나 서버를 실행하지 않는다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../rndplz/web/app.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../rndplz/web/site-cosmos.css'), 'utf8');

const pending = [];
const body = {};
const document = {activeElement: body, body, documentElement: {inert: false}};
class Button {
  constructor(dialog = null) { this.dialog = dialog; this.isConnected = true; this.disabled = false; this.hidden = false; this.focusCalls = []; }
  matches() { return true; }
  closest(selector) { return selector === 'dialog' ? this.dialog : this.hidden ? {} : null; }
  getClientRects() { return this.hidden ? [] : [{}]; }
  focus(options) { this.focusCalls.push(options); document.activeElement = this; }
}
class Dialog {
  constructor(id) { this.id = id; this.open = false; this.events = {}; this.classList = {contains: () => false, toggle() {}}; }
  addEventListener(type, listener) { (this.events[type] ||= []).push(listener); }
  emit(type, extra = {}) {
    const event = {target: this, clientX: 0, clientY: 0, preventDefault() { this.defaultPrevented = true; }, ...extra};
    for (const listener of this.events[type] || []) listener(event);
    return event;
  }
  contains(element) { return element?.dialog === this; }
  getBoundingClientRect() { return {left: 10, top: 10, right: 110, bottom: 110}; }
  showModal() { this.open = true; document.activeElement = new Button(this); }
  show() { this.showModal(); }
  close() { if (!this.open) return; this.open = false; document.activeElement = body; pending.push(() => this.emit('close')); }
}
const inbox = new Dialog('inboxDialog'), settings = new Dialog('settingsDialog'), detail = new Dialog('detailDialog');
const dialogs = [inbox, settings, detail];
const elements = Object.fromEntries(dialogs.map(dialog => [dialog.id, dialog]));
elements.inboxCount = {}; elements.inboxContent = {};
document.getElementById = id => elements[id];
document.querySelector = selector => selector === 'dialog[open]' ? dialogs.find(dialog => dialog.open) || null : null;
document.querySelectorAll = selector => selector === 'dialog[open]' ? dialogs.filter(dialog => dialog.open) : dialogs.filter(dialog => dialog !== detail);
const scope = {document, $: document.getElementById, detailReturn: null, detailTrigger: null, detailPersonId: null,
  api: async () => { document.activeElement = body; return []; }};
vm.createContext(scope);
vm.runInContext(source.slice(source.indexOf('function detailDocked()'), source.indexOf('function renderExamples()')) + '\n' +
  source.slice(source.indexOf('// Shared modal dialogs return'), source.length) + '\n' +
  source.slice(source.indexOf('async function openInbox('), source.indexOf('\nfunction renderRecipient(')), scope);
const closeBranch = source.slice(source.indexOf(' if(action==="close"){'), source.indexOf(' if(action==="scene-close")'));
vm.runInContext('function clickClose(button){const action="close";' + closeBranch + '}', scope);
const flush = () => { while (pending.length) pending.shift()(); };
const begin = () => { const opener = new Button(); document.activeElement = opener; scope.showDialog('inboxDialog'); return opener; };

(async () => {
  // 비동기 조회와 disabled 처리로 activeElement가 바뀌어도 실제 진입 버튼을 보관한다.
  const opener = new Button(); opener.disabled = true;
  await scope.openInbox(opener);
  opener.disabled = false;
  scope.clickClose(new Button(inbox)); flush();
  assert.equal(document.activeElement, opener, '×로 닫으면 제안함 진입 버튼으로 돌아간다');
  assert.equal(opener.focusCalls[0].preventScroll, true, '초점 복귀가 페이지를 스크롤하지 않는다');

  const escapeOpener = begin();
  // Escape: the browser closes a modal dialog unless its cancel event is prevented.
  if (!inbox.emit('cancel').defaultPrevented) inbox.close();
  flush(); assert.equal(document.activeElement, escapeOpener, 'Esc로 닫아도 초점이 복귀한다');

  const backdropOpener = begin();
  inbox.emit('pointerdown'); inbox.emit('click'); flush();
  assert.equal(document.activeElement, backdropOpener, '바깥에서 누르고 놓으면 닫고 초점을 복귀한다');

  begin();
  inbox.emit('pointerdown', {clientX: 50, clientY: 50}); inbox.emit('click');
  assert.equal(inbox.open, true, '안에서 시작한 드래그를 바깥에서 놓아도 닫지 않는다');
  inbox.close(); flush();
  // 작성·설정 창은 바깥 누름으로 닫지 않는다(의뢰 초안 입력이 사라지지 않게).
  settings.showModal(); settings.emit('pointerdown'); settings.emit('click');
  assert.equal(settings.open, true, '설정 창은 바깥을 눌러도 열려 있다');
  settings.close(); flush();

  for (const unavailable of ['hidden', 'disabled', 'disconnected', 'document-inert']) {
    const hiddenOpener = begin();
    if (unavailable === 'hidden') hiddenOpener.hidden = true;
    if (unavailable === 'disabled') hiddenOpener.disabled = true;
    if (unavailable === 'disconnected') hiddenOpener.isConnected = false;
    if (unavailable === 'document-inert') document.documentElement.inert = true;
    inbox.close(); flush();
    assert.equal(hiddenOpener.focusCalls.length, 0, unavailable + ': 초점을 받을 수 없는 버튼에는 복귀하지 않는다');
    document.documentElement.inert = false;
  }

  const priorOpener = begin();
  scope.showDialog('settingsDialog', false, new Button(inbox));
  flush(); assert.equal(priorOpener.focusCalls.length, 0, '새 창이 열리면 이전 창의 지연된 close가 초점을 빼앗지 않는다');
  settings.close(); flush();

  const refreshOpener = begin();
  scope.showDialog('inboxDialog'); flush();
  assert.equal(inbox.open, true);
  assert.equal(refreshOpener.focusCalls.length, 0, '같은 창을 다시 열어도 이전 close가 초점을 빼앗지 않는다');
  inbox.close(); flush();
  assert.equal(document.activeElement, refreshOpener, '제안 상태를 갱신해도 최초 진입 버튼을 유지한다');

  const returnOpener = begin();
  scope.showDialog('detailDialog'); flush();
  detail.close(); scope.showDialog('inboxDialog', false, null); flush();
  inbox.close(); flush();
  assert.equal(document.activeElement, returnOpener, '근거를 보고 제안함으로 돌아와도 최초 진입 버튼을 유지한다');

  // CSS 계약 검사: 고리는 터치/작은 화면에서만 생기고 원래 버튼의 크기·배치를 바꾸지 않는다.
  const touch = css.slice(css.indexOf('/* Touch: the remaining small controls'));
  assert.match(touch, /@media \(pointer:coarse\),\(max-width:700px\)/);
  for (const selector of ['.craft-nav :is(a,button)::after', '.field-meta .text-button::after', '#personCardDialog>.close::after', '#detailDialog .close-button::after']) {
    const rule = touch.slice(touch.indexOf(selector)).split('}')[0];
    assert.match(rule, /position:absolute/);
    assert.match(rule, /inset:-\d+px/);
    assert.match(rule, /min-height:44px/);
  }
  assert.match(touch, /#detailDialog\.sheet \.close-button::after\{inset:-7px\}/);
  assert.match(touch, /:active:not\(:disabled\)[^{]*\{transform:none\}/);
  console.log('묶음 C UI 단위 시험 통과: 초점 복귀·바깥 누름·고리 CSS 계약');
})().catch(error => { console.error(error); process.exitCode = 1; });
