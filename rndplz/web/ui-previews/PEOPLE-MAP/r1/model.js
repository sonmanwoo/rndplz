/* PEOPLE-MAP r1: four fictional people, browser-only preview state.
 * Fictional cases A-C and PF-DEMO-04; see private handoff for provenance.
 * No product API, persistence, identity verification, or message delivery.
 */
(function (root, factory) {
  'use strict';
  var core = factory();
  if (typeof module === 'object' && module.exports) module.exports = core;
  else root.PeopleMapCore = core;
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function deepFreeze(value) {
    if (value && typeof value === 'object' && !Object.isFrozen(value)) {
      Object.keys(value).forEach(function (key) { deepFreeze(value[key]); });
      Object.freeze(value);
    }
    return value;
  }

  var people = deepFreeze([
    {
      id: 'PF-DEMO-01', name: '가람', initial: '가',
      team: '현장운영팀', teamNote: '가상 소속 · 기준일 미기재',
      currentRole: '현재 역할 미기재',
      experience: {
        title: '정제 시험 지원', topic: '탈색탈취', role: '현장 샘플링 담당',
        period: '2025', thenTeam: '업무 당시 소속 미기재',
        evidence: {
          id: 'PF-MEMO-01', version: 'v1', kind: '가상 메모',
          summary: '채취·인계 조건을 기록한 역할만 명시돼 있습니다.',
          limit: '공정 설계자나 시험의 최종 책임자로 확대하지 않습니다. 실제 적합성·현재 응답 가능성·문제 해결은 미확인입니다.',
          location: '정확한 원문 위치 미기재', date: '메모 작성일 미기재'
        },
        question: '당시 시료를 채취·인계할 때 기록한 조건 중 이번 배치 비교에서도 먼저 확인해야 할 것은 무엇인가요?'
      },
      ai: null
    },
    {
      id: 'PF-DEMO-02', name: '누리', initial: '누',
      team: '소재기획팀', teamNote: '가상 현재 소속 · 2026~',
      currentRole: '현재 역할 미기재',
      experience: {
        title: '분리막 파일럿', topic: '분리막', role: '시험 계획 검토자',
        period: '업무 참여 기간 미기재', thenTeam: '공정개발팀 (2024~2025)',
        evidence: {
          id: 'PF-REPORT-02', version: 'v2', kind: '가상 보고서',
          summary: '과거 공정개발팀의 분리막 파일럿에서 시험 계획을 검토한 역할을 뒷받침합니다.',
          limit: '직접 운전 수행은 확인하지 못합니다. 당시 경험을 현재 팀의 성과나 직접 수행 경력으로 바꾸지 않습니다.',
          location: '정확한 원문 위치 미기재', date: '보고서 작성일 미기재'
        },
        question: '당시 계획을 검토할 때 비교 조건으로 삼은 항목과 확인하지 못한 조건은 무엇이었나요?'
      },
      ai: null
    },
    {
      id: 'PF-DEMO-03', name: '다솔', initial: '다',
      team: '품질분석팀', teamNote: '가상 소속 · 기준일 미기재',
      currentRole: '현재 역할 미기재',
      experience: {
        title: '시료 이미지 비교', topic: '이미지 분석', role: '촬영 조건 기록·검토',
        period: '기간 미기재', thenTeam: '업무 당시 소속 미기재',
        evidence: {
          id: 'PF-REPORT-03', version: 'v1', kind: '가상 보고서',
          summary: '시료 이미지 비교의 촬영 조건 기록·검토 경험이 남아 있습니다.',
          limit: 'AI 모델 자체의 전문성이나 전체 실험 검증으로 확대하지 않습니다. 실제 전문가 의견·발송·성과가 아닙니다.',
          location: '정확한 원문 위치 미기재', date: '보고서 작성일 미기재'
        },
        question: '이 비교에 필요한 조건 가운데 자료로 확인되는 것과 추가 확인해야 할 것은 무엇인가요?'
      },
      ai: {
        id: 'PF-AI-03 v1',
        assumption: '과거·현재 이미지의 촬영·보관 조건이 같다는 가정은 사용자가 확인한 사실이 아닙니다.',
        summary: '이미지 분석 비교안의 가정을 확인하기 위한 시안용 요약입니다. 실제 AI 원답 전문은 제공되지 않았습니다.'
      }
    },
    {
      id: 'PF-DEMO-04', name: '온유', initial: '온',
      team: null, teamNote: '명부에 미기재', currentRole: '명부에 미기재',
      experience: null, ai: null
    }
  ]);

  function initialState() {
    return {
      query: '', topic: '', view: 'experience', selectedId: null,
      evidenceIds: [], problem: '', draft: '', includeAi: false, aiText: ''
    };
  }

  function str(value) { return typeof value === 'string' ? value : ''; }
  function searchKey(value) {
    return str(value).normalize('NFKC').replace(/\s+/g, '').toLocaleLowerCase('ko');
  }

  function visiblePeople(state) {
    state = state || initialState();
    var query = searchKey(state.query);
    var topic = str(state.topic);
    return people.filter(function (person) {
      return (!query || searchKey(person.name).indexOf(query) !== -1) &&
        (!topic || (person.experience && person.experience.topic === topic));
    });
  }

  function clearSelection(state) {
    return Object.assign({}, state, {
      selectedId: null, evidenceIds: [], problem: '', draft: '',
      includeAi: false, aiText: ''
    });
  }

  function selectedPerson(state) {
    return visiblePeople(state).find(function (person) { return person.id === state.selectedId; }) || null;
  }

  // Reconcile every transition against the current visible person and that
  // person's evidence. A stale action can never attach another person's source.
  function reconcile(input) {
    var state = {
      query: str(input.query), topic: str(input.topic),
      view: input.view === 'organization' ? 'organization' : 'experience',
      selectedId: str(input.selectedId) || null,
      evidenceIds: Array.isArray(input.evidenceIds) ? input.evidenceIds.slice() : [],
      problem: str(input.problem), draft: str(input.draft),
      includeAi: input.includeAi === true, aiText: str(input.aiText)
    };
    var person = selectedPerson(state);
    if (!person) return clearSelection(state);
    var evidenceId = person.experience && person.experience.evidence.id;
    state.evidenceIds = evidenceId && state.evidenceIds.indexOf(evidenceId) !== -1 ? [evidenceId] : [];
    if (!person.experience) state.problem = '';
    if (!state.evidenceIds.length) {
      state.draft = '';
      state.includeAi = false;
      state.aiText = '';
    }
    if (!state.includeAi) {
      state.includeAi = false;
      state.aiText = '';
    }
    return state;
  }

  function reduce(input, action) {
    var state = reconcile(input || initialState());
    action = action || {};
    var person = selectedPerson(state);
    switch (action.type) {
      case 'QUERY':
        state.query = str(action.value);
        break;
      case 'TOPIC':
        state.topic = str(action.value);
        break;
      case 'VIEW':
        if (action.value === 'experience' || action.value === 'organization') state.view = action.value;
        break;
      case 'SELECT':
        if (visiblePeople(state).some(function (item) { return item.id === action.id; }) &&
            state.selectedId !== action.id) {
          state = clearSelection(state);
          state.selectedId = action.id;
        }
        break;
      case 'EVIDENCE':
        if (person && person.experience && action.id === person.experience.evidence.id) {
          if (action.checked === true) {
            if (!state.evidenceIds.length) {
              state.evidenceIds = [action.id];
              state.draft = person.experience.question;
            }
          } else if (action.checked === false) {
            state.evidenceIds = [];
            state.draft = '';
            state.includeAi = false;
            state.aiText = '';
          }
        }
        break;
      case 'PROBLEM':
        if (person && person.experience) state.problem = str(action.value);
        break;
      case 'DRAFT':
        if (person && state.evidenceIds.length) state.draft = str(action.value);
        break;
      case 'INCLUDE_AI':
        if (person && person.experience && state.evidenceIds.length) {
          if (action.value === true && !state.includeAi) {
            state.includeAi = true;
            state.aiText = '';
          } else if (action.value === false) {
            state.includeAi = false;
            state.aiText = '';
          }
        }
        break;
      case 'AI_TEXT':
        if (person && person.experience && state.evidenceIds.length && state.includeAi) state.aiText = str(action.value);
        break;
      case 'CLEAR_FILTERS':
        state.query = '';
        state.topic = '';
        break;
      case 'CLEAR_TOPIC':
        state.topic = '';
        break;
      case 'CLOSE_DETAIL':
        state = clearSelection(state);
        break;
      default:
        break;
    }
    return reconcile(state);
  }

  return Object.freeze({
    people: people, initialState: initialState,
    visiblePeople: visiblePeople, reduce: reduce
  });
}));
