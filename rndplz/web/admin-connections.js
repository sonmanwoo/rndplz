/* The operator's connection counts (2026-10-14): numbers come from /api/account/connections, which
   answers the admin account only; this file holds no data. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const status = $('metricsStatus');
  const charts = {
    choice: [['first', '첫 카드', '--s1'], ['other', '다른 추천 카드', '--s2'], ['picked', '지도에서 직접 고름', '--s3'], ['unknown', '확인 어려움', '--none']],
    edit: [['same', '그대로', '--o1'], ['light', '조금 고침', '--o2'], ['heavy', '많이 고침', '--o3']],
    letter: [['model', 'AI가 다듬은 문장', '--s1'], ['rule', '규칙 문장', '--s2']],
    reaction: [['good', '잘 맞아요', '--s1'], ['unsure', '애매해요', '--none'], ['bad', '안 맞아요', '--bad']]
  };
  let data = null;
  let period = 'week';
  const tip = document.createElement('div');
  tip.className = 'metrics-tip';
  tip.hidden = true;
  document.body.append(tip);

  const share = (part, whole) => whole > 0 ? Math.round(part * 100 / whole) + '%' : '—';

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function tile(label, value, note) {
    const box = node('div', 'metrics-tile');
    box.append(node('span', '', label), node('b', '', String(value)), node('small', '', note || ''));
    return box;
  }

  function bar(host, counts, rows) {
    const total = rows.reduce((sum, [key]) => sum + (counts[key] || 0), 0);
    const strip = node('div', 'metrics-bar' + (total ? '' : ' is-empty'));
    strip.setAttribute('role', 'img');
    const legend = node('ul', 'metrics-legend');
    const words = [];
    for (const [key, label, color] of rows) {
      const count = counts[key] || 0;
      if (key === 'unknown' && !count) continue;
      words.push(label + ' ' + count + '건');
      if (count) {
        const part = node('span');
        part.style.flex = String(count);
        part.style.background = 'var(' + color + ')';
        part.dataset.tip = label + ' · ' + count + '건 · ' + share(count, total);
        strip.append(part);
      }
      const item = node('li');
      const swatch = node('i');
      swatch.style.background = 'var(' + color + ')';
      item.append(swatch, node('span', '', label), node('b', '', String(count)), node('small', '', share(count, total)));
      legend.append(item);
    }
    strip.setAttribute('aria-label', total ? words.join(', ') : '아직 없음');
    host.replaceChildren(strip, total ? legend : node('p', 'metrics-empty', '이 기간에는 아직 없어요.'));
  }

  const reasons = [['field', '분야가 달라요'], ['evidence', '근거가 약해요'], ['known', '이미 아는 분이에요']];

  function render() {
    const row = data.periods[period];
    const answered = row.reaction.good + row.reaction.unsure + row.reaction.bad;
    $('reactionNote').textContent = '의뢰서를 보낸 ' + row.sends + '번 중 ' + answered + '번 답했어요(' + share(answered, row.sends) +
      '). 한 대화에 한 번만 묻고, 두 번 연달아 지나친 사람에게는 더 묻지 않아요.';
    $('reasons').replaceChildren(node('li', '', '아쉬운 이유'), ...reasons.map(([key, label]) => {
      const item = node('li');
      item.append(node('span', '', label), node('b', '', String(row.reason[key] || 0)));
      return item;
    }));
    const visit = data.visits?.[period] || { visitors: 0, accounts: 0, views: 0 };
    $('visits').replaceChildren(
      tile('방문자', visit.visitors),
      tile('그중 로그인', visit.accounts, '방문자의 ' + share(visit.accounts, visit.visitors)),
      tile('페이지 열람', visit.views, visit.visitors ? '한 명당 ' + (visit.views / visit.visitors).toFixed(1) + '번' : ''));
    $('visitNote').textContent = '사람이 연 페이지만 셉니다(자동 점검·봇 제외). ' +
      (data.visits_since ? data.visits_since + '부터 센 숫자예요.' : '10월 14일 배포 이후부터 셉니다.');
    const funnel = $('funnel');
    funnel.replaceChildren(
      tile('대화 시작', row.started),
      tile('수소문', row.searched, '대화의 ' + share(row.searched, row.started)),
      tile('의뢰서 저장', row.proposed, '수소문의 ' + share(row.proposed, row.searched)),
      tile('보냄', row.sent, '수소문의 ' + share(row.sent, row.searched)));
    $('funnelNote').textContent = '수소문한 대화 중 로그인 ' + row.searched_by.account + ' · 방문자 ' + row.searched_by.visitor +
      '. 대화는 시작한 날짜로, 의뢰서는 저장한 날짜로 셉니다.';
    for (const [name, rows] of Object.entries(charts)) bar(document.querySelector('[data-chart="' + name + '"]'), row[name], rows);
    const lines = [['대화 시작', row.started], ['수소문', row.searched], ['의뢰서 저장한 대화', row.proposed], ['보낸 대화', row.sent],
      ['의뢰서 수', row.letters], ['보낸 의뢰서 수', row.letters_sent]];
    lines.push(['보낸 횟수', row.sends], ['방문자', visit.visitors], ['로그인 방문자', visit.accounts], ['페이지 열람', visit.views]);
    for (const [name, rows] of Object.entries(charts)) for (const [key, label] of rows) lines.push([label, row[name][key] || 0]);
    for (const [key, label] of reasons) lines.push(['이유: ' + label, row.reason[key] || 0]);
    $('metricsTable').replaceChildren(...lines.map(([label, value]) => {
      const tr = node('tr');
      tr.append(node('th', '', label), node('td', '', String(value)));
      return tr;
    }));
    const since = data.since[period];
    $('metricsStamp').textContent = '기준 ' + data.generated_at.replace('T', ' ').slice(0, 16) + ' (한국 시간) · ' +
      (since ? since + '부터' : '전체 기간') + ' · 페이지를 새로 열면 다시 셉니다.';
    document.querySelectorAll('[data-period]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.period === period)));
  }

  document.querySelectorAll('[data-period]').forEach(button => button.addEventListener('click', () => {
    period = button.dataset.period;
    if (data) render();
  }));
  document.addEventListener('pointermove', event => {
    const part = event.target.closest?.('.metrics-bar span');
    if (!part) { tip.hidden = true; return; }
    tip.textContent = part.dataset.tip;
    tip.hidden = false;
    tip.style.left = Math.min(event.clientX + 12, innerWidth - tip.offsetWidth - 8) + 'px';
    tip.style.top = (event.clientY - 36) + 'px';
  });

  fetch('/api/account/connections', {credentials: 'same-origin', cache: 'no-store'})
    .then(response => response.json().then(value => ({ok: response.ok, value})))
    .then(({ok, value}) => {
      if (!ok) throw new Error(value?.error || '불러오지 못했어요.');
      data = value;
      status.hidden = true;
      $('metricsBody').hidden = false;
      render();
    })
    .catch(error => { status.textContent = '지표를 불러오지 못했어요. ' + error.message; });
})();
