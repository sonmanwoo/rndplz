/* PEOPLE-MAP r2: read-only service-data adapter and pure page state.
 * Consumes the complete service-data contract; no network, storage or delivery.
 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else root.createPeopleMapModel = factory;
}(typeof window !== 'undefined' ? window : globalThis, function (data) {
  'use strict';
  if (!data || data.schema_version !== 'people-map-existing-v1' ||
      !Array.isArray(data.people) || !Array.isArray(data.topics) || !Array.isArray(data.featured_ids)) {
    throw new TypeError('The fixed PEOPLE-MAP public-data contract is required.');
  }

  function freeze(value) {
    if (value && typeof value === 'object' && !Object.isFrozen(value)) {
      Object.keys(value).forEach(function (key) { freeze(value[key]); });
      Object.freeze(value);
    }
    return value;
  }
  function text(value) { return typeof value === 'string' ? value : ''; }
  function original(value) { return value === undefined ? null : value; }
  function unique(values) {
    return values.filter(function (value, index) { return values.indexOf(value) === index; });
  }
  function key(value) { return text(value).normalize('NFKC').replace(/\s+/g, '').toLocaleLowerCase('ko'); }
  var topics = data.topics.slice();
  var topicIds = new Set(topics.map(function (topic) { return topic.id; }));
  var featuredIds = data.featured_ids.slice();
  var featuredSet = new Set(featuredIds);
  function recordTopics(record) {
    return unique((Array.isArray(record.tags) ? record.tags : []).map(function (tag) {
      return typeof tag === 'string' ? tag : tag && tag.id;
    }).filter(function (id) { return typeof id === 'string' && topicIds.has(id); }));
  }
  function typeLabel(kind) {
    return ({ paper: '논문', patent_record: '제공 특허 목록', preprint: '프리프린트', career_record: '제공 경력', public_profile_record: '공개 경력·학력', project_record: '제공 프로젝트 이력', site_record: '현장 기록' })[kind] || kind || '자료 종류 미기재';
  }
  function normalizePortrait(value) {
    if (!value || typeof value !== 'object') return null;
    return {
      path: original(value.path), generated: original(value.generated),
      label: original(value.label), sourcePortrait: value
    };
  }
  function normalizeAwards(value) {
    if (!value) return [];
    return (Array.isArray(value) ? value : [value]).map(function (award) {
      if (typeof award === 'string') return { label: award, year: null, sourceUrl: null, sourceAward: award };
      return {
        label: original(award.label_ko || award.label || award.name || award.title),
        year: original(award.year),
        sourceUrl: original(award.facts_url || award.sourceUrl || award.source_url || award.url),
        sourceAward: award
      };
    });
  }
  function stableValue(value) {
    if (Array.isArray(value)) return value.map(stableValue);
    if (value && typeof value === 'object') {
      var ordered = {};
      Object.keys(value).sort().forEach(function (name) { ordered[name] = stableValue(value[name]); });
      return ordered;
    }
    return value;
  }
  function recordGroups(records, personId) {
    var groups = new Map();
    records.forEach(function (record) {
      var group = groups.get(record.id);
      if (!group) groups.set(record.id, [record]);
      else {
        if (JSON.stringify(stableValue(group[0])) !== JSON.stringify(stableValue(record))) {
          throw new TypeError('Conflicting evidence variants: ' + personId + ' / ' + record.id);
        }
        group.push(record);
      }
    });
    return Array.from(groups.values());
  }
  function normalizePerson(person) {
    var profile = person.profile && typeof person.profile === 'object' ? person.profile : {};
    var name = text(person.name) || text(person.display_name);
    var aliases = unique((Array.isArray(person.aliases) ? person.aliases.slice() : []).concat(
      person.display_name && person.display_name !== name ? [person.display_name] : []
    ).filter(function (alias) { return typeof alias === 'string'; }));
    return {
      id: person.id, name: name, originalName: original(person.name), aliases: aliases,
      initial: Array.from(name)[0] || '',
      organization: original(person.org),
      organizationGroupName: original(person.org_name),
      organizationNote: [text(person.org_basis), person.org_as_of ? '기준일: ' + person.org_as_of : '소속 기준일 미기재'].filter(Boolean).join(' · '),
      organizationAsOf: original(person.org_as_of),
      currentRole: original(profile.current_role),
      virtual: person.virtual === true,
      featured: featuredSet.has(person.id),
      recordCount: original(person.record_count),
      personConfirmed: original(person.person_confirmed),
      topicIds: Array.isArray(person.topic_ids) ? person.topic_ids.slice() : [],
      portrait: normalizePortrait(profile.portrait),
      awards: normalizeAwards(profile.award),
      records: recordGroups(Array.isArray(person.evidence) ? person.evidence : [], person.id).map(function (group) {
        var record = group[0];
        return {
          id: record.id, title: original(record.title), type: original(record.kind),
          typeLabel: typeLabel(record.kind), role: original(record.role),
          recordDate: original(record.date), period: original(record.period),
          organization: original(record.organization),
          sourceUrl: original(record.url), sourceLabel: original(record.source_label),
          topics: recordTopics(record),
          summary: original(record.summary), provenance: original(record.provenance),
          sourceRecord: record, sourceRecords: group, duplicateCount: group.length
        };
      }),
      sourceProfile: profile,
      sourcePerson: person
    };
  }
  var people = data.people.map(normalizePerson);
  var peopleById = new Map(people.map(function (person) { return [person.id, person]; }));
  if (peopleById.size !== people.length) throw new TypeError('Person IDs must be unique.');

  // Source-linked presentation categories from approved CAPABILITY-PROPOSALS r1.
  // Each link is intersected with the same person's current records at runtime.
  var capabilityDefinitions = [{"id":"catalyst","label":"촉매 설계·반응 평가","description":"촉매를 설계하고, 어떤 조건에서 반응하는지 살피는 일.","people":[{"id":"LOCAL-JINHO","scope":"CO₂ 전환 촉매 설계·제법 개발과 반응 활성 평가","recordIds":["CAREER-JO-CO2J","CAREER-JO-CO2L","CAREER-JO-ENERGY"]},{"id":"PUB-NORSKOV","scope":"표면 반응 계산을 통한 고체 촉매 설계","recordIds":["PUB-PAPER-NORSKOV"]},{"id":"PUB-ERTL","scope":"표면화학·촉매 관련 연구 자료","recordIds":["GS-PAPER-GERHARD-ERTL-2008-1"]},{"id":"PUB-RYOO","scope":"표면화학·촉매 관련 연구 자료","recordIds":["GS-PAPER-RYONG-RYOO-2009-1"]},{"id":"PUB-PARK-JY","scope":"표면화학·촉매 관련 연구 자료","recordIds":["GS-PAPER-JEONG-YOUNG-PARK-2025-1"]},{"id":"PUB-HARTWIG","scope":"표면화학·촉매 관련 연구 자료","recordIds":["GS-PAPER-JOHN-F-HARTWIG-2024-1"]},{"id":"PUB-SHAO-HORN","scope":"표면화학·촉매 관련 연구 자료","recordIds":["GS-PAPER-YANG-SHAO-HORN-2011-1"]},{"id":"LOCAL-HONG","scope":"촉매·바이오매스 전환 및 배출가스 저감 논문 · 사용자 제공 연구 목록","recordIds":["PAPER-HY-2014-01","PAPER-HY-2014-02","PAPER-HY-2010-03"]}]},{"id":"separation","label":"분리·정제와 품질 개선","description":"혼합물에서 필요한 성분을 분리하고 제품 품질을 개선하는 일.","people":[{"id":"LOCAL-MANWOO","scope":"증류·흡착·수소화 기반 탈색·탈취, 증류·추출 실험","recordIds":["CAREER-MW-BIO","CAREER-MW-MONOMER"]},{"id":"PUB-NAIR","scope":"나노튜브의 분자 흡착 선택성 연구","recordIds":["GS-PAPER-SANKAR-NAIR-2014-1"]},{"id":"PUB-YAGHI","scope":"이산화탄소 포집·분리 관련 연구 자료","recordIds":["GS-PAPER-OMAR-M-YAGHI-2024-1"]}]},{"id":"process","label":"공정 모델링·최적화","description":"공정을 모델로 이해하고, 더 나은 운전 조건을 찾는 일.","people":[{"id":"LOCAL-MANWOO","scope":"모노머 공정 모델링·최적화와 실험 데이터 분석","recordIds":["CAREER-MW-MONOMER","CAREER-MW-BIO"]},{"id":"PUB-GROSSMANN","scope":"혼합정수 비선형·논리 분기 최적화","recordIds":["PUB-PAPER-GROSSMANN"]},{"id":"PUB-MACCHIETTO","scope":"원유 예열망·침적·세정 주기의 동적 모델","recordIds":["EXP02-PAPER-SANDRO-MACCHIETTO-2011-1","EXP02-PAPER-SANDRO-MACCHIETTO-2016-2"]}]},{"id":"control","label":"예측 제어·운전 안정화","description":"제약과 불확실성을 고려해 공정을 제어하는 일.","people":[{"id":"PUB-RAWLINGS","scope":"화학공정의 모델 예측 제어와 입력 제약","recordIds":["EXP02-PAPER-RAWLINGS-1992-1"]},{"id":"PUB-MORARI","scope":"불확실성과 입출력 제약을 고려한 강인 MPC","recordIds":["EXP02-PAPER-MORARI-1996-1","EXP02-PAPER-MORARI-1999-2"]}]},{"id":"cooling","label":"냉각 유체 선별·열성능 평가","description":"냉각 유체와 구조가 열을 어떻게 전달하는지 평가하는 일.","people":[{"id":"PUB-JOSHI","scope":"유기규소 냉각유 선별·풀비등 평가와 단상 열성능 수치해석","recordIds":["EXP02-PAPER-YOGENDRA-JOSHI-2012-1","EXP02-PAPER-YOGENDRA-JOSHI-2025-1"]},{"id":"PUB-MUDAWAR","scope":"절연액 비등과 액침 냉각 모듈 연구","recordIds":["EXP02-PAPER-ISSAM-MUDAWAR-1989-1","EXP02-PAPER-ISSAM-MUDAWAR-1994-2"]}]},{"id":"saf","label":"SAF 생산·연료 평가","description":"대체 원료의 항공유 전환 경로와 연료 특성을 살피는 일.","people":[{"id":"LOCAL-JINHO","scope":"Lab 규모 CO₂ 전환 SAF 촉매 공정 개발","recordIds":["CAREER-JO-CO2J"]},{"id":"PUB-HEYNE","scope":"폐기물 유래 원료 전환과 SAF 사전 평가","recordIds":["EXP02-PAPER-HEYNE-2021-1","EXP02-PAPER-HEYNE-2021-2"]},{"id":"PUB-MCCORMICK","scope":"수소처리 기반 항공유 생산과 점화 품질 평가","recordIds":["EXP02-PAPER-MCCORMICK-2024-1","EXP02-PAPER-MCCORMICK-2025-2"]}]},{"id":"fouling","label":"파울링 진단·세정 주기 해석","description":"침적이 운전에 미치는 영향을 읽고 세정 주기를 해석하는 일.","people":[{"id":"PUB-WILSON-DI","scope":"침전층 노화와 열부하·압력손실의 관계","recordIds":["EXP02-PAPER-D-IAN-WILSON-2020-1"]},{"id":"PUB-MACCHIETTO","scope":"원유 침적층 변화와 세정·재침적 주기의 모델링","recordIds":["EXP02-PAPER-SANDRO-MACCHIETTO-2016-2"]}]},{"id":"robotics","label":"로봇 동작·장애물 회피","description":"로봇팔과 이동 로봇이 장애물을 피하도록 움직임을 설계하는 일.","people":[{"id":"PUB-KHATIB","scope":"인공 포텐셜 필드를 이용한 실시간 장애물 회피","recordIds":["EXP02-PAPER-KHATIB-1986-1"]}]},{"id":"lubricants","label":"산업용 윤활유 제품 개발","description":"제공된 경력에서 산업용 윤활유 제품 개발 업무를 확인하는 분류.","people":[{"id":"LOCAL-DASOL","scope":"산업용 윤활유 제품 개발 · 제공 경력","recordIds":["CAREER-DS-LUBE"]}]},{"id":"rd-commercialization","label":"R&D 전략·신기술 사업화","description":"공개 경력에서 연구조직 보직과 신기술 사업 협력 참여를 확인하는 분류.","people":[{"id":"PUB-KWON-YOUNGWOON","scope":"화학 R&D 전략·사업화 관련 보직과 화이트바이오 사업 협력 참여","recordIds":["PUBLIC-KWON-LG-RND","PUBLIC-KWON-GS-ROLE","PUBLIC-KWON-WHITEBIO-COLLABORATION"]}]}];
  var capabilities = capabilityDefinitions.map(function (definition) {
    return {id: definition.id, label: definition.label, description: definition.description,
      people: definition.people.map(function (link) {
        var person = peopleById.get(link.id);
        var available = new Set(person ? person.records.map(function (r) { return r.id; }) : []);
        return {id: link.id, scope: link.scope, recordIds: link.recordIds.filter(function (id) { return available.has(id); })};
      }).filter(function (link) { return link.recordIds.length; })};
  });
  // Project participation shares the filter UI, not an expertise classification.
  // Resolve every person and edge from the same currently exposed project record.
  var projectCategories = new Map();
  people.forEach(function (person) {
    if (person.sourcePerson.team_member !== true) return;
    var ids = Array.isArray(person.sourcePerson.team_project_ids) ? person.sourcePerson.team_project_ids : [];
    unique(ids).forEach(function (id) {
      var record = person.records.find(function (item) { return item.id === id && item.type === 'project_record'; });
      if (!record || !text(record.title)) return;
      var category = projectCategories.get(id);
      if (!category) {
        category = {id: 'project:' + id, kind: 'project', label: record.title,
          description: [record.recordDate, record.title, '참여 멤버'].filter(Boolean).join(' '), people: []};
        projectCategories.set(id, category);
      }
      if (category.label !== record.title) throw new TypeError('Conflicting project title: ' + id);
      category.people.push({id: person.id, kind: 'project', scope: '사용자 제공 프로젝트 참여 정보 · 역할·성과 미기재', recordIds: [record.id]});
    });
  });
  projectCategories.forEach(function (category) { capabilities.push(category); });
  freeze(capabilities);
  function capabilityLink(state, person) {
    var capability = capabilities.find(function (item) { return item.id === state.capability; });
    return capability && capability.people.find(function (link) { return link.id === person.id; });
  }

  freeze(people);
  freeze(topics);
  freeze(data.source);
  freeze(data.counts);
  freeze(featuredIds);

  function initialState() {
    return {
      query: '', topic: '', capability: '', view: 'experience', scope: 'all',
      selectedId: null, evidenceIds: [], problem: '', draft: '',
      includeAi: false, aiText: '', draftEdited: false, draftNeedsReview: false,
      expandedGroups: [], page: 0, pageSize: 25
    };
  }
  function matches(state, person) {
    var query = key(state.query);
    return true &&
      (!query || [person.name].concat(person.aliases).some(function (name) { return key(name).indexOf(query) !== -1; })) &&
      (!state.capability || Boolean(capabilityLink(state, person))) &&
      (!state.topic || person.records.some(function (record) {
        var link = capabilityLink(state, person);
        return record.topics.indexOf(state.topic) !== -1 && (!state.capability || link && (link.kind === 'project' || link.recordIds.indexOf(record.id) !== -1));
      }));
  }
  function visiblePeople(state) {
    state = state || initialState();
    return people.filter(function (person) { return matches(state, person); });
  }
  function getPerson(state, person) {
    var id = typeof person === 'string' ? person : person && person.id;
    var found = peopleById.get(id || state.selectedId);
    return found && matches(state, found) ? found : null;
  }
  function visibleEvidence(state, person) {
    state = state || initialState();
    var found = getPerson(state, person);
    if (!found) return [];
    return found.records.filter(function (record) {
      var link = capabilityLink(state, found);
      return (!state.capability || link && (link.kind === 'project' || link.recordIds.indexOf(record.id) !== -1)) &&
        (!state.topic || record.topics.indexOf(state.topic) !== -1);
    });
  }
  function selectedEvidence(state, person) {
    state = state || initialState();
    var found = getPerson(state, person);
    if (!found || found.id !== state.selectedId) return [];
    var selectedIds = Array.isArray(state.evidenceIds) ? state.evidenceIds : [];
    return visibleEvidence(state, found).filter(function (record) { return selectedIds.indexOf(record.id) !== -1; });
  }
  function printable(value) {
    if (value === null || value === undefined || value === '') return '미기재';
    return typeof value === 'string' ? value : JSON.stringify(value);
  }
  function neutralDraft(state, person) {
    var records = selectedEvidence(state, person);
    if (!records.length) return '';
    var profile = person.sourceProfile || {}, status = profile.current_status || {};
    var historical = profile.display_type === 'historical_researcher' || profile.affiliation_status === 'deceased' || status.category === 'deceased';
    return (historical ? '자료의 연구자: ' : '질문 대상: ') + person.name + '\n선택한 근거 ' + records.length + '건:\n' +
      records.map(function (record) {
        return '- ' + printable(record.title) + ' [' + record.id + ']' +
          '\n  기재 역할: ' + printable(record.role) +
          '\n  자료 날짜/기재 기간 원문: ' + printable(record.recordDate) +
          '\n  해석 한계: ' + printable(record.sourceRecord.boundary);
      }).join('\n') +
      '\n\n위 자료에 기재된 역할과 조건 중 현재 문제를 검토할 때 확인할 점과 추가 확인이 필요한 부분은 무엇인가요?';
  }
  function clearSelection(state) {
    return Object.assign({}, state, {
      selectedId: null, evidenceIds: [], problem: '', draft: '', includeAi: false,
      aiText: '', draftEdited: false, draftNeedsReview: false
    });
  }
  function sameIds(left, right) {
    return left.length === right.length && left.every(function (id) { return right.indexOf(id) !== -1; });
  }
  function changeEvidence(state, ids, person) {
    var oldIds = state.evidenceIds;
    state.evidenceIds = ids;
    if (!ids.length) {
      state.draft = '';
      state.draftEdited = false;
      state.draftNeedsReview = false;
      state.includeAi = false;
      state.aiText = '';
    } else if (!sameIds(oldIds, ids)) {
      state.includeAi = false;
      state.aiText = '';
      if (state.draftEdited) state.draftNeedsReview = true;
      else {
        state.draft = neutralDraft(state, person);
        state.draftNeedsReview = false;
      }
    }
    return state;
  }
  function sanitize(input) {
    var state = {
      query: text(input.query), topic: text(input.topic),
      capability: capabilities.some(function (item) { return item.id === input.capability; }) ? input.capability : '',
      view: input.view === 'organization' ? 'organization' : 'experience',
      scope: 'all',
      selectedId: text(input.selectedId) || null,
      evidenceIds: unique(Array.isArray(input.evidenceIds) ? input.evidenceIds.filter(function (id) { return typeof id === 'string'; }) : []),
      problem: text(input.problem), draft: text(input.draft),
      includeAi: input.includeAi === true, aiText: text(input.aiText),
      draftEdited: input.draftEdited === true, draftNeedsReview: input.draftNeedsReview === true,
      expandedGroups: unique(Array.isArray(input.expandedGroups) ? input.expandedGroups.filter(function (id) { return typeof id === 'string'; }) : []),
      page: Number.isInteger(input.page) && input.page > 0 ? input.page : 0, pageSize: 25
    };
    state.page = Math.min(state.page, Math.max(0, Math.ceil(visiblePeople(state).length / state.pageSize) - 1));
    var person = getPerson(state);
    if (!person) return clearSelection(state);
    var permitted = visibleEvidence(state, person);
    var keptIds = permitted.filter(function (record) { return state.evidenceIds.indexOf(record.id) !== -1; }).map(function (record) { return record.id; });
    state = changeEvidence(state, unique(keptIds), person);
    if (!permitted.length) state.problem = '';
    if (!state.includeAi) state.aiText = '';
    return state;
  }
  function resetPage(state) { state.page = 0; state.expandedGroups = []; }
  function reduce(input, action) {
    var state = sanitize(input || initialState());
    action = action || {};
    var person = getPerson(state);
    switch (action.type) {
      case 'QUERY':
        state.query = text(action.value); resetPage(state); break;
      case 'CAPABILITY':
        state.capability = text(action.value); resetPage(state); break;
      case 'TOPIC':
        state.topic = text(action.value); resetPage(state); break;
      case 'SCOPE':
        if (action.value === 'all' || action.value === 'featured') {
          state.scope = action.value; resetPage(state);
        }
        break;
      case 'VIEW':
        if (action.value === 'experience' || action.value === 'organization') {
          state.view = action.value; resetPage(state);
        }
        break;
      case 'PAGE':
        if (Number.isInteger(action.value) && action.value >= 0) state.page = action.value;
        break;
      case 'SELECT':
        var candidate = getPerson(state, action.id);
        if (candidate && candidate.id !== state.selectedId) {
          state = clearSelection(state); state.selectedId = candidate.id;
        }
        if (candidate) {
          state.page = Math.floor(visiblePeople(state).findIndex(function (item) { return item.id === candidate.id; }) / state.pageSize);
        }
        break;
      case 'EVIDENCE':
        if (person && (!action.personId || action.personId === person.id) &&
            visibleEvidence(state, person).some(function (record) { return record.id === action.id; })) {
          var next = state.evidenceIds.slice();
          if (action.checked === true && next.indexOf(action.id) === -1) next.push(action.id);
          else if (action.checked === false) next = next.filter(function (id) { return id !== action.id; });
          state = changeEvidence(state, next, person);
        }
        break;
      case 'PROBLEM':
        if (person && visibleEvidence(state, person).length) state.problem = text(action.value);
        break;
      case 'DRAFT':
        if (person && state.evidenceIds.length) { state.draft = text(action.value); state.draftEdited = true; }
        break;
      case 'ACK_DRAFT_CONTEXT':
        if (person && state.evidenceIds.length) state.draftNeedsReview = false;
        break;
      case 'RESET_DRAFT':
        if (person && state.evidenceIds.length) {
          state.draft = neutralDraft(state, person); state.draftEdited = false; state.draftNeedsReview = false;
        }
        break;
      case 'INCLUDE_AI':
        if (person && state.evidenceIds.length) {
          if (action.value === true && !state.includeAi) { state.includeAi = true; state.aiText = ''; }
          else if (action.value === false) { state.includeAi = false; state.aiText = ''; }
        }
        break;
      case 'AI_TEXT':
        if (person && state.evidenceIds.length && state.includeAi) state.aiText = text(action.value);
        break;
      case 'CLEAR_FILTERS':
        state.query = ''; state.topic = ''; state.capability = ''; state.scope = 'all'; resetPage(state); break;
      case 'CLEAR_TOPIC':
        state.topic = ''; resetPage(state); break;
      case 'CLOSE_DETAIL':
        state = clearSelection(state); break;
      case 'TOGGLE_GROUP':
        if (typeof action.id === 'string' && action.id) {
          state.expandedGroups = state.expandedGroups.indexOf(action.id) === -1
            ? state.expandedGroups.concat([action.id])
            : state.expandedGroups.filter(function (id) { return id !== action.id; });
        }
        break;
      case 'COLLAPSE_GROUPS':
        state.expandedGroups = []; break;
      default: break;
    }
    return sanitize(state);
  }
  return Object.freeze({
    people: people, topics: topics, capabilities: capabilities, capabilityLink: capabilityLink, counts: data.counts, source: data.source,
    featuredIds: featuredIds, initialState: initialState, visiblePeople: visiblePeople,
    visibleEvidence: visibleEvidence, selectedEvidence: selectedEvidence, reduce: reduce
  });
}));
