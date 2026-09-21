/* Spatial adapter for the existing people-map model.
 * The canonical model owns filtering, evidence, selection and question drafts.
 * Layout position and adjacency do not assert individual skill or availability.
 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./people-map-layout.js'));
  else root.createPeopleMapGraph = factory(root.RndPeopleMapLayout);
}(typeof window !== 'undefined' ? window : globalThis, function (Layout) {
  'use strict';
  // Display hubs only; all original product topics remain available to its reducer.
  // No preview person, record, capability membership or translated label is copied.
  const TOPIC_HUB_IDS = Object.freeze([
    'GS-SURFACE', 'GS-POROUS', 'GS-POLYMER', 'GS-TRIBOLOGY', 'GS-CIRCULAR',
    'BIO-ENZYME', 'GS-ELECTRO', 'GS-CO2-CAPTURE', 'GS-PROCESS-AI'
  ]);
  const unique = values => [...new Set(values)];
  const clone = value => JSON.parse(JSON.stringify(value));

  return function createPeopleMapGraph(C) {
    if (!Layout || typeof Layout.arrange !== 'function') throw new TypeError('Load people-map-layout.js before people-map-graph.js.');
    if (!C || !Array.isArray(C.capabilities) || !Array.isArray(C.topics) || typeof C.visiblePeople !== 'function' || typeof C.visibleEvidence !== 'function' || typeof C.capabilityLink !== 'function' || typeof C.initialState !== 'function') {
      throw new TypeError('The canonical people-map model is required.');
    }
    const topicById = new Map(C.topics.map(topic => [topic.id, {...topic, label: topic.name}]));
    const topicFields = TOPIC_HUB_IDS.map(id => topicById.get(id)).filter(Boolean);
    const cache = new Map();

    function graph(state) {
      state = state || C.initialState();
      const visible = C.visiblePeople(state);
      const evidenceByPerson = new Map(visible.map(person => [person.id, C.visibleEvidence(state, person)]));
      const nodes = [], edges = [];

      function addField(field, kind, links) {
        if (!links.length) return;
        const key = kind + ':' + field.id;
        const relationKind = field.kind === 'project' ? 'project' : kind;
        const basisType = relationKind === 'project' ? 'user_provided_project_participation' : kind === 'topic' ? 'registered_record_topic' : 'verified_seed_record_links';
        nodes.push({key, type: 'capability', kind: relationKind, id: field.id, label: field.label,
          group: relationKind, basisType, count: links.length,
          filter: {type: kind === 'topic' ? 'TOPIC' : 'CAPABILITY', value: field.id},
          x: 0, y: 0, ...Layout.SIZE.capability});
        links.forEach(link => edges.push({
          key: 'field-person:' + kind + ':' + field.id + ':' + link.id,
          from: key, to: 'person:' + link.id, type: 'field-person', kind: relationKind,
          capabilityId: kind === 'capability' ? field.id : null,
          topicId: kind === 'topic' ? field.id : null,
          personId: link.id, recordIds: unique(link.recordIds),
          scope: link.scope || '', scopeType: basisType
        }));
      }

      C.capabilities.forEach(capability => {
        const links = visible.map(person => {
          const link = C.capabilityLink({...state, capability: capability.id}, person);
          if (!link) return null;
          const allowed = new Set(evidenceByPerson.get(person.id).map(record => record.id));
          const recordIds = link.recordIds.filter(id => allowed.has(id));
          return recordIds.length ? {id: person.id, recordIds, scope: link.scope} : null;
        }).filter(Boolean);
        addField(capability, 'capability', links);
      });

      topicFields.forEach(topic => {
        const links = visible.map(person => {
          const recordIds = evidenceByPerson.get(person.id)
            .filter(record => record.topics.includes(topic.id)).map(record => record.id);
          return recordIds.length ? {id: person.id, recordIds, scope: '등록 자료 주제: ' + topic.label} : null;
        }).filter(Boolean);
        addField(topic, 'topic', links);
      });

      visible.forEach(person => nodes.push({key: 'person:' + person.id, type: 'person', kind: 'person',
        id: person.id, label: person.name, supportingLabel: '', group: 'person',
        filter: null, x: 0, y: 0, ...Layout.SIZE.person}));

      // State cannot expand people via a hub's neighbours. Include the visible
      // evidence even when it currently has no display hub; not just person IDs.
      const cacheKey = JSON.stringify({query: state.query || '', capability: state.capability || '', topic: state.topic || '',
        people: visible.map(person => [person.id, evidenceByPerson.get(person.id).map(record => [record.id, record.topics])]),
        edges: edges.map(edge => [edge.key, edge.recordIds])});
      let geometry = cache.get(cacheKey);
      if (!geometry) {
        geometry = Layout.arrange(nodes, edges);
        if (cache.size >= 32) cache.delete(cache.keys().next().value);
        cache.set(cacheKey, geometry);
      }
      const cap = C.capabilities.find(item => item.id === state.capability) || null;
      const topic = topicById.get(state.topic) || null;
      return {mode: 'spatial', ...clone(geometry), visible, cap, topic, cacheKey,
        title: [cap && cap.label, topic && topic.label].filter(Boolean).join(' · ') || (state.query ? '검색된 연구 경험' : '연구 경험의 연결'),
        subtitle: visible.length + '명 · 근거가 있는 분야 연결'};
    }

    return Object.freeze({graph, capabilities: C.capabilities, topics: C.topics,
      topicHubIds: TOPIC_HUB_IDS, topicFields: Object.freeze(topicFields),
      sizes: Layout.SIZE});
  };
}));
