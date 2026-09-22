"""Offline stop continuity through actual Conversation/Service/StateStore.

Only corpus input and model streaming are synthetic. PublicEvidenceSearch.search
is observed and called unchanged. No pending state or accepted plan is injected.
Run baseline and candidate in separate Python processes with --source-root.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
SEED = '증류 경험을 기준으로 찾고 싶어. 탈색과 탈취는 필수 조건이야.'
STOP = '찾는 건 여기서 멈춰. 지금까지 정한 조건만 정리해줘.'
CORRECTION = '탈색과 탈취는 필수가 아니야. 증류 경험만 기준으로 기억해줘.'
RESUME = '이제 증류 경험을 기준으로 다시 찾아줘.'
EXPLAIN = '지금 저장한 조건의 뜻만 설명해줘.'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def grounding(messages, phase):
    for row in messages:
        content = row.get('content', '')
        for line in content.splitlines():
            if line.startswith('{'):
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict) and (value.get('phase') == phase or
                        phase == 'source_turns' and 'current_turn_id' in value and 'source_turns' in value):
                    return value
    raise AssertionError('Actual model request grounding not found: ' + phase)


class RecordingModels:
    """Same get/catalog/stream fixture convention as verify_attachment_routing."""
    def __init__(self, correction_decision):
        self.correction_decision = correction_decision
        self.calls = []
        self.fail_answer = False

    def get(self, identifier):
        if identifier != 'synthetic-stop':
            raise ValueError('Unknown synthetic model')
        return {'id': identifier, 'name': 'Offline fixture', 'provider': 'fixture',
                'enabled': True, 'vision': False}

    def catalog(self, refresh=False):
        return {'models': [self.get('synthetic-stop')], 'default': 'synthetic-stop'}

    def stream(self, identifier, messages, *, contract=None):
        self.get(identifier)
        call = {'contract': contract, 'messages': copy.deepcopy(messages)}
        self.calls.append(call)
        if contract == 'dialogue_plan.v2':
            actual = grounding(messages, 'source_turns')
            source = actual['source_turns'][-1]
            text, turn = source['input_text'], source['turn_id']
            scope = {'purposes': [], 'interpretations': [], 'record_ids': [],
                     'person_names': [], 'conditions': []}
            brief = {'requested_help': [], 'open_questions': []}
            if text == EXPLAIN:
                decision, scope, summary = 'answer', None, '기존 조건 설명'
            elif text == STOP:
                decision, scope, summary = 'stop', None, '탐색 보류'
            else:
                decision = 'answer' if text == SEED else self.correction_decision if text == CORRECTION else 'lookup'
                if text not in (SEED, CORRECTION, RESUME):
                    raise AssertionError('Unexpected synthetic user turn')
                summary = '증류 경험'
                brief['requested_help'] = [{'text': '증류 경험', 'source_turn_id': turn,
                                            'source_quote': '증류 경험'}]
                if text == SEED:
                    scope['conditions'] = [
                        {'kind': 'required', 'text': name, 'source_turn_id': turn,
                         'source_quote': '탈색과 탈취는 필수 조건이야.',
                         'strength_quote': '필수 조건'} for name in ('탈색', '탈취')]
                else:
                    scope['interpretations'] = [{'label': '증류 경험', 'groups': [
                        {'topic_ids': [], 'queries': ['증류']}]}]
            value = {'request_effect': 'preserve' if text == EXPLAIN else 'update', 'decision': decision, 'scope': scope,
                     'brief': brief, 'summary': summary, 'reply': '합성 실행 계획입니다.',
                     'attachment_actions': []}
            call['output'] = copy.deepcopy(value)
            yield json.dumps(value, ensure_ascii=False)
        elif contract == 'dialogue_answer.v1':
            call['grounding'] = grounding(messages, 'final_consultation')
            if self.fail_answer:
                call['injected_failure'] = 'synthetic_consultation_failure'
                raise ValueError('synthetic_consultation_failure')
            call['output'] = '현재 요청 조건을 반영했습니다.'
            yield call['output']
        elif contract == 'dialogue_response.v1':
            # Baseline wrongly permits prepare after a paused correction. Let the
            # real preparation run to completion so denial is not a fixture error.
            value = {'assessments': [], 'reply': '합성 공개 자료가 없습니다.', 'next_lookup': None}
            call['output'] = value
            yield json.dumps(value, ensure_ascii=False)
        else:
            raise AssertionError('Unexpected generation contract: ' + str(contract))


class StopStateRegression(unittest.TestCase):
    source_root = None
    output_root = None
    observations = []

    def setUp(self):
        if self.output_root is None:
            temporary = tempfile.TemporaryDirectory(prefix='rndplz-stop-state-')
            self.addCleanup(temporary.cleanup)
            self.output_root = Path(temporary.name)
            self.source_root = Path(__file__).resolve().parents[1]
            self.observations = []
            # Discovery does not call main() or install its process-wide audit.
            # Scoped guards are removed after this case and do not affect other
            # unittest modules. Product inputs remain the synthetic corpus/model.
            for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                           'socket.socket.bind', 'socket.getaddrinfo',
                           'urllib.request.OpenerDirector.open', 'subprocess.Popen'):
                guard = patch(target, side_effect=AssertionError('offline-only discovery'))
                blocked = guard.start()
                self.addCleanup(guard.stop)
                self.addCleanup(blocked.assert_not_called)

    def run_scenario(self, decision):
        from rndplz.conversation import Conversation
        from rndplz.engine import Engine
        from rndplz.models import ExternalModel
        from rndplz.service import Service
        from rndplz.evidence_search import PublicEvidenceSearch

        corpus = SimpleNamespace(people={}, records={}, by_person={}, topics=[],
                                 topic_by_id={}, questions=[], errors=[])
        models = RecordingModels(decision)
        service = Service(Engine(corpus), self.output_root / decision / 'state',
                          ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                          state_env={})
        chat = Conversation(service, models)
        report = {'correction_decision': decision, 'checks': [], 'turns': [],
                  'physical_searches': [], 'model_calls': models.calls}
        self.observations.append(report)
        sid = None

        def check(name, value):
            report['checks'].append({'name': name, 'pass': value is True})

        def turn(text, fail=False):
            nonlocal sid
            models.fail_answer = fail
            turn_id = uuid.uuid4().hex
            payload = {'text': text, 'model_id': 'synthetic-stop', 'turn_id': turn_id,
                       'model_selection_origin': 'explicit', 'attachments': []}
            if sid:
                payload['session_id'] = sid
            events = list(chat.stream(payload))
            if not sid:
                sid = service.store.read()['sessions'][-1]['id']
            stored = next(row for row in service.store.read()['sessions'] if row['id'] == sid)
            message = next(m for m in reversed(stored['messages']) if m['role'] == 'assistant')
            report['turns'].append({'text': text, 'turn_id': turn_id, 'events': events,
                                    'stored': copy.deepcopy(stored)})
            expected_status = 'error' if fail else 'complete'
            self.assertEqual(message.get('status'), expected_status,
                             'Fixture must pass actual PLAN/ANSWER parsing before behavior assertions')
            self.assertIsNone(stored.get('pending'))
            return stored

        original_search = PublicEvidenceSearch.search

        def observe_search(instance, plan, *args, **kwargs):
            report['physical_searches'].append({'plan': copy.deepcopy(plan), 'kwargs': copy.deepcopy(kwargs)})
            return original_search(instance, plan, *args, **kwargs)

        with patch.object(PublicEvidenceSearch, 'search', observe_search):
            seed = turn(SEED)
            self.assertEqual({r['text'] for r in seed['request_spec']['conditions']}, {'탈색', '탈취'})
            stopped = turn(STOP)
            check('stop_completed_pause_true', stopped.get('lookup_paused') is True)
            check('stop_scout_stopped', stopped['scout']['status'] == 'stopped')
            count = len(report['physical_searches'])
            corrected = turn(CORRECTION)
            check('correction_pause_remains', corrected.get('lookup_paused') is True)
            check('correction_no_physical_search', len(report['physical_searches']) == count)
            check('correction_offer_not_rewritten_to_stop', corrected['model_plan']['intent'] == 'chat'
                  and corrected['model_plan']['lookup_action'] == 'offer')
            check('correction_scout_stopped', corrected['scout']['status'] == 'stopped')
            check('correction_discovery_deferred', corrected['discovery']['lookup_ready'] is False
                  and corrected['discovery']['lookup_status'] == 'deferred')
            check('correction_no_disclosure', corrected.get('result') is None
                  and corrected.get('can_propose') is False and corrected['scout']['disclosed'] is False)
            spec = corrected['request_spec']
            check('goal_and_source_preserved', spec['summary'] == '증류 경험'
                  and spec['requested_help'][0]['text'] == '증류 경험'
                  and spec['requested_help'][0]['source_quote'] == '증류 경험'
                  and spec['requested_help'][0]['source_turn_id'] == report['turns'][-1]['turn_id'])
            check('withdrawn_mandatory_conditions_absent', spec['conditions'] == [])
            observation = models.calls[-1]['grounding']['execution_observation']
            check('answer_observation_not_executed', observation['status'] == 'not_executed')
            check('answer_button_disabled', observation['button_enabled_on_completion'] is False)
            calls_before, searches_before = len(models.calls), len(report['physical_searches'])
            before_prepare = copy.deepcopy(service.store.read())
            try:
                value = chat.prepare({'session_id': sid, 'discovery_revision': corrected['model_plan_revision']})
            except ValueError as error:
                report['prepare'] = {'rejected': True, 'error': str(error)}
            else:
                report['prepare'] = {'rejected': False, 'result': value}
            check('prepare_rejected', report['prepare']['rejected'])
            check('prepare_no_model_or_search', len(models.calls) == calls_before
                  and len(report['physical_searches']) == searches_before)
            check('prepare_state_unchanged', service.store.read() == before_prepare)

            # Fresh explicit turn: allowed physical search, but failed answer
            # must not commit lifting the user's pause.
            count = len(report['physical_searches'])
            failed_resume = turn(RESUME, fail=True)
            check('explicit_lookup_can_search_before_completion', len(report['physical_searches']) == count + 1)
            check('failed_resume_preserves_pause', failed_resume.get('lookup_paused') is True)
            check('failed_resume_no_authorized_cards', failed_resume.get('can_propose') is False
                  and failed_resume['scout']['disclosed'] is False)
            count = len(report['physical_searches'])
            resumed = turn(RESUME)
            check('new_explicit_lookup_searches_once', len(report['physical_searches']) == count + 1)
            check('successful_resume_commits_pause_false', resumed.get('lookup_paused') is False)
            check('resume_plan_execute', resumed['model_plan']['lookup_action'] == 'execute')
            check('resume_does_not_reintroduce_mandatory_conditions', resumed['request_spec']['conditions'] == [])
            check('no_plan_repair_or_hidden_retry', sum(c['contract'] == 'dialogue_plan.v2' for c in models.calls) == 5)
        failures = [row['name'] for row in report['checks'] if not row['pass']]
        self.assertEqual(failures, [], 'Behavior regression: ' + ', '.join(failures))

    def test_answer_offer_after_stop(self):
        self.run_scenario('answer')

    def test_clarify_offer_after_stop(self):
        self.run_scenario('clarify')

    def test_stop_brief_and_next_preserve(self):
        from rndplz.conversation import Conversation
        from rndplz.engine import Engine
        from rndplz.models import ExternalModel
        from rndplz.service import Service
        from rndplz.evidence_search import PublicEvidenceSearch

        corpus = SimpleNamespace(people={}, records={}, by_person={}, topics=[],
                                 topic_by_id={}, questions=[], errors=[])
        models = RecordingModels('answer')
        service = Service(Engine(corpus), self.output_root/'continuity'/'state',
                          ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                          state_env={})
        chat = Conversation(service, models)
        report = {'case': 'stop_brief_and_next_preserve', 'checks': [], 'turns': [],
                  'model_calls': models.calls, 'physical_searches': []}
        self.observations.append(report)
        sid = None

        def check(name, value):
            report['checks'].append({'name': name, 'pass': value is True})

        def turn(text):
            nonlocal sid
            payload = {'text': text, 'model_id': 'synthetic-stop', 'turn_id': uuid.uuid4().hex,
                       'model_selection_origin': 'explicit', 'attachments': []}
            if sid:
                payload['session_id'] = sid
            events = list(chat.stream(payload))
            raw = service.store.read()['sessions'][-1]
            sid = raw['id']
            report['turns'].append({'text': text, 'events': events, 'stored': copy.deepcopy(raw)})
            return raw

        content_keys = ('summary', 'purposes', 'requested_help', 'conditions', 'open_questions', 'has_content')
        def brief(raw):
            return {key: copy.deepcopy(raw.get(key)) for key in content_keys}

        original_search = PublicEvidenceSearch.search
        def observe_search(instance, plan, *args, **kwargs):
            report['physical_searches'].append(copy.deepcopy(plan))
            return original_search(instance, plan, *args, **kwargs)

        with patch.object(PublicEvidenceSearch, 'search', observe_search):
            seed = turn(SEED)
            self.assertEqual(seed['messages'][-1]['status'], 'complete')
            original = brief(seed['request_spec'])
            stopped = turn(STOP)
            self.assertEqual(stopped['messages'][-1]['status'], 'complete')
            check('stop_keeps_original_brief', brief(stopped['request_spec']) == original)
            check('stop_answer_receives_original_brief', brief(models.calls[-1]['grounding']['request_spec']) == original)
            check('stop_revision_matches_stored_brief', stopped['request_spec']['revision'] == stopped['model_plan_revision'])
            after = turn(EXPLAIN)
            plans = [call for call in models.calls if call['contract'] == 'dialogue_plan.v2']
            next_input = grounding(plans[2]['messages'], 'source_turns')
            check('next_plan_can_preserve', next_input['request_continuity']['preserve_available'] is True)
            check('preserve_response_completes', after['messages'][-1]['status'] == 'complete')
            check('preserve_keeps_original_brief', brief(after['request_spec']) == original)
            check('preserve_keeps_pause', after.get('lookup_paused') is True)
            check('no_physical_search', report['physical_searches'] == [])
            check('no_repair_or_retry', len(plans) == 3 and len(models.calls) == 6)
            check('no_candidate_or_proposal_authority', after.get('can_propose') is False
                  and not after.get('result') and after['scout']['disclosed'] is False)
        failures = [row['name'] for row in report['checks'] if not row['pass']]
        self.assertEqual(failures, [], 'Continuity regression: ' + ', '.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--only', choices=('stop', 'continuity', 'all'), default='stop')
    args = parser.parse_args()
    source = args.source_root.resolve()
    output = args.out.resolve()
    unit = Path(__file__).resolve().parents[2]
    if not output.is_relative_to(unit) or output == unit:
        parser.error('--out must be a new child directory of the owned unit')
    output.mkdir(parents=True, exist_ok=False)
    blocked = []

    def audit(event, values):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'urllib.Request', 'subprocess.Popen'):
            blocked.append(event)
            raise RuntimeError('offline-only regression')
        if event == 'open' and isinstance(values[0], (str, bytes)):
            name = str(values[0]).replace('\\', '/').lower()
            if name.endswith(('/featured_people.json', '/demo_pool.json', '/auth.json')) or '/pack/data/' in name:
                blocked.append('forbidden_real_input')
                raise RuntimeError('synthetic corpus and model only')

    sys.addaudithook(audit)
    sys.path.insert(0, str(source))
    pins = {name: sha((source/'rndplz'/name).read_bytes()) for name in (
        'conversation.py', 'model_conversation.py', 'model_dialogue.py', 'service.py',
        'storage.py', 'evidence_search.py', 'engine.py')}
    StopStateRegression.source_root = source
    StopStateRegression.output_root = output
    methods = ['test_answer_offer_after_stop', 'test_clarify_offer_after_stop'] if args.only == 'stop' else []
    if args.only == 'all':
        methods = ['test_answer_offer_after_stop', 'test_clarify_offer_after_stop']
    if args.only in ('continuity', 'all'):
        methods.append('test_stop_brief_and_next_preserve')
    suite = unittest.TestSuite(StopStateRegression(name) for name in methods)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    receipt = {'schema': 'r1-stop-state-offline-regression.v1',
               'status': 'PASS' if result.wasSuccessful() else 'FAIL',
               'source_root': str(source), 'source_pins': pins,
               'test_sha256': sha(Path(__file__).read_bytes()),
               'selected_cases': methods,
               'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
               'details': [{'test': str(test), 'traceback': trace} for test, trace in result.failures + result.errors],
               'observations': StopStateRegression.observations,
               'blocked_events': blocked,
               'actual_external_model_calls': 0, 'network': 0, 'server': 0,
               'limits': ['Scripted valid PLAN/ANSWER outputs test state control, not live model semantics.',
                          'Synthetic empty corpus; search spy delegates to actual PublicEvidenceSearch.search.',
                          'No WSGI/browser/provider integration claim; actual Conversation/Service/StateStore used.']}
    receipt['source_unchanged_during_run'] = all(sha((source/'rndplz'/name).read_bytes()) == pin for name, pin in pins.items())
    (output/'result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': receipt['status'], 'tests': result.testsRun,
                      'result': str(output/'result.json'), 'sha256': sha((output/'result.json').read_bytes())}))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
