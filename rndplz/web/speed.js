/* Connection speed check (/speed, 2026-10-12): this device's round trips to the 수소문 server, read only.
 * The numbers stay on this screen; nothing is stored or sent anywhere. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  // Model time per search on the server, measured 2026-10-12 (_work/tools/map-search-bench).
  const MODELS = [['임베딩', 10], ['로컬 Gemma', 220], ['사내 AI flash', 3400]];
  const TRIPS = 20;
  const ms = value => value == null || !isFinite(value) ? '—' : Math.round(value) + 'ms';
  const seconds = value => (value / 1000).toFixed(2) + '초';
  const at = (sorted, share) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * share))];
  let busy = false, lines = [];

  function row(host, label, value) {
    const term = document.createElement('dt'), detail = document.createElement('dd');
    term.textContent = label; detail.textContent = value; host.append(term, detail);
    lines.push(label + ': ' + value);
  }
  function section(id, title) { const host = $(id); host.replaceChildren(); lines.push('', '[' + title + ']'); return host; }

  function firstVisit() {
    const host = section('speedConnect', '처음 접속'), nav = performance.getEntriesByType('navigation')[0];
    if (!nav) { row(host, '첫 연결', '브라우저가 알려 주지 않아요'); return; }
    const connect = nav.connectEnd - nav.connectStart;
    row(host, '첫 연결(보안 연결 포함)', connect > 0 ? ms(connect) : '이미 열린 연결 사용');
    if (connect > 0 && nav.secureConnectionStart > 0) row(host, '그중 보안 연결(TLS)', ms(nav.connectEnd - nav.secureConnectionStart));
    row(host, '첫 응답까지', ms(nav.responseStart - nav.startTime));
    row(host, '페이지 받기 완료', ms(nav.responseEnd - nav.startTime));
  }

  async function trips() {
    const times = [];
    let failed = 0;
    for (let i = 0; i < TRIPS; i++) {
      $('speedStatus').textContent = '작은 요청 왕복을 재는 중… ' + (i + 1) + '/' + TRIPS;
      const started = performance.now();
      try {
        const response = await fetch('/healthz?n=' + i + '-' + Date.now(), {cache: 'no-store'});
        await response.text();
        if (response.ok) times.push(performance.now() - started); else failed++;
      } catch (_) { failed++; }
      await new Promise(done => setTimeout(done, 250));
    }
    const host = section('speedTrips', '작은 요청 ' + TRIPS + '번 왕복'), sorted = [...times].sort((a, b) => a - b);
    if (!sorted.length) { row(host, '결과', '서버에 닿지 못했어요'); $('speedRaw').textContent = ''; return null; }
    const median = at(sorted, .5), slow = at(sorted, .9);
    row(host, '보통(중앙값)', ms(median));
    row(host, '느린 쪽 10%', ms(slow));
    row(host, '가장 빠름 · 가장 느림', ms(sorted[0]) + ' · ' + ms(sorted[sorted.length - 1]));
    if (failed) row(host, '실패한 요청', failed + '번');
    $('speedRaw').textContent = '각 왕복(ms): ' + times.map(Math.round).join(' ');
    lines.push('각 왕복(ms): ' + times.map(Math.round).join(' '));
    return {median, slow};
  }

  async function mapData() {
    $('speedStatus').textContent = '연구 맵 자료를 받는 중…';
    const host = section('speedMap', '연구 맵 자료 받기'), started = performance.now();
    try {
      const response = await fetch('/api/people-map', {cache: 'no-store', credentials: 'same-origin'});
      const bytes = (await response.arrayBuffer()).byteLength;
      if (!response.ok) throw new Error();
      row(host, '걸린 시간', ms(performance.now() - started));
      row(host, '받은 크기', Math.round(bytes / 1024) + 'KB');
    } catch (_) { row(host, '결과', '받지 못했어요'); }
  }

  function search(trip) {
    const host = section('speedSearch', '연구 맵 검색어 확장의 예상 체감 시간');
    row(host, '지금 글자 검색', '즉시 (서버를 거치지 않음)');
    for (const [name, model] of MODELS) {
      row(host, name, trip ? '보통 ' + seconds(trip.median + model) + ' · 느릴 때 ' + seconds(trip.slow + model) : '—');
    }
  }

  function network() {
    const host = section('speedNetwork', '망 정보'), info = navigator.connection;
    if (!info) { row(host, '망 종류', '브라우저가 알려 주지 않아요'); return; }
    if (info.type) row(host, '연결 종류', info.type);
    if (info.effectiveType) row(host, '체감 등급', info.effectiveType);
    if (info.rtt != null) row(host, '브라우저 추정 왕복', ms(info.rtt));
    if (info.downlink != null) row(host, '브라우저 추정 속도', info.downlink + 'Mbps');
  }

  async function run() {
    if (busy) return;
    busy = true; $('speedAgain').disabled = true;
    lines = ['수소문 연결 속도 · ' + new Date().toLocaleString('ko-KR')];
    firstVisit();
    const trip = await trips();
    await mapData();
    search(trip);
    network();
    $('speedStatus').textContent = '다 쟀어요. 결과 복사로 옮길 수 있어요.';
    busy = false; $('speedAgain').disabled = false;
  }

  $('speedAgain').addEventListener('click', run);
  $('speedCopy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(lines.join('\n')); $('speedStatus').textContent = '결과를 복사했어요.'; }
    catch (_) { $('speedStatus').textContent = '복사하지 못했어요. 화면을 캡처해 주세요.'; }
  });
  run();
})();
