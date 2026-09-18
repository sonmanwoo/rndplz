(function () {
  "use strict";
  const data = window.CARD_FLIP_DATA;
  const gallery = document.getElementById("card-gallery");
  if (!data || !Array.isArray(data.people)) {
    gallery.innerHTML = '<p class="empty-state">카드 자료를 불러오지 못했습니다. data.js와 이미지를 함께 열어 주세요.</p>';
    return;
  }
  document.getElementById("release-id").textContent = data.id + " / r" + data.revision;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const people = new Map(data.people.map(person => [person.slug, person]));
  const variants = [
    { key: "standard", person: people.get("manwoo"), code: "01", title: "Standard Researcher", subtitle: "기본 연구자 카드", grade: "절제된 은빛 · 새틴 표면", recommended: false },
    { key: "gold", person: people.get("hinton"), code: "A", title: "Gold Laureate", subtitle: "금속 테두리 · 금박과 각인", grade: "노벨 수상 기념 · 골드 등급", recommended: true },
    { key: "prism", person: people.get("hinton"), code: "B", title: "Prism Laureate", subtitle: "다색 테두리 · 프리즘 회절", grade: "노벨 수상 기념 · 프리즘 등급", recommended: false }
  ];
  const state = [];
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function link(label, url) {
    const node = element("a", "", label);
    try {
      const parsed = new URL(url, location.href);
      if (!["https:", "http:"].includes(parsed.protocol)) return element("span", "", label);
      node.href = parsed.href;
      node.target = "_blank";
      node.rel = "noopener noreferrer";
      return node;
    } catch (_) { return element("span", "", label); }
  }
  function heading(container, title) { container.append(element("h4", "", title)); }
  function sourceList(container, sources) {
    if (!sources || !sources.length) return;
    const list = element("ul", "source-list");
    sources.forEach(source => {
      const item = element("li");
      item.append(link(source.label || source.title || "출처", source.url));
      list.append(item);
    });
    container.append(list);
  }
  function fillDetails(container, person) {
    heading(container, "연구의 방향");
    container.append(element("p", "lead", person.summary), element("p", "", person.biography));
    if (person.award) {
      heading(container, "수상 기록");
      const award = element("div", "award-panel");
      award.append(link(person.award.label, person.award.url), element("p", "", person.award.summary));
      container.append(award);
    }
    if (person.timeline && person.timeline.length) {
      heading(container, "주요 이력");
      const list = element("ul", "detail-list");
      person.timeline.forEach(entry => {
        const item = element("li");
        item.append(element("span", "detail-date", entry.date), element("p", "", entry.text));
        list.append(item);
      });
      container.append(list);
    }
    if (person.records && person.records.length) {
      heading(container, person.award ? "대표 연구 · 논문" : "직무 경력 근거");
      const list = element("ul", "detail-list");
      person.records.forEach(record => {
        const item = element("li");
        item.append(element("span", "detail-date", record.year));
        const title = record.url ? link(record.title, record.url) : element("span", "", record.title);
        title.className = "detail-title";
        item.append(title);
        if (record.kind) item.append(element("p", "source-note", record.kind));
        if (record.authors) item.append(element("p", "source-note", record.authors.join(" · ")));
        if (record.summary) item.append(element("p", "", record.summary));
        if (record.contribution) item.append(element("p", "source-note", record.contribution));
        list.append(item);
      });
      container.append(list);
    }
    heading(container, "출처 · 자료 기준");
    container.append(element("p", "source-note", person.sourceNote));
    sourceList(container, person.sources);
    container.append(element("p", "source-note", "자료 확인: " + (person.checkedAt || data.asOf)));
    heading(container, "이미지 제작 표시");
    container.append(element("p", "", person.imageLabel + " · " + person.imageCredit));
    if (person.portraitReference) {
      const ref = person.portraitReference;
      const paragraph = element("p", "source-note");
      paragraph.append(ref.url ? link(ref.label, ref.url) : document.createTextNode(ref.label));
      container.append(paragraph);
    }
    container.append(element("p", "source-note", "AI로 생성한 일러스트입니다. 배경 도식은 연구 분야의 상징이며 실제 실험 결과가 아닙니다."));
    if (person.award) container.append(element("p", "source-note", "수상 기념 등급은 연구자의 역량 점수나 협업 적합도를 뜻하지 않습니다."));
  }
  function resetLight(item) {
    item.card.style.setProperty("--rx", "0deg");
    item.card.style.setProperty("--ry", "0deg");
    item.card.style.setProperty("--mx", "50%");
    item.card.style.setProperty("--my", "45%");
    item.card.style.setProperty("--bx", "50%");
    item.card.style.setProperty("--by", "50%");
    item.card.style.setProperty("--intensity", "0");
    item.card.classList.remove("is-tracking", "is-demo");
  }
  function stopDemo(item) {
    if (item.frame) cancelAnimationFrame(item.frame);
    item.frame = 0;
    item.demo.setAttribute("aria-pressed", "false");
    resetLight(item);
  }
  function setLight(item, x, y, strength) {
    item.card.style.setProperty("--rx", ((0.5 - y) * 13).toFixed(2) + "deg");
    item.card.style.setProperty("--ry", ((x - 0.5) * 16).toFixed(2) + "deg");
    item.card.style.setProperty("--mx", (x * 100).toFixed(2) + "%");
    item.card.style.setProperty("--my", (y * 100).toFixed(2) + "%");
    item.card.style.setProperty("--bx", (20 + x * 60).toFixed(2) + "%");
    item.card.style.setProperty("--by", (20 + y * 60).toFixed(2) + "%");
    item.card.style.setProperty("--intensity", strength.toFixed(3));
  }
  function setFlipped(item, flipped) {
    stopDemo(item);
    item.flipped = flipped;
    item.card.dataset.flipped = String(flipped);
    item.card.classList.toggle("is-flipped", flipped);
    item.front.inert = flipped;
    item.back.inert = !flipped;
    item.front.setAttribute("aria-hidden", String(flipped));
    item.back.setAttribute("aria-hidden", String(!flipped));
    item.demo.disabled = flipped || reducedMotion.matches;
    item.frontFlip.setAttribute("aria-expanded", String(flipped));
    (flipped ? item.backFlip : item.frontFlip).focus({ preventScroll: true });
  }
  variants.forEach(variant => {
    const person = variant.person;
    if (!person) return;
    const column = element("div", "card-column");
    const label = element("header", "variant-heading " + variant.key);
    const labelText = element("div");
    const title = element("h2", "", variant.title);
    if (variant.recommended) title.append(element("span", "recommend", "추천"));
    labelText.append(title, element("p", "", variant.subtitle));
    label.append(labelText, element("span", "variant-code", variant.code));
    const card = element("article", "research-card");
    card.dataset.variant = variant.key;
    card.dataset.personId = person.id;
    card.dataset.flipped = "false";
    card.setAttribute("aria-label", person.name + " · " + variant.title);
    const tilt = element("div", "card-tilt");
    const flipper = element("div", "card-flipper");
    const front = element("section", "card-face card-front");
    front.setAttribute("aria-hidden", "false");
    const content = element("div", "front-content");
    const top = element("div", "front-top");
    const nameRow = element("div", "name-row");
    nameRow.append(element("h3", "person-name", person.name));
    if (person.award) nameRow.append(element("span", "nobel-year", "NOBEL " + person.award.year));
    const org = element("p", "person-org", person.org);
    org.title = person.org;
    top.append(nameRow, org);
    const portrait = element("div", "portrait-window");
    const img = element("img", "portrait");
    img.src = person.image;
    img.alt = person.name + " AI 일러스트";
    img.decoding = "async";
    img.width = 1086;
    img.height = 1448;
    portrait.append(img, element("span", "image-label", person.imageLabel));
    const bottom = element("div", "front-bottom");
    const tags = element("div", "tags");
    (person.tags || []).slice(0, 2).forEach(tag => tags.append(element("span", "field-tag", tag)));
    const hint = element("div", "flip-hint");
    hint.append(element("span", "", "상세 정보 · 카드 뒤집기"), element("span", "", "↗"));
    bottom.append(tags, hint);
    content.append(top, portrait, bottom);
    const frontFlip = element("button", "face-hit");
    frontFlip.type = "button";
    frontFlip.dataset.action = "flip";
    frontFlip.setAttribute("aria-label", person.name + " 상세 정보 보기 · " + variant.title + " 카드 뒤집기");
    frontFlip.setAttribute("aria-expanded", "false");
    front.append(content);
    ["foil-texture", "foil-sheen", "foil-glare"].forEach(name => {
      const layer = element("div", name);
      layer.setAttribute("aria-hidden", "true");
      front.append(layer);
    });
    front.append(frontFlip);
    const back = element("section", "card-face card-back");
    back.id = "details-" + variant.key;
    frontFlip.setAttribute("aria-controls", back.id);
    back.inert = true;
    back.setAttribute("aria-hidden", "true");
    const backContent = element("div", "back-content");
    const backHeader = element("div", "back-header");
    backHeader.append(element("p", "back-kicker", variant.title.toUpperCase() + " / RESEARCH PROFILE"), element("h3", "", person.name), element("p", "alternate", person.alternateName));
    const scroll = element("div", "back-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", person.name + " 상세 정보 · 스크롤");
    fillDetails(scroll, person);
    const backActions = element("div", "back-actions");
    const backFlip = element("button", "back-flip", "↶ 앞면으로 돌아가기");
    backFlip.type = "button";
    backFlip.dataset.action = "flip";
    backFlip.setAttribute("aria-label", person.name + " 카드 앞면으로 돌아가기 · " + variant.title);
    backActions.append(backFlip);
    backContent.append(backHeader, scroll, backActions);
    back.append(backContent);
    flipper.append(front, back);
    tilt.append(flipper);
    card.append(tilt);
    const tools = element("div", "card-tools");
    const demo = element("button", "demo-button", "✧ 빛 살펴보기");
    demo.type = "button";
    demo.dataset.action = "demo";
    demo.setAttribute("aria-label", variant.title + " 빛 살펴보기");
    demo.setAttribute("aria-pressed", "false");
    demo.setAttribute("aria-describedby", "motion-note");
    tools.append(element("p", "grade-note", variant.grade), demo);
    column.append(label, card, tools);
    gallery.append(column);
    const item = { card, front, back, frontFlip, backFlip, demo, flipped: false, frame: 0 };
    state.push(item);
    frontFlip.addEventListener("click", () => setFlipped(item, true));
    backFlip.addEventListener("click", () => setFlipped(item, false));
    card.addEventListener("keydown", event => {
      if (event.key === "Escape" && item.flipped) {
        event.preventDefault();
        setFlipped(item, false);
      }
    });
    card.addEventListener("pointermove", event => {
      if (event.pointerType === "touch" || reducedMotion.matches || item.flipped || item.frame) return;
      const rect = card.getBoundingClientRect();
      const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
      card.classList.add("is-tracking");
      setLight(item, x, y, 1);
    });
    card.addEventListener("pointerleave", () => { if (!item.frame) resetLight(item); });
    demo.addEventListener("click", () => {
      if (reducedMotion.matches || item.flipped) return;
      if (item.frame) { stopDemo(item); return; }
      const started = performance.now();
      card.classList.add("is-demo");
      demo.setAttribute("aria-pressed", "true");
      const tick = now => {
        const p = Math.min(1, (now - started) / 1750);
        if (p >= 1 || reducedMotion.matches || item.flipped) { stopDemo(item); return; }
        const envelope = Math.sin(Math.PI * p);
        setLight(item, 0.5 + Math.cos(p * Math.PI * 2) * 0.42 * envelope, 0.5 + Math.sin(p * Math.PI * 2) * 0.38 * envelope, envelope);
        item.frame = requestAnimationFrame(tick);
      };
      item.frame = requestAnimationFrame(tick);
    });
  });
  function syncMotionPreference() {
    state.forEach(item => {
      stopDemo(item);
      item.demo.disabled = reducedMotion.matches || item.flipped;
      item.demo.title = reducedMotion.matches ? "움직임 줄이기 설정에서 빛 시연이 꺼집니다." : "";
    });
    document.getElementById("motion-note").textContent = reducedMotion.matches
      ? "움직임 줄이기 설정을 적용했습니다. 기울기·빛 시연 없이 카드를 즉시 뒤집습니다. Enter·Space로 전환하고 Esc로 앞면에 돌아옵니다."
      : "카드 위에서 빛을 움직이거나, 아래 버튼으로 짧게 살펴보세요. Enter·Space로 뒤집고 Esc로 앞면에 돌아옵니다.";
  }
  reducedMotion.addEventListener("change", syncMotionPreference);
  document.addEventListener("visibilitychange", () => { if (document.hidden) state.forEach(stopDemo); });
  syncMotionPreference();
})();
