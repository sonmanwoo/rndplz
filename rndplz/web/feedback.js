/* Customer feedback opens a mail draft; it does not send or receive mail. */
(() => {
  'use strict';
  const entry = document.querySelector('[data-feedback-open]');
  if (!entry || document.getElementById('feedbackDialog')) return;
  const address = 'manwooson@gscaltex.com';
  const categories = {
    bug: {label: '오류 신고', guide: '어떤 작업에서 문제가 생겼나요? 기대한 결과와 실제 결과를 적어주세요.'},
    improvement: {label: '개선 제안', guide: '어떤 점이 불편했나요? 바라는 변화를 적어주세요.'},
    other: {label: '기타 의견', guide: '수소문에 전하고 싶은 의견을 적어주세요.'}
  };
  const page = entry.dataset.feedbackPage === 'chat' ? '대화' : entry.dataset.feedbackPage === 'explore' ? '연구 맵' : '';
  const dialog = document.createElement('dialog');
  dialog.id = 'feedbackDialog';
  dialog.className = 'feedback-dialog';
  dialog.setAttribute('aria-labelledby', 'feedbackTitle');
  dialog.setAttribute('aria-describedby', 'feedbackDescription');
  dialog.innerHTML = `
    <div class="feedback-heading"><h2 id="feedbackTitle">의견 보내기</h2><button type="button" class="feedback-close" data-feedback-close aria-label="의견 보내기 닫기">×</button></div>
    <p id="feedbackDescription">수소문을 더 편리하게 만드는 데 의견을 보태주세요. 내용은 메일 앱에서 작성합니다.</p>
    <label for="feedbackCategory">의견 유형</label>
    <select id="feedbackCategory"><option value="bug">오류 신고</option><option value="improvement" selected>개선 제안</option><option value="other">기타 의견</option></select>
    <p id="feedbackGuide" class="feedback-guide"></p>
    <label for="feedbackAddress">받는 곳</label>
    <div class="feedback-address-row"><input id="feedbackAddress" class="feedback-address" type="text" readonly spellcheck="false" autocomplete="off" aria-describedby="feedbackCopyHelp"><button type="button" data-feedback-copy>주소 복사</button></div>
    <p id="feedbackCopyHelp" class="feedback-help">메일 앱이 연결되어 있지 않으면 주소를 복사해 사용하세요.</p>
    <div class="feedback-actions"><a id="feedbackMail" class="feedback-mail">메일 작성하기 ↗</a></div>
    <p class="feedback-help">대화 내용과 첨부 자료는 자동으로 포함하지 않습니다.</p>
    <p id="feedbackStatus" class="feedback-status" role="status" aria-live="polite" aria-atomic="true"></p>`;
  document.body.append(dialog);
  const category = dialog.querySelector('#feedbackCategory');
  const guide = dialog.querySelector('#feedbackGuide');
  const addressField = dialog.querySelector('#feedbackAddress');
  const copy = dialog.querySelector('[data-feedback-copy]');
  const mail = dialog.querySelector('#feedbackMail');
  const status = dialog.querySelector('#feedbackStatus');
  addressField.value = address;
  let blocked = false;
  let invalidated = false;
  let epoch = 0;
  let copying = false;

  function updateMail() {
    const selected = Object.prototype.hasOwnProperty.call(categories, category.value) ? categories[category.value] : null;
    status.textContent = '';
    if (!selected) {
      mail.removeAttribute('href');
      mail.setAttribute('aria-disabled', 'true');
      guide.textContent = '의견 유형을 선택해 주세요.';
      return;
    }
    const body = selected.guide + (page ? '\n\n화면: ' + page : '');
    mail.href = 'mailto:' + address + '?subject=' + encodeURIComponent('[수소문] ' + selected.label) + '&body=' + encodeURIComponent(body);
    mail.removeAttribute('aria-disabled');
    guide.textContent = selected.guide;
  }

  function resetTransient() {
    epoch++;
    copying = false;
    copy.disabled = false;
    status.textContent = '';
  }

  function close() {
    resetTransient();
    if (dialog.open) dialog.close();
  }

  entry.addEventListener('click', () => {
    if (blocked || invalidated || document.documentElement.inert || !entry.isConnected || document.querySelector('dialog[open]')) return;
    resetTransient();
    updateMail();
    dialog.showModal();
    category.focus();
  });
  category.addEventListener('change', updateMail);
  dialog.querySelector('[data-feedback-close]').addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('close', () => {
    // A queued close from the previous opening must not disturb a new one.
    if (dialog.open) return;
    resetTransient();
    if (!blocked && !invalidated && entry.isConnected && !document.documentElement.inert && !document.querySelector('dialog[open]')) entry.focus({preventScroll: true});
  });
  mail.addEventListener('click', event => {
    if (blocked || invalidated || !dialog.open || !mail.getAttribute('href')) { event.preventDefault(); return; }
    status.textContent = '메일 앱에서 내용을 작성하고 보내주세요.';
  });
  copy.addEventListener('click', async () => {
    if (copying || blocked || invalidated || !dialog.open) return;
    const ticket = ++epoch;
    copying = true;
    copy.disabled = true;
    status.textContent = '';
    const current = () => ticket === epoch && dialog.open && !blocked && !invalidated;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(address);
      if (current()) status.textContent = '주소를 복사했어요.';
    } catch {
      if (current()) {
        status.textContent = '자동 복사를 하지 못했어요. 주소를 선택해 직접 복사해 주세요.';
        addressField.focus();
        addressField.select();
      }
    } finally {
      if (current()) { copying = false; copy.disabled = false; }
    }
  });
  window.addEventListener('rndplz:account-navigation', event => {
    const phase = event.detail?.phase;
    if (!['begin', 'cancel', 'invalidate'].includes(phase)) return;
    if (phase === 'invalidate') invalidated = true;
    blocked = phase !== 'cancel' || invalidated;
    entry.disabled = blocked;
    if (blocked) close();
  });
  updateMail();
  entry.hidden = false;
})();
