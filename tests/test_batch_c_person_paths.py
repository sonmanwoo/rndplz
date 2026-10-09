"""C6: 합성 자료의 같은 날짜 경력과 등록 이력 응답→인물 카드 경로.

브라우저/서버를 띄우지 않는다. 등록 조회의 인증 상태는 고정 fixture이며
실제 조회·응답 투영·JS 목록/클릭/카드 분기를 실행한다.
"""
import ast
import copy
import json
from pathlib import Path

import pytest

from rndplz.data import Corpus
from rndplz.engine import Engine
from rndplz.models import ExternalModel
from rndplz.service import Service
from test_person_view_b import ROOT, run_js


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    period = '2024-01 ~ 2025-12'
    timeline = [
        {'record_id': 'C-B', 'date': period, 'text': '둘째 합성 경력의 설명'},
        {'record_id': 'C-A', 'date': period, 'text': '첫째 합성 경력의 설명'},
    ]
    featured = {'checked_at': '2026-10-09', 'people': [
        {'id': 'SYNTHETIC-P', 'name': 'Synthetic Person', 'display_name': '합성 연구자',
         'org': '시험 연구실', 'org_type': 'education', 'timeline': timeline}],
        'papers': [], 'experience_records': [
            {'id': rid, 'person_id': 'SYNTHETIC-P', 'title': title + ' 합성 공정',
             'summary': title + ' 합성 공정 실험', 'date': period, 'tags': ['PE-SYNTHETIC']}
            for rid, title in [('C-A', '첫째 합성 경력'), ('C-B', '둘째 합성 경력')]]}
    topics = [{'id': 'PE-SYNTHETIC', 'name': '합성 공정', 'field': 'process_engineering',
               'keywords': ['합성 공정']}]
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        if path.name == 'featured_people.json':
            return json.dumps(featured, ensure_ascii=False)
        if path.name == 'topics.json':
            return json.dumps(topics, ensure_ascii=False)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', read)
    for name, data in {
        'openalex_snapshot.json': {'checked_at': '2026-10-09', 'authors': [], 'works': []},
        'site_records_seed.json': {'checked_at': '2026-10-09', 'records': []},
        'questions.json': {'questions': []},
    }.items():
        (tmp_path / name).write_text(json.dumps(data), encoding='utf-8')
    return Corpus(tmp_path)


def test_same_period_careers_keep_their_own_record_descriptions(corpus):
    person = corpus.people['SYNTHETIC-P']
    evidence = [Engine(corpus).explain_record(record)
                for record in corpus.by_person[person.id]]
    assert not corpus.errors
    assert [row['record_id'] for row in person.profile['timeline']] == ['C-B', 'C-A']
    assert len({row['date'] for row in evidence}) == 1
    payload = json.dumps({'profile': person.profile, 'evidence': evidence}, ensure_ascii=False)
    run_js('const fixture=' + payload + ';' + r"""
install('chat',['evidenceDescription']);
for(const timeline of [fixture.profile.timeline,[...fixture.profile.timeline].reverse()]){
  const profile={timeline};
  assert.equal(evidenceDescription(fixture.evidence[0],profile),'첫째 합성 경력의 설명');
  assert.equal(evidenceDescription(fixture.evidence[1],profile),'둘째 합성 경력의 설명');
  assert.equal(evidenceDescription({...fixture.evidence[0],id:'없는-기록'},profile),'');
}
const legacy={timeline:fixture.profile.timeline.map(({record_id,...row})=>row)};
for(const row of fixture.evidence)assert.equal(evidenceDescription(row,legacy),'');
""")


@pytest.fixture
def registered_response(corpus, tmp_path, monkeypatch):
    from rndplz import public_profiles, registered_experts

    monkeypatch.setattr(public_profiles, 'APPROVED_PERSON_IDS', frozenset(corpus.people))
    monkeypatch.setattr(public_profiles, 'APPROVED_RECORD_IDS', frozenset(corpus.records))
    service = Service(Engine(corpus), tmp_path / 'state',
                      ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                      state_env={'RNDPLZ_STATE_BACKEND': 'file'})
    session = {'id': 'S-SYNTHETIC', 'kind': 'chat', 'ready': True, 'pending': None,
               'messages': [{'role': 'user', 'turn_id': 'T-SYNTHETIC'},
                            {'role': 'assistant', 'turn_id': 'T-SYNTHETIC', 'status': 'complete'}],
               'result': {'candidates': [{'id': 'ORDINARY-P', 'name': '일반 합성 후보'}]},
               'discovery': {'revision': 'V-SYNTHETIC'},
               'scout': {'revision': 'V-SYNTHETIC', 'status': 'complete', 'disclosed': True},
               'prepared_discovery_revision': 'V-SYNTHETIC',
               'request_spec': {'revision': 'V-SYNTHETIC', 'source_turn_id': 'T-SYNTHETIC',
                                'state': 'current', 'has_content': True,
                                'purposes': [{'text': '합성 공정 자문'}], 'requested_help': [],
                                'conditions': [], 'open_questions': []}}
    service.store.transaction(lambda state: state['sessions'].append(copy.deepcopy(session)))
    # 조회 권한 자체는 이 시험 범위가 아니다. 이미 승인된 현재 의뢰를 제공한다.
    monkeypatch.setattr(registered_experts, '_current',
                        lambda service, state, sid, revision=None:
                        (state['sessions'][0], session['request_spec'], 'synthetic-binding'))
    extra = service.registered_expert_lookup(session['id'], 'V-SYNTHETIC',
                                            context_builder=lambda _: {'excluded_person_ids': []})
    assert extra['candidate_count'] == 1
    assert service.registered_expert_present(session['id']) == extra
    assert service.store.read()['sessions'][0] == session  # 일반 후보/대화 권한을 바꾸지 않는다.

    # WSGI 내부의 실제 응답 결합 함수만 실행한다. 서버 시작과 앱 초기화는 없다.
    tree = ast.parse((ROOT / 'rndplz/public_web.py').read_text(encoding='utf-8'))
    attach = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == 'attach_registered')
    scope = {'service': service}
    exec(compile(ast.Module(body=[attach], type_ignores=[]), 'public_web.py', 'exec'), scope)
    response = scope['attach_registered'](copy.deepcopy(session))
    assert response['registered_experts'] == extra
    stale = copy.deepcopy(session)
    stale['discovery']['revision'] = '다른-요청'
    assert 'registered_experts' not in scope['attach_registered'](stale)
    return response


