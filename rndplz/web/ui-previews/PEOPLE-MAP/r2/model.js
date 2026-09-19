/* PEOPLE-MAP r2: read-only adapter and pure preview state.
 * Consumes the fixed public-data contract; no network, storage or delivery.
 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./data.js'));
  else root.PeopleMapCore = factory(root.PeopleMapData);
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
    return ({ paper: '논문', preprint: '프리프린트', career_record: '제공 경력', site_record: '현장 기록' })[kind] || kind || '자료 종류 미기재';
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
  freeze(people);
  freeze(topics);
  freeze(data.source);
  freeze(data.counts);
  freeze(featuredIds);

  function initialState() {
    return {
      query: '', topic: '', view: 'experience', scope: 'featured',
      selectedId: null, evidenceIds: [], problem: '', draft: '',
      includeAi: false, aiText: '', draftEdited: false, draftNeedsReview: false,
      expandedGroups: [], page: 0, pageSize: 25
    };
  }
  function matches(state, person) {
    var query = key(state.query);
    return (state.scope === 'all' || person.featured) &&
      (!query || [person.name].concat(person.aliases).some(function (name) { return key(name).indexOf(query) !== -1; })) &&
      (!state.topic || person.topicIds.indexOf(state.topic) !== -1);
  }
  function visiblePeople(state) {
    state = state || initialState();
    if (state.scope === 'all') return people.filter(function (person) { return matches(state, person); });
    return featuredIds.map(function (id) { return peopleById.get(id); }).filter(function (person) {
      return person && matches(state, person);
    });
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
      return !state.topic || record.topics.indexOf(state.topic) !== -1;
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
    return '질문 대상: ' + person.name + '\n선택한 근거 ' + records.length + '건:\n' +
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
      view: input.view === 'organization' ? 'organization' : 'experience',
      scope: input.scope === 'all' ? 'all' : 'featured',
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
        state.query = ''; state.topic = ''; resetPage(state); break;
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
    people: people, topics: topics, counts: data.counts, source: data.source,
    featuredIds: featuredIds, initialState: initialState, visiblePeople: visiblePeople,
    visibleEvidence: visibleEvidence, selectedEvidence: selectedEvidence, reduce: reduce
  });
}));
