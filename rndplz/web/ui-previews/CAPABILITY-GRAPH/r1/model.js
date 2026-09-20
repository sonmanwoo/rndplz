(function (root) {
  'use strict';
  const norm = value => String(value ?? '').normalize('NFKC').toLocaleLowerCase().trim();
  const unique = values => [...new Set(values)];
  const asText = value => typeof value === 'string' ? value : Array.isArray(value) ? value.join(' · ') : '';
  const personDisplayName = person => typeof person?.originalName === 'string' && person.originalName.trim() ? person.originalName : String(person?.name || '');
  const personSupportingName = person => person?.name && norm(person.name) !== norm(personDisplayName(person)) ? person.name : '';
  function createModel(data) {
    if (!data || !Array.isArray(data.people) || !Array.isArray(data.records) || !Array.isArray(data.capabilities)) throw new Error('자료 형식이 올바르지 않습니다.');
    const people = new Map(data.people.map(item => [item.id, item]));
    const records = new Map(data.records.map(item => [item.id, item]));
    const capabilities = new Map(data.capabilities.map(item => [item.id, item]));
    const errors = [];
    if (people.size !== data.people.length || records.size !== data.records.length || capabilities.size !== data.capabilities.length) errors.push('중복 식별자');
    for (const person of people.values()) {
      if (!person.id || !person.name || !Array.isArray(person.recordIds)) errors.push('인물 필수 항목 누락: ' + person.id);
      for (const id of person.recordIds || []) if (!records.has(id)) errors.push('인물의 미등록 근거: ' + id);
    }
    for (const cap of capabilities.values()) {
      if (!cap.label || !Array.isArray(cap.people)) errors.push('분야 필수 항목 누락: ' + cap.id);
      for (const link of cap.people || []) {
        const person = people.get(link.id);
        if (!person) errors.push('분야의 미등록 인물: ' + link.id);
        if (!Array.isArray(link.recordIds) || !link.recordIds.length) errors.push('분야의 연결 근거 없음: ' + cap.id + '/' + link.id);
        for (const id of link.recordIds || []) if (!records.has(id) || !person?.recordIds.includes(id)) errors.push('다른 인물의 근거 연결: ' + cap.id + '/' + link.id + '/' + id);
      }
    }
    if (errors.length) throw new Error(errors.join('; '));
    const personCaps = id => data.capabilities.filter(cap => cap.people.some(link => link.id === id));
    const searchText = person => norm([person.name, person.originalName, ...(person.aliases || []), person.capabilityLine, ...personCaps(person.id).map(cap => cap.label)].join(' '));
    function visiblePeople(state = {}) {
      const query = norm(state.query);
      const cap = capabilities.get(state.capabilityId);
      const allowed = cap ? new Set(cap.people.map(link => link.id)) : null;
      return data.people.filter(person => (!allowed || allowed.has(person.id)) && (!query || searchText(person).includes(query)));
    }
    function visibleCapabilities(state = {}) {
      const ids = new Set(visiblePeople({query: state.query}).map(person => person.id));
      return data.capabilities.map(cap => ({...cap, visibleCount: unique(cap.people.map(link => link.id).filter(id => ids.has(id))).length}));
    }
    function personRecords(id) {
      return unique(people.get(id)?.recordIds || []).map(recordId => records.get(recordId)).filter(Boolean);
    }
    function recordRole(record, id) {
      return (record.people || []).find(person => person.id === id) || null;
    }
    function graph(state = {}) {
      const nodes = [], edges = [];
      const cap = capabilities.get(state.capabilityId);
      const visible = visiblePeople(state);
      const person = visible.find(item => item.id === state.personId);
      const addNode = (type, item, x, y, extra = {}) => {
        const node = {key: type + ':' + item.id, type, id: item.id, label: type === 'capability' ? item.label : type === 'person' ? personDisplayName(item) : item.title, supportingLabel: type === 'person' ? personSupportingName(item) : '', x, y, group: item.basisType === 'registered_record_topic' ? 'topic' : 'capability', ...extra};
        nodes.push(node); return node;
      };
      const addEdge = (from, to, type) => edges.push({from: from.key, to: to.key, type});
      if (person) {
        const p = addNode('person', person, 0, 0, {selected: true});
        const linkedCaps = cap ? [cap] : personCaps(person.id);
        linkedCaps.forEach((field, i) => {
          const hub = addNode('capability', field, -330, (i - (linkedCaps.length - 1) / 2) * 105, {count: unique(field.people.map(item => item.id)).length});
          addEdge(hub, p, 'field-person');
        });
        const linkedRecords = personRecords(person.id);
        const currentFieldRecords = cap ? new Set(cap.people.find(link => link.id === person.id)?.recordIds || []) : null;
        linkedRecords.forEach((record, i) => {
          const inField = !currentFieldRecords || currentFieldRecords.has(record.id);
          const n = addNode('record', record, 330, (i - (linkedRecords.length - 1) / 2) * 112, {evidenceScope: currentFieldRecords ? (inField ? 'direct' : 'other') : null});
          addEdge(p, n, inField ? 'person-record' : 'person-record-other');
        });
        return {mode: 'person', nodes, edges, visible, person, cap, title: personDisplayName(person) + '의 연결', subtitle: '선택한 한 사람의 전체 근거 ' + linkedRecords.length + '개' + (currentFieldRecords ? ' · 현재 분야의 근거 ' + currentFieldRecords.size + '개 / 다른 등록 기록 ' + (linkedRecords.length - currentFieldRecords.size) + '개' : '')};
      }
      if (cap || norm(state.query)) {
        const n = visible.length;
        const rootNode = cap ? addNode('capability', cap, 0, 0, {count: n}) : null;
        if (n === 1) {
          const p = addNode('person', visible[0], 270, 0); if (rootNode) addEdge(rootNode, p, 'field-person');
        } else {
          const radiusX = n < 7 ? 275 : 355;
          const radiusY = n < 7 ? 200 : Math.max(275, Math.ceil(n / 5) * 68);
          visible.forEach((item, i) => {
            const angle = -Math.PI / 2 + i / n * Math.PI * 2;
            const p = addNode('person', item, Math.cos(angle) * radiusX, Math.sin(angle) * radiusY);
            if (rootNode) addEdge(rootNode, p, 'field-person');
          });
        }
        return {mode: 'people', nodes, edges, visible, cap, title: cap?.label || '검색된 사람', subtitle: n + '명 · 사람을 고르면 근거가 펼쳐집니다'};
      }
      const fields = visibleCapabilities(state).filter(item => item.visibleCount);
      const cols = fields.length <= 8 ? 3 : 4;
      fields.forEach((field, i) => {
        const row = Math.floor(i / cols), col = i % cols;
        addNode('capability', field, (col - (cols - 1) / 2) * 235 + (row % 2 ? 26 : -12), row * 126, {count: field.visibleCount});
      });
      return {mode: 'overview', nodes, edges, visible, title: '관심 분야의 연결', subtitle: '분야를 펼쳐 자료로 연결된 사람을 살펴보세요'};
    }
    return {data, people, records, capabilities, visiblePeople, visibleCapabilities, personCaps, personRecords, recordRole, graph};
  }
  const api = {createModel, norm, asText, personDisplayName, personSupportingName};
  root.CapabilityGraphModel = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : window);
