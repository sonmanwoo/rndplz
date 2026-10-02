"""The company AI platform (AiU) as an opt-in model: one workflow app called over its service API.

Measured 2026-10-02 against local gemma4:e4b on 34 hosted first questions: no failed scout
assessment (Gemma 4 of 27) and cleaner candidates, but a first reply of 17.8 s against 5.3 s.
It is therefore an option, enabled only by RNDPLZ_AIU_API_KEY and RNDPLZ_AIU_URL.
"""
import json
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
        self.assertEqual((option['provider'], option['name']), ('aiu', '사내 AI (AiU) · GPT luna'))
        with self.assertRaises(ValueError):
            ChatModels({**ENV, 'RNDPLZ_AIU_URL': 'http://aiu.example/run'})  # https only

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

    def test_a_stalled_run_is_dropped(self):
        ping = [b'event: ping\n', b'data: {"event":"ping"}\n']
        with patch.object(chat_models, 'AIU_FIRST_TEXT_SECONDS', -1), self.assertRaises(ValueError):
            self.run_stream(ping * 3)

    def test_prompt_and_fence_helpers(self):
        text = aiu_text('지침', [{'role': 'user', 'content': '질문'}, {'role': 'assistant', 'content': '답'}], structured=False)
        self.assertEqual(text, '[지침]\n지침\n[지침 끝]\n\n[대화]\n<user>\n질문\n</user>\n\n<assistant>\n답\n</assistant>\n[대화 끝]\n\n'
                               '위 지침에 따라 마지막 user 메시지에 답하세요.')
        self.assertEqual(strip_json_fence(' {"a": 1} '), '{"a": 1}')


if __name__ == '__main__':
    unittest.main()
