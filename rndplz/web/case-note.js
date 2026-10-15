/* How a request turned out (2026-10-15): the result sheet, the 제안함 card's result line, and the one-time question
   on the home a week after a send. Each page passes its own api(path, body). The server keeps the note on the
   send's letters (case_notes.py); a note shared with the team waits for the admin. */
(() => {
  'use strict';
  const RESULTS = [['solved', '해결됐어요'], ['partial', '일부 풀렸어요'], ['unsolved', '안 풀렸어요'], ['ongoing', '아직 진행 중']];
  const REASONS = [['field', '분야가 달랐어요'], ['evidence', '근거가 약했어요'], ['unreachable', '연락이 닿지 않았어요'],
    ['changed', '문제가 바뀌었어요'], ['other', '기타']];
  const FIELDS = {
    problem: ['무엇이 문제였나요', ''],
    helped: ['도움이 된 것', '예: 운전 조건부터 바꿔 보라는 조언을 받았다'],
    remaining: ['아직 남은 것', '예: 장치를 바꿔야 하는지는 아직 모른다'],
    lesson: ['다음에 쓸 교훈', '예: 비슷한 일은 조건을 의뢰서에 함께 적으면 빠르다'],
    tried: ['해 본 것', '예: 의뢰서를 보냈지만 답을 받지 못했다'],
    next: ['다음에 다르게 해 볼 것', '예: 인접 분야 후보 두 분께 함께 보내 보기']
  };
  const SHOWN = { solved: ['problem', 'helped', 'lesson'], partial: ['problem', 'helped', 'remaining', 'lesson'],
    unsolved: ['problem', 'tried', 'next'], ongoing: [] };
  const SENT = ['sent', 'accepted', 'declined', 'closed'];
  const WEEK = 7 * 864e5;
  const label = result => (RESULTS.find(([key]) => key === result) || [, ''])[1];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const daysSince = iso => { const t = Date.parse(iso); return Number.isFinite(t) ? Math.max(0, Math.floor((Date.now() - t) / 864e5)) : null; };
  const chips = (items, picked, attr, extra = '') => '<div class="case-chips' + extra + '" role="group">' + items.map(([key, text]) =>
    '<button type="button" data-' + attr + '="' + key + '" aria-pressed="' + (picked.includes(key) ? 'true' : 'false') + '">' + text + '</button>').join('') + '</div>';

  function recipientsText(names) {
    const list = (names || []).filter(Boolean);
    return !list.length ? '보낸 분' : list.length === 1 ? list[0] + '님' : list[0] + '님 외 ' + (list.length - 1) + '명';
  }

  // The result sheet. `preset` picks a result first; a saved note opens as it was, to change.
  async function open(groupId, { api, preset = null, onSaved = () => {} } = {}) {
    const info = await api('/api/proposals/outcome-draft', { group_id: groupId });
    const saved = info.saved || {};
    let result = preset || saved.result || null;
    let reasons = Array.isArray(saved.reasons) ? [...saved.reasons] : [];
    const values = { problem: info.problem || '', ...(saved.notes || {}) };
    let visibility = saved.visibility || 'private';
    const dialog = document.createElement('dialog');
    dialog.className = 'case-dialog';
    dialog.setAttribute('aria-labelledby', 'caseTitle');
    document.body.append(dialog);
    dialog.addEventListener('close', () => dialog.remove());
    const when = info.days == null ? '' : info.days === 0 ? ' · 오늘 보냄' : ' · 보낸 지 ' + info.days + '일';

    function keep() { dialog.querySelectorAll('[data-field]').forEach(t => { values[t.dataset.field] = t.value; }); }
    function render() {
      const fields = SHOWN[result] || [];
      dialog.innerHTML = '<div class="case-frame"><section class="case-sheet">' +
        '<header><span class="case-eyebrow">CASE NOTE</span><button type="button" class="case-x" data-case="close" aria-label="결과 남기기 닫기">×</button></header>' +
        '<h2 id="caseTitle">결과 남기기</h2><p class="case-sub">' + esc(recipientsText(info.recipients)) + '께 보낸 의뢰' + esc(when) + '</p>' +
        chips(RESULTS, result ? [result] : [], 'result', ' case-result') +
        (result === 'unsolved' ? '<p class="case-q">어디서 막혔나요? 여러 개 골라도 돼요</p>' + chips(REASONS, reasons, 'reason') : '') +
        (fields.length ? '<p class="case-note-hint">✦ 대화에서 정리한 요청으로 채웠어요. 고치거나 지워도 돼요.</p>' : '') +
        fields.map(key => (key === 'helped' || key === 'tried' ? '<div class="case-fixed"><span>어떻게 찾았나요 (자동)</span>' + esc(info.route) + '</div>' : '') +
          '<label class="case-field"><span>' + FIELDS[key][0] + '</span><textarea data-field="' + key + '" rows="2" maxlength="1000" placeholder="' + esc(FIELDS[key][1]) + '">' + esc(values[key] || '') + '</textarea></label>').join('') +
        (result === 'unsolved' ? '<p class="case-privacy">안 풀린 사례는 받는 분 이름을 빼고, 경로와 이유만 남겨요.</p>' : '') +
        (result && result !== 'ongoing' ? '<fieldset class="case-visibility"><legend>공개 범위</legend>' +
          '<label><input type="radio" name="caseVisibility" value="private"' + (visibility === 'private' ? ' checked' : '') + '> <span>나만 보기<small>내 제안함과 연결 지표의 해결률에만 쓰여요.</small></span></label>' +
          '<label><input type="radio" name="caseVisibility" value="team"' + (visibility === 'team' ? ' checked' : '') + '> <span>팀과 공유<small>관리자가 확인한 뒤 팀 사례 모음에 올라가요.</small></span></label></fieldset>' : '') +
        (result === 'ongoing' ? '<p class="case-privacy">아직 진행 중이면 일주일 뒤 홈에서 한 번 더 여쭐게요.</p>' : '') +
        '<p class="case-status" role="status" aria-live="polite"></p>' +
        '<footer><button type="button" class="case-ghost" data-case="close">나중에</button><button type="button" class="case-save" data-case="save"' + (result ? '' : ' disabled') + '>저장</button></footer>' +
        '</section></div>';
    }
    dialog.addEventListener('click', async event => {
      const button = event.target.closest('button');
      if (!button) { if (event.target === dialog || event.target.classList.contains('case-frame')) dialog.close(); return; }
      if (button.dataset.case === 'close') return dialog.close();
      if (button.dataset.result) { keep(); result = button.dataset.result; if (result !== 'unsolved') reasons = []; render(); dialog.querySelector('[data-result="' + result + '"]')?.focus(); return; }
      if (button.dataset.reason) {
        const key = button.dataset.reason;
        reasons = reasons.includes(key) ? reasons.filter(r => r !== key) : [...reasons, key];
        button.setAttribute('aria-pressed', String(reasons.includes(key)));
        return;
      }
      if (button.dataset.case === 'save') {
        keep();
        const status = dialog.querySelector('.case-status');
        visibility = dialog.querySelector('input[name="caseVisibility"]:checked')?.value || 'private';
        const notes = Object.fromEntries((SHOWN[result] || []).map(key => [key, values[key] || '']).filter(([, v]) => v.trim()));
        button.disabled = true; status.textContent = '저장하고 있어요…';
        try {
          const note = await api('/api/proposals/outcome', { group_id: groupId, result, reasons: result === 'unsolved' ? reasons : [],
            notes, visibility: result === 'ongoing' ? 'private' : visibility });
          dialog.close(); onSaved(note);
        } catch (error) {
          button.disabled = false; status.textContent = '저장하지 못했어요. ' + (error?.message || '다시 시도해 주세요.');
        }
      }
    });
    dialog.addEventListener('input', event => { if (event.target.matches('input[name="caseVisibility"]')) visibility = event.target.value; });
    render();
    dialog.showModal();
    (dialog.querySelector('[data-result][aria-pressed="true"]') || dialog.querySelector('[data-result]'))?.focus();
  }

  // The 제안함 card's line: the saved result, or the way to leave one.
  function block(proposal) {
    if (!proposal || !SENT.includes(proposal.state) || !proposal.group_id) return '';
    const note = proposal.outcome;
    if (note && note.result) {
      const days = Number.isInteger(note.days) ? (note.days === 0 ? '당일' : note.days + '일') : '';
      return '<div class="case-badge" data-result="' + esc(note.result) + '"><b>' + esc(label(note.result)) + '</b><span>' +
        [days, note.visibility === 'team' ? '팀과 공유' : '나만 보기'].filter(Boolean).map(t => ' · ' + esc(t)).join('') +
        '</span><button type="button" data-action="case" data-group="' + esc(proposal.group_id) + '">고치기</button></div>';
    }
    const days = daysSince(proposal.created);
    return '<div class="case-entry"><p><b>일은 어떻게 됐나요?</b>' + (days ? '보낸 지 ' + days + '일' : '오늘 보냄') +
      ' · 결과를 남기면 다음 수소문에 쓰여요.</p><button type="button" data-action="case" data-group="' + esc(proposal.group_id) + '">결과 남기기</button></div>';
  }

  // The home asks once about the oldest send a week old without a result (or a week after "아직 진행 중").
  const MEMO = 'susomun.caseAsk';
  function memo() { try { const v = JSON.parse(localStorage.getItem(MEMO) || '{}'); return Array.isArray(v.asked) ? v : { asked: [] }; } catch { return { asked: [] }; } }
  function remember(key) { try { const v = memo(); localStorage.setItem(MEMO, JSON.stringify({ asked: [key, ...v.asked.filter(k => k !== key)].slice(0, 100) })); } catch {} }
  async function homeAsk({ api, anchor }) {
    if (!anchor || document.querySelector('.case-ask')) return;
    let proposals;
    try { proposals = await api('/api/proposals'); } catch { return; }
    if (!Array.isArray(proposals)) return;
    const groups = new Map();
    for (const p of proposals) if (SENT.includes(p.state) && p.group_id) groups.set(p.group_id, [...(groups.get(p.group_id) || []), p]);
    const asked = memo().asked;
    const due = [...groups.values()].map(letters => {
      const first = letters[0], note = first.outcome;
      const since = note?.result === 'ongoing' ? note.at : note ? null : first.created;
      const key = first.group_id + (note?.at ? ':' + note.at : '');
      return { letters, since, key, ongoing: note?.result === 'ongoing' };
    }).filter(item => item.since && Date.now() - Date.parse(item.since) >= WEEK && !asked.includes(item.key))
      .sort((a, b) => Date.parse(a.since) - Date.parse(b.since))[0];
    if (!due) return;
    remember(due.key);  // asked once: passing it by is an answer too
    const names = recipientsText(due.letters.map(p => p.recipient_name));
    const box = document.createElement('div');
    box.className = 'case-ask';
    box.setAttribute('role', 'region');
    box.setAttribute('aria-label', '보낸 의뢰의 결과');
    box.innerHTML = '<p><b>' + (due.ongoing ? esc(names) + '께 보낸 의뢰, 그 뒤로 어떻게 됐나요?' : '지난번 ' + esc(names) + '께 보낸 의뢰, 어떻게 됐나요?') + '</b>' +
      (due.ongoing ? '지난번에 아직 진행 중이라고 남기셨어요.' : '보낸 지 ' + daysSince(due.letters[0].created) + '일') + '</p>' +
      chips(RESULTS, [], 'result', ' case-result') + '<p class="case-status" role="status" aria-live="polite"></p><button type="button" class="case-later">나중에</button>';
    anchor.after(box);
    const group = due.letters[0].group_id;
    const thank = text => { box.innerHTML = '<p><b>고마워요.</b>' + esc(text) + '</p>'; };
    box.addEventListener('click', async event => {
      const button = event.target.closest('button');
      if (!button) return;
      if (button.classList.contains('case-later')) return box.remove();
      const result = button.dataset.result;
      if (result === 'ongoing') {
        try { await api('/api/proposals/outcome', { group_id: group, result: 'ongoing', reasons: [], notes: {}, visibility: 'private' }); thank('일주일 뒤에 한 번 더 여쭐게요.'); }
        catch (error) { box.querySelector('.case-status').textContent = '저장하지 못했어요. ' + (error?.message || ''); }
        return;
      }
      try { await open(group, { api, preset: result, onSaved: () => thank('남겨 주신 결과는 제안함에서 볼 수 있어요.') }); }
      catch (error) { box.querySelector('.case-status').textContent = '결과 창을 열지 못했어요. ' + (error?.message || ''); }
    });
  }

  window.RndCaseNote = { open, block, homeAsk, label };
})();