def test_registered_response_keeps_browser_only_contract(registered_response):
    extra = registered_response['registered_experts']
    assert extra['schema'] == 'registered_expert_lookup.v1'
    assert extra['audience'] == 'browser_only'
    assert extra['session_id'] == registered_response['id']
    assert extra['model_data_sent'] is extra['can_propose'] is extra['delivery_allowed'] is False
    candidate = extra['candidates'][0]
    assert candidate['name'] == '합성 연구자'
    assert {row['id'] for row in candidate['evidence']} == {'C-A', 'C-B'}
    assert candidate['proposal_allowed'] is False
    assert candidate['availability'] == '미확인'


def test_registered_and_ordinary_clicks_open_the_same_person_card(registered_response):
    run_js('global.session=' + json.dumps(registered_response, ensure_ascii=False) + ';' + r"""
install('chat',['registeredViewCurrent','registeredEnvelope','registeredBinding',
  'renderRegisteredExperts','openPersonCard']);
global.accountNavigationPending=false;global.accountInvalidated=false;global.busy=false;
global.prepareBusy=false;global.profileBusy=false;global.profileUI=null;global.uploading=false;
global.files=[];global.composerComposing=false;global.letter=null;
const dialog=element();dialog.open=false;dialog.querySelector=()=>null;
const elements={message:{value:''},personCardDialog:dialog,proposalZone:{after(node){elements[node.id]=node;}}};
global.$=id=>elements[id];
global.document={activeElement:null,createElement:()=>element()};
global.registeredContextHtml=()=>'';global.registeredRequestAction=()=>'';
global.invalidateRegisteredUI=()=>assert.fail('유효한 합성 응답이 숨겨짐');
global.bindInspectHandle=()=>{};global.composerClientLocked=()=>false;
global.inspectCandidateIds=()=>session.result.candidates.map(row=>row.id);
const rendered=[],opened=[];
global.renderInspect=async id=>{rendered.push({id,registered:dialog.dataset.registeredReview,ids:dialog.inspectIds});return true;};
global.modal=(id,opener)=>{opened.push({id,opener});dialog.open=true;};
global.error=message=>assert.fail(message);
renderRegisteredExperts();
const markup=elements.registeredExpertsZone.innerHTML;
assert(markup.includes('등록 이력에서 찾은 사람'));
assert(markup.includes('data-action="registered-person" data-id="SYNTHETIC-P"'));

// 실제 위임 click 리스너를 설치해 목록 버튼의 action 분기를 실행한다.
const source=read('chat'), start=source.indexOf('document.addEventListener("click",async e=>{');
assert(start>=0,'실제 click 분기 위치');
let click;
document.addEventListener=(event,listener)=>{assert.equal(event,'click');click=listener;};
const end=source.indexOf('// A press and release',start);assert(end>start);
vm.runInThisContext(source.slice(start,end));
(async()=>{
  const registeredButton={classList:{contains:()=>false},dataset:{action:'registered-person',id:'SYNTHETIC-P'}};
  await click({target:{closest:()=>registeredButton}});
  assert.deepEqual(rendered[0],{id:'SYNTHETIC-P',registered:'true',ids:['SYNTHETIC-P']});
  assert.equal(opened[0].id,'personCardDialog');assert.equal(opened[0].opener,registeredButton);
  dialog.open=false;
  const ordinaryButton={classList:{contains:()=>false},dataset:{action:'person',id:'ORDINARY-P'}};
  await click({target:{closest:()=>ordinaryButton}});
  assert.deepEqual(rendered[1],{id:'ORDINARY-P',registered:'false',ids:['ORDINARY-P']});
  assert.equal(opened[1].id,opened[0].id);assert.equal(opened[1].opener,ordinaryButton);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")
