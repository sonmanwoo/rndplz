"""The company AI platform (AiU) as an opt-in model: one workflow app called over its service API.

Measured 2026-10-02 against local gemma4:e4b on 34 hosted first questions: no failed scout
assessment (Gemma 4 of 27) and cleaner candidates, but a first reply of 17.8 s against 5.3 s.
It is therefore an option, enabled only by RNDPLZ_AIU_API_KEY and RNDPLZ_AIU_URL.
"""
import json
import time
import unittest
from unittest.mock import patch

from rndplz import chat_models
from rndplz.chat_models import ChatModels, aiu_text, strip_json_fence

ENV = {'RNDPLZ_AIU_API_KEY': 'app-test', 'RNDPLZ_AIU_URL': 'https://aiu.example/ext/v1/workflows/run',
       'RNDPLZ_AIU_MODEL': 'GPT luna'}


def frames(*events):
    return [('data: ' + json.dumps(event, ensure_ascii=False) + '\n').encode('utf-8') for event in events]


class Response:
    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return iter(self.lines)

    def __exit__(self, *args):
        return False


class Opener:
    def __init__(self, lines, sink):
        self.lines, self.sink = lines, sink

    def open(self, request, timeout=None):
        self.sink.append((request.full_url, dict(request.header_items()), json.loads(request.data.decode('utf-8'))))
        # A list of lists scripts one response per call (for the retry tests).
        scripted = self.lines[min(len(self.sink), len(self.lines)) - 1] if self.lines and isinstance(self.lines[0], list) else self.lines
        return Response(scripted)


