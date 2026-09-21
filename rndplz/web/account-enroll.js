(() => {
  'use strict';
  const form = document.getElementById('enrollmentForm');
  const input = document.getElementById('invitationCode');
  const fields = document.getElementById('enrollmentFields');
  const submit = document.getElementById('enrollmentSubmit');
  const status = document.getElementById('enrollmentStatus');
  const error = document.getElementById('enrollmentError');
  const check = document.getElementById('checkEnrollment');
  const profile = document.getElementById('enrolledProfile');
  if (![form, input, fields, submit, status, error, check, profile].every(Boolean)) return;

  let csrf = '';
  let ready = false;
  let busy = false;
  let leaving = false;
  let epoch = 0;

  function lock(locked) {
    fields.disabled = locked;
    input.disabled = locked;
    submit.disabled = locked;
    form.setAttribute('aria-busy', busy ? 'true' : 'false');
  }
  function clearError() {
    error.textContent = '';
    error.hidden = true;
  }
  function showError(message) {
    error.textContent = message;
    error.hidden = false;
    error.focus();
  }
  function unavailable(message, retry = false) {
    ready = false;
    csrf = '';
    input.value = '';
    lock(true);
    status.textContent = message;
    check.hidden = !retry;
  }
  function googleDestination(value) {
    if (typeof value !== 'string' || value !== value.trim()) return null;
    try {
      const url = new URL(value);
      if (url.origin !== 'https://accounts.google.com' ||
          url.pathname !== '/o/oauth2/v2/auth' || url.username || url.password || url.hash) return null;
      return url.href;
    } catch {
      return null;
    }
  }

  async function loadSession() {
    if (busy || leaving) return;
    const requestEpoch = ++epoch;
    busy = true;
    ready = false;
    csrf = '';
    input.value = '';
    clearError();
    profile.hidden = true;
    check.setAttribute('aria-disabled', 'true');
    check.setAttribute('aria-busy', 'true');
    lock(true);
    status.textContent = '가입 가능 여부를 확인하고 있습니다.';
    try {
      const response = await fetch('/api/account/session', {
        credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) throw new Error('session unavailable');
      const data = await response.json();
      if (requestEpoch !== epoch || leaving) return;
      if (!data || typeof data !== 'object') throw new Error('invalid session');
      if (data.authenticated === true) {
        unavailable('이미 로그인되어 있습니다. 내 프로필에서 경험과 관심 분야를 이어서 정리해 주세요.', true);
        profile.hidden = false;
      } else if (data.authenticated !== false || data.account !== null) {
        throw new Error('invalid anonymous session');
      } else if (data.enabled !== true || data.enrollment_enabled !== true) {
        unavailable('팀원 가입을 준비 중입니다. 지금은 방문자로 계속 이용할 수 있습니다.', true);
      } else if (data.enrollment_url !== '/auth/google/enroll' ||
                 typeof data.token !== 'string' || !data.token.trim()) {
        unavailable('가입 상태를 확인하지 못했습니다. 페이지를 다시 열거나 잠시 후 확인해 주세요.', true);
      } else {
        csrf = data.token;
        ready = true;
        status.textContent = '초대 코드를 입력하면 Google 로그인으로 이어집니다.';
      }
    } catch {
      if (requestEpoch !== epoch || leaving) return;
      unavailable('가입 상태를 불러오지 못했습니다. 연결 상태를 확인한 뒤 다시 확인해 주세요.', true);
    } finally {
      if (requestEpoch === epoch && !leaving) {
        busy = false;
        lock(!ready);
        check.removeAttribute('aria-disabled');
        check.removeAttribute('aria-busy');
        if (ready || !profile.hidden) {
          // Transfer focus only while this control still owns it, before hiding it.
          if (document.activeElement === check) {
            (ready ? input : profile).focus({ preventScroll: true });
          }
          check.hidden = true;
        }
      }
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!ready || busy || leaving) return;
    if (!input.value.trim()) {
      showError('받은 초대 코드를 입력해 주세요.');
      input.focus();
      return;
    }
    const requestEpoch = ++epoch;
    busy = true;
    clearError();
    check.hidden = true;
    lock(true);
    status.textContent = '초대를 확인하고 Google 로그인을 준비하고 있습니다.';
    let requestBody = JSON.stringify({ invitation: input.value.trim() });
    input.value = '';
    try {
      const pending = fetch('/auth/google/enroll', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-RNDPLZ-TOKEN': csrf },
        body: requestBody
      });
      requestBody = '';
      const response = await pending;
      if (requestEpoch !== epoch || leaving) return;
      if (!response.ok) {
        const messages = {
          400: '초대 코드를 사용할 수 없습니다. 잘못 입력했거나 만료·사용된 코드일 수 있습니다. 초대한 분에게 확인해 주세요.',
          403: '가입 요청을 확인할 수 없습니다. 가입 가능 여부를 다시 확인한 뒤 진행해 주세요.',
          429: '요청이 많습니다. 잠시 후 다시 진행해 주세요.',
          503: '지금은 Google 가입을 시작할 수 없습니다. 잠시 후 가입 가능 여부를 다시 확인해 주세요.'
        };
        unavailable('가입이 완료되지 않았습니다.', true);
        showError(messages[response.status] || '가입 요청의 처리 결과를 확인하지 못했습니다. 초대가 이미 사용 처리됐을 수 있으니 초대한 분에게 새 코드가 필요한지 확인해 주세요.');
        return;
      }
      if (response.status !== 200) throw new Error('unexpected response');
      const data = await response.json();
      if (requestEpoch !== epoch || leaving) return;
      const destination = googleDestination(data && data.authorization_url);
      if (!destination) throw new Error('invalid authorization destination');
      csrf = '';
      ready = false;
      status.textContent = 'Google 로그인으로 이동합니다.';
      window.location.assign(destination);
      leaving = true;
    } catch {
      if (requestEpoch !== epoch || leaving) return;
      unavailable('가입 요청의 처리 결과를 확인하지 못했습니다.', true);
      showError('초대가 이미 가입 절차에 사용됐을 수 있습니다. 초대한 분에게 새 코드가 필요한지 확인한 뒤 다시 진행해 주세요.');
    } finally {
      requestBody = '';
      if (requestEpoch === epoch && !leaving) {
        input.value = '';
        busy = false;
        lock(!ready);
      }
    }
  });
  check.addEventListener('click', loadSession);
  window.addEventListener('pagehide', () => {
    epoch++;
    leaving = true;
    ready = false;
    csrf = '';
    input.value = '';
    lock(true);
  });
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    leaving = false;
    busy = false;
    loadSession();
  });
  loadSession();
})();
