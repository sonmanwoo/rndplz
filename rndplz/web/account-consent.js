(() => {
  'use strict';
  const agree = document.getElementById('consentAgree');
  const decline = document.getElementById('consentDecline');
  const status = document.getElementById('consentStatus');
  const error = document.getElementById('consentError');
  if (![agree, decline, status, error].every(Boolean)) return;

  let csrf = '';
  let busy = false;

  function lock(locked) {
    agree.disabled = locked;
    decline.disabled = locked;
  }
  function showError(message) {
    error.textContent = message;
    error.hidden = false;
    error.focus();
  }
  // Only a path on this site, never another origin.
  function destination(value) {
    return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : null;
  }

  async function loadSession() {
    lock(true);
    try {
      const response = await fetch('/api/account/session', {
        credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/json' }
      });
      if (!response.ok) throw new Error('session unavailable');
      const data = await response.json();
      if (!data || typeof data.token !== 'string' || !data.token) throw new Error('no token');
      csrf = data.token;
      status.textContent = '동의 여부를 골라 주세요. 10분이 지나면 처음부터 다시 로그인해야 합니다.';
      lock(false);
    } catch {
      status.textContent = '동의 화면을 준비하지 못했습니다.';
      showError('페이지를 다시 열거나, 홈에서 처음부터 다시 로그인해 주세요.');
    }
  }

  async function answer(decision) {
    if (busy || !csrf) return;
    busy = true;
    lock(true);
    error.hidden = true;
    status.textContent = decision === 'agree' ? '동의를 기록하고 로그인을 마무리하고 있습니다.' : '동의하지 않음을 처리하고 있습니다.';
    try {
      const response = await fetch('/auth/consent', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-RNDPLZ-TOKEN': csrf },
        body: JSON.stringify({ decision })
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        status.textContent = '처리하지 못했습니다.';
        showError(response.status === 503
          ? '지금은 로그인을 마무리할 수 없습니다. 잠시 후 처음부터 다시 로그인해 주세요.'
          : '동의할 로그인 정보가 없거나 10분이 지났습니다. 홈에서 처음부터 다시 로그인해 주세요.');
        return;
      }
      const next = destination(data && data.location);
      if (!next) throw new Error('invalid destination');
      csrf = '';
      status.textContent = decision === 'agree' ? '로그인을 마쳤습니다. 이동합니다.' : '동의하지 않아 로그인하지 않았습니다. 방문자로 이동합니다.';
      window.location.assign(next);
    } catch {
      status.textContent = '처리 결과를 확인하지 못했습니다.';
      showError('홈에서 처음부터 다시 로그인해 주세요.');
    } finally {
      busy = false;
    }
  }

  agree.addEventListener('click', () => answer('agree'));
  decline.addEventListener('click', () => answer('decline'));
  loadSession();
})();