class AiuProviderTests(unittest.TestCase):
    def run_stream(self, lines, contract=None):
        models, sink = ChatModels(ENV), []
        models.refreshed = 10 ** 12  # no local Ollama probe
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=Opener(lines, sink)):
            pieces = list(models.stream('aiu', [{'role': 'user', 'content': '증류 전문가 찾아줘'}], contract=contract))
        return pieces, sink[0]

    def test_it_is_listed_only_when_configured(self):
        plain = ChatModels({})
        plain.refreshed = 10 ** 12
        self.assertNotIn('aiu', [m['id'] for m in plain.catalog()['models']])
        configured = ChatModels(ENV)
        configured.refreshed = 10 ** 12
        option = next(m for m in configured.catalog()['models'] if m['id'] == 'aiu')
        self.assertEqual((option['provider'], option['name'], option['slow']), ('aiu', 'GPT luna', False))
        with self.assertRaises(ValueError):
            ChatModels({**ENV, 'RNDPLZ_AIU_URL': 'http://aiu.example/run'})  # https only

    def test_further_apps_are_their_own_options_and_use_their_own_key(self):
        env = {**ENV, 'RNDPLZ_AIU_APPS': 'gpt-luna=GPT luna;nokey=Missing;Bad Slug=x', 'RNDPLZ_AIU_API_KEY_GPT_LUNA': 'app-gpt'}
        models, sink = ChatModels(env), []
        models.refreshed = 10 ** 12
        self.assertEqual([(m['id'], m['name']) for m in models.catalog()['models'] if m['provider'] == 'aiu'],
                         [('aiu', 'GPT luna'), ('aiu:gpt-luna', 'GPT luna')])
        good = frames({'event': 'text_chunk', 'data': {'text': '답'}}, {'event': 'workflow_finished', 'data': {'status': 'succeeded'}})
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=Opener(good, sink)):
            list(models.stream('aiu:gpt-luna', [{'role': 'user', 'content': '증류 전문가 찾아줘'}]))
        self.assertEqual(sink[0][1]['Authorization'], 'Bearer app-gpt')

    def test_the_hosted_catalog_lists_aiu_first_as_the_default(self):
        from rndplz.public_web import PublicModels
        hosted = PublicModels({**ENV, 'RNDPLZ_PUBLIC_MODEL': 'bridge', 'RNDPLZ_BRIDGE_TOKEN': 'fixture-secret'})
        catalog = hosted.catalog()
        self.assertEqual(catalog['default'], 'aiu')
        self.assertEqual([m['id'] for m in catalog['models']], ['bridge', 'guide', 'aiu'])
        without = PublicModels({'RNDPLZ_PUBLIC_MODEL': 'bridge', 'RNDPLZ_BRIDGE_TOKEN': 'fixture-secret'})
        self.assertEqual([m['id'] for m in without.catalog()['models']], ['bridge', 'guide'])

    def test_an_answer_streams_its_chunks(self):
        pieces, (url, headers, body) = self.run_stream(frames(
            {'event': 'workflow_started', 'data': {}}, {'event': 'text_chunk', 'data': {'text': '손만우 님이 '}},
            {'event': 'text_chunk', 'data': {'text': '있어요.'}}, {'event': 'workflow_finished', 'data': {'status': 'succeeded'}}))
        self.assertEqual(pieces, ['손만우 님이 ', '있어요.'])
        self.assertEqual((url, headers['Authorization'], body['mode']), (ENV['RNDPLZ_AIU_URL'], 'Bearer app-test', 'streaming'))
        self.assertIn('<user>\n증류 전문가 찾아줘\n</user>', body['inputs']['text'])  # instructions and turns in one input

    def test_structured_output_is_handed_over_whole_without_a_code_fence(self):
        plan = {'request_effect': 'update', 'decision': 'answer'}
        raw = '```json\n' + json.dumps(plan) + '\n```'
        pieces, (_, _, body) = self.run_stream(frames(
            {'event': 'text_chunk', 'data': {'text': raw[:12]}}, {'event': 'text_chunk', 'data': {'text': raw[12:]}},
            {'event': 'workflow_finished', 'data': {'status': 'succeeded'}}), contract='dialogue_plan.v2')
        self.assertEqual([json.loads(piece) for piece in pieces], [plan])
        self.assertIn('JSON 객체 하나만 출력', body['inputs']['text'])

    def test_a_failed_or_cut_run_is_an_error(self):
        for lines in (frames({'event': 'error', 'code': 'credit_exceeded', 'message': 'x', 'status': 402}),
                      frames({'event': 'workflow_finished', 'data': {'status': 'failed'}}),
                      frames({'event': 'text_chunk', 'data': {'text': '끊긴 답'}})):
            with self.subTest(lines=len(lines)), self.assertRaises(ValueError):
                self.run_stream(lines)

    def test_a_run_that_failed_before_any_text_is_tried_once_more(self):
        failed = frames({'event': 'workflow_finished', 'data': {'status': 'failed'}})
        good = frames({'event': 'text_chunk', 'data': {'text': '다시 받은 답'}}, {'event': 'workflow_finished', 'data': {'status': 'succeeded'}})
        models, sink = ChatModels(ENV), []
        models.refreshed = 10 ** 12
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=Opener([failed, good], sink)):
            pieces = list(models.stream('aiu', [{'role': 'user', 'content': '증류 전문가 찾아줘'}]))
        self.assertEqual((pieces, len(sink)), (['다시 받은 답'], 2))

    def test_an_answer_cut_after_text_was_shown_is_not_repeated(self):
        cut = frames({'event': 'text_chunk', 'data': {'text': '보인 답'}}, {'event': 'error', 'code': 'x', 'message': 'x', 'status': 500})
        models, sink = ChatModels(ENV), []
        models.refreshed = 10 ** 12
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=Opener([cut, cut], sink)):
            with self.assertRaises(ValueError):
                list(models.stream('aiu', [{'role': 'user', 'content': '증류 전문가 찾아줘'}]))
        self.assertEqual(len(sink), 1)

    def test_reading_stops_at_the_success_event(self):
        # Reviewed 2026-10-03: a socket kept open after workflow_finished(succeeded) timed out and
        # turned a complete answer into an error.
        class Cut(Response):
            def __enter__(self):
                def lines():
                    yield from self.lines
                    raise TimeoutError('socket kept open after completion')
                return lines()
        done = frames({'event': 'text_chunk', 'data': {'text': '완성된 답'}}, {'event': 'workflow_finished', 'data': {'status': 'succeeded'}})
        models, sink = ChatModels(ENV), []
        models.refreshed = 10 ** 12
        opener = Opener(done, sink)
        with patch.object(chat_models, 'Response', Cut, create=True), patch.object(chat_models.urllib.request, 'build_opener', return_value=opener):
            opener.open = lambda request, timeout=None: (sink.append(request.full_url), Cut(done))[1]
            pieces = list(models.stream('aiu', [{'role': 'user', 'content': '증류 전문가 찾아줘'}]))
        self.assertEqual((pieces, len(sink)), (['완성된 답'], 1))

    def test_a_permanent_platform_error_is_sent_once_and_named(self):
        credit = frames({'event': 'error', 'code': 'credit_exceeded', 'message': 'x', 'status': 402})
        models, sink = ChatModels(ENV), []
        models.refreshed = 10 ** 12
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=Opener([credit, credit], sink)):
            with self.assertRaises(ValueError) as caught:
                list(models.stream('aiu', [{'role': 'user', 'content': '증류 전문가 찾아줘'}]))
        self.assertEqual((len(sink), models.calls['aiu']), (1, 1))
        self.assertIn('크레딧', str(caught.exception))
        busy = frames({'event': 'error', 'code': 'too_many_requests', 'message': 'x', 'status': 429})
        good = frames({'event': 'text_chunk', 'data': {'text': '답'}}, {'event': 'workflow_finished', 'data': {'status': 'succeeded'}})
        models, sink = ChatModels(ENV), []
        models.refreshed = 10 ** 12
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=Opener([busy, good], sink)):
            pieces = list(models.stream('aiu', [{'role': 'user', 'content': '증류 전문가 찾아줘'}]))
        self.assertEqual((pieces, len(sink), models.calls['aiu']), (['답'], 2, 2))  # the retry is a counted run

    def test_the_shared_app_has_an_hourly_and_a_concurrent_budget(self):
        from rndplz.chat_models import ModelProviderCapacity
        good = frames({'event': 'text_chunk', 'data': {'text': '답'}}, {'event': 'workflow_finished', 'data': {'status': 'succeeded'}})
        models, sink = ChatModels({**ENV, 'RNDPLZ_AIU_RUNS_PER_HOUR': '2'}), []
        models.refreshed = 10 ** 12
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=Opener(good, sink)):
            for _ in range(2):
                list(models.stream('aiu', [{'role': 'user', 'content': '증류 전문가 찾아줘'}]))
            self.assertFalse(models.has_call_capacity('aiu', provider='aiu'))
            with self.assertRaises(ModelProviderCapacity):
                list(models.stream('aiu', [{'role': 'user', 'content': '증류 전문가 찾아줘'}]))
        self.assertEqual(len(sink), 2)
        models.aiu_runs.clear()
        models.aiu_active = models.aiu_max_concurrent  # other runs in flight
        self.assertFalse(models.has_call_capacity('aiu', provider='aiu'))
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=Opener(good, sink)):
            with self.assertRaises(ModelProviderCapacity):
                list(models.stream('aiu', [{'role': 'user', 'content': '증류 전문가 찾아줘'}]))
        self.assertEqual(len(sink), 2)

    def test_a_ping_does_not_extend_the_run_past_the_deadline(self):
        # Reviewed 2026-10-03 (Codex): the socket timeout was set once at open, so a keep-alive ping
        # followed by silence let a read block past the caller's deadline, and the retry was reserved
        # and counted although the deadline no longer allowed it to be sent.
        import socket, threading
        receiver, sender = socket.socketpair()
        stop = threading.Event()

        def ping_then_silence():
            if not stop.wait(0.4):
                try:
                    sender.sendall(b'data: {"event":"ping"}\n')
                except OSError:
                    pass
            stop.wait(3)

        class SocketReply:
            def __enter__(self):
                self.file = receiver.makefile('rb')
                return self.file

            def __exit__(self, *args):
                self.file.close()
                return False

        class SocketOpener:
            def __init__(self):
                self.opens = []

            def open(self, request, timeout=None):
                self.opens.append(timeout)
                receiver.settimeout(timeout)
                return SocketReply()

        class Deadlined(list):
            generation_deadline = None

        messages = Deadlined([{'role': 'user', 'content': '증류 전문가 찾아줘'}])
        messages.generation_deadline = time.monotonic() + 0.6
        models, opener = ChatModels(ENV), SocketOpener()
        models.refreshed = 10 ** 12
        writer = threading.Thread(target=ping_then_silence, daemon=True)
        writer.start()
        started = time.monotonic()
        try:
            with patch.object(chat_models.urllib.request, 'build_opener', return_value=opener), self.assertRaises(ValueError):
                list(models.stream('aiu', messages))
            elapsed = time.monotonic() - started
        finally:
            stop.set()
            writer.join(1)
            receiver.close()
            sender.close()
        self.assertLess(elapsed, 0.9)  # the deadline, not the socket's idle timeout, ended the wait
        self.assertEqual((len(opener.opens), models.calls['aiu'], len(models.aiu_runs), models.aiu_active), (1, 1, 1, 0))

    def test_a_stalled_run_is_dropped(self):
        ping = [b'event: ping\n', b'data: {"event":"ping"}\n']
        with patch.object(chat_models, 'AIU_FIRST_TEXT_SECONDS', -1), self.assertRaises(ValueError):
            self.run_stream(ping * 3)

    def test_apps_beside_the_default_wait_longer_for_their_first_text(self):
        # The profile app and the deep-consultation app run Claude Fable 5, ~20-35 s before the first
        # text (2026-10-06); the default chat app keeps the short stall limit.
        seen = []

        def fake_run(config, payload, remaining, budget, first_text=chat_models.AIU_FIRST_TEXT_SECONDS):
            seen.append((config['key'], first_text))
            yield '답'
        env = {**ENV, 'RNDPLZ_AIU_PROFILE_API_KEY': 'app-profile', 'RNDPLZ_AIU_APPS': 'deep=깊은 상담 · 클로드 페이블 5',
               'RNDPLZ_AIU_API_KEY_DEEP': 'app-deep'}
        for identifier in ('aiu', chat_models.AIU_PROFILE_APP, 'aiu:deep'):
            models = ChatModels(env)
            models.refreshed = 10 ** 12
            with patch.object(chat_models, 'aiu_run', fake_run):
                list(models.stream(identifier, [{'role': 'user', 'content': '안녕'}]))
        self.assertEqual(seen, [('app-test', chat_models.AIU_FIRST_TEXT_SECONDS),
                                ('app-profile', chat_models.AIU_SLOW_FIRST_TEXT_SECONDS),
                                ('app-deep', chat_models.AIU_SLOW_FIRST_TEXT_SECONDS)])
        deep = next(m for m in models.catalog()['models'] if m['id'] == 'aiu:deep')
        self.assertEqual((deep['name'], deep['slow']), ('깊은 상담 · 클로드 페이블 5', True))

    def test_prompt_and_fence_helpers(self):
        text = aiu_text('지침', [{'role': 'user', 'content': '질문'}, {'role': 'assistant', 'content': '답'}], structured=False)
        self.assertEqual(text, '[지침]\n지침\n[지침 끝]\n\n[대화]\n<user>\n질문\n</user>\n\n<assistant>\n답\n</assistant>\n[대화 끝]\n\n'
                               '위 지침에 따라 마지막 user 메시지에 답하세요.')
        self.assertEqual(strip_json_fence(' {"a": 1} '), '{"a": 1}')


if __name__ == '__main__':
    unittest.main()
