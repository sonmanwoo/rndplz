"""공용 인물 내용의 데이터 경계와 표시 계약. 브라우저 검증과 별개다."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRELUDE = """
const assert = require('node:assert/strict');
const P = require('./rndplz/web/person-view.js');
"""


def run_js(script):
    result = subprocess.run(['node', '-'], input=PRELUDE + script, text=True,
                            encoding='utf-8', cwd=ROOT, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_name_priority_and_record_spelling_are_shared():
    run_js(r"""
const person = {name:'Recorded Name', org:'합성 기관', profile:{display_name:'표시 이름'}};
assert.equal(P.displayName(person),'표시 이름');
const header=P.nameBlock(person,'h2','pi-identity',{headingId:'piName',headingClass:'pi-name',orgClass:'pi-org'});
assert(header.indexOf('표시 이름') < header.indexOf('Recorded Name'));
assert(header.includes('id="piName"'));
assert(header.includes('class="pi-name"'));
assert.equal(P.displayName({name:'기록 이름',profile:{display_name:'   '}}),'기록 이름');
assert.equal(P.displayName({profile:{}}),'이름 미확인');
assert(!P.nameBlock({name:'<img onerror=bad>',profile:{display_name:'<script>'}}).includes('<script>'));
""")


def test_evidence_description_joins_exact_records_and_preserves_legacy_guard():
    run_js(r"""
const profile={timeline:[{record_id:'C1',date:'2026',text:'첫 역할'},
 {record_id:'C2',date:'2026',text:'다른 역할'}],projects:[{id:'P1',text:'프로젝트 성과'}]};
assert.equal(P.evidenceDescription({id:'C2',kind:'career_record',date:'2026'},profile),'다른 역할');
assert.equal(P.evidenceDescription({id:'C3',kind:'career_record',date:'2026'},profile),'');
assert.equal(P.evidenceDescription({id:'P1',kind:'project_record'},profile),'프로젝트 성과');
assert.equal(P.evidenceDescription({id:'P2',kind:'project_record',title:'P1'},profile),'');
assert.equal(P.evidenceDescription({id:'C1',kind:'career_record',excerpt:'저장된 설명'},profile),'저장된 설명');
assert.equal(P.evidenceDescription({id:'OLD',kind:'career_record',date:'2025'},
 {timeline:[{date:'2025',text:'예전 설명'}]}),'예전 설명');
assert.equal(P.evidenceDescription({id:'OLD',kind:'career_record',date:'2025'},
 {timeline:[{date:'2025',text:'하나'},{date:'2025',text:'둘'}]}),'');
""")


def test_only_descriptions_expand_and_unsafe_sources_never_link():
    run_js(r"""
const evidence={id:'E',title:'출처만 있는 기록',date:'2026',scope_label:'공개 기록',
 url:'https://example.org/record',boundary:'공통 고지'};
const plain=P.evidenceRow(evidence,{});
assert(!plain.includes('<details'));
assert(plain.includes('href="https://example.org/record"'));
assert(plain.includes('공개 기록') && plain.includes('2026'));
const expanded=P.evidenceRow({...evidence,excerpt:'실제 활동 설명'},{});
assert(expanded.includes('<details') && expanded.includes('실제 활동 설명'));
assert(!P.evidenceRow({...evidence,url:'javascript:alert(1)'},{}).includes('href='));
const disabled=P.evidenceRow({...evidence,in_current_pool:false},{},{recordAction:true});
assert(!/data-action="record"[^>]*>/.test(disabled) || disabled.includes('disabled'));
""")


def test_counts_use_available_evidence_and_scoped_record_intersection():
    run_js(r"""
const person={evidence:[{id:'a'},{id:'b'},{id:'c'}],record_count:99,works_count:1000};
assert.equal(P.countLabel(3),'전체 등록 이력 3건');
assert.equal(P.countLabel(2,true),'이번 조건에 연결된 근거 2건');
assert.equal(P.evidenceStats(person,{hasCondition:false}),'전체 등록 이력 3건');
assert.equal(P.evidenceStats(person,{hasCondition:true,recordIds:['b','b','missing']}),
 '전체 등록 이력 3건 · 이번 조건에 연결된 근거 1건');
assert.equal(P.evidenceStats(person,{hasCondition:true,recordIds:[]}),
 '전체 등록 이력 3건 · 이번 조건에 연결된 근거 0건');
""")


def test_history_uses_passed_snapshot_without_latest_registry_counts():
    run_js(r"""
const snapshot={name:'저장 이름',profile:{display_name:'저장 표시명',biography:'당시 소개'},
 evidence:[{id:'old',title:'당시 기록',excerpt:'당시 설명'}],record_count:500};
const output=P.nameBlock(snapshot)+P.evidenceSection(snapshot.evidence,snapshot.profile,{historical:true})+
 P.notice(snapshot,{historical:true,scopeNote:'저장된 범위'});
assert(output.includes('저장 표시명') && output.includes('당시 설명'));
assert(output.includes('이번 조건에 연결된 근거 1건'));
assert(!output.includes('<h3>전체 등록 이력'));
assert(output.includes('현재 전체 등록 이력이 아닙니다'));
assert(output.includes('저장된 범위'));
""")


def test_notice_distinguishes_virtual_people_and_preserves_profile_scope():
    run_js(r"""
const virtual=P.notice({virtual:true,profile:{}});
assert(virtual.includes('시연용 가상 인물과 기록입니다.'));
assert(virtual.includes('실제 인물·사업장·승인 절차가 아닙니다.'));
assert(!virtual.includes('본인 제공·공개 기록'));
const normal=P.notice({virtual:false,profile:{}});
assert(normal.includes('본인 제공·공개 기록'));
assert(!normal.includes('시연용 가상 인물'));
const historical=P.notice({profile:{current_status:{category:'deceased'},profile_note:'역사적 연구 자료의 범위'}});
assert(historical.includes('역사적 연구 자료의 범위'));
assert(!historical.includes('지금의 역량'));
""")


def test_sections_have_stable_ids_and_do_not_repeat_record_descriptions():
    run_js(r"""
const person={id:'P',name:'합성 인물',profile:{curated:true,biography:'합성 소개',
 skills:['기술 하나','기술 둘','기술 셋','기술 넷','기술 다섯'],
 timeline:[{record_id:'C1',date:'2026',text:'한 번만 보여줄 경력'}],
 projects:[{id:'P1',title:'프로젝트',date:'2025',text:'한 번만 보여줄 성과'}],
 links:[{url:'https://example.org',label:'소개 링크'}]},evidence:[
 {id:'C1',kind:'career_record',title:'경력 기록',date:'2026'},
 {id:'P1',kind:'project_record',title:'프로젝트 기록',date:'2025'}]};
const sections=P.sections(person,{editable:true,includeEvidence:true});
const ids=sections.map(s=>s.id);
for(const id of ['identity','bio','skills','careers','projects','links','evidence'])assert(ids.includes(id),id);
assert.equal(new Set(ids).size,ids.length);
const output=P.render(person);
assert.equal(output.split('한 번만 보여줄 경력').length-1,1);
assert.equal(output.split('한 번만 보여줄 성과').length-1,1);
assert.equal(output,P.sections(person).map(section=>section.html).join(''));
assert(!output.includes('person-section'));
assert(!P.sections(person).some(section=>section.id==='evidence'));
const notice=P.notice(person,{variant:'detail'});assert(notice);assert.equal(output.split(notice).length-1,1);
const chips=P.skills(person,{limit:4,className:'sheet-chips'});
assert(chips.includes('data-chips-more') && chips.includes('+1') && chips.includes('hidden'));
""")


def test_assets_are_registered_before_callers():
    web = ROOT / 'rndplz' / 'web'
    for name in ['index.html', 'explore.html', 'profile.html']:
        html = (web / name).read_text(encoding='utf-8')
        assert html.count('person-view.js') == 1
        assert html.count('person-view.css') == 1
        assert html.index('person-view.js') < html.index('craft.js')
    for name in ['public_web.py', 'ui.py']:
        source = (ROOT / 'rndplz' / name).read_text(encoding='utf-8')
        assert 'person-view.js' in source
        assert 'person-view.css' in source
