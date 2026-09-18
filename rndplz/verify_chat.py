"""Conversation boundaries, real document parsing, and provider wire contracts."""
import base64
import io
import json
import tempfile
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from .attachments import Attachments
from .chat_models import ChatModels
from .conversation import Conversation
from .engine import Engine
from .service import Service


class FakeModels:
    def __init__(self):
        self.calls=[];self.fail=False
    def get(self,identifier):
        if identifier!='fixture':raise ValueError('unknown model')
        return {'id':'fixture','name':'Fixture','vision':False}
    def stream(self,identifier,messages):
        self.calls.append(messages)
        yield '조건을 함께 확인해요.'
        if self.fail:raise ValueError('fixture interrupted')
        yield ' 60도인가요?'


class ChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.engine=Engine()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.service=Service(self.engine,self.temp.name)
        self.models=FakeModels();self.chat=Conversation(self.service,self.models)
    def tearDown(self):self.temp.cleanup()
    def payload(self,text='FKM 씰 액침냉각',**kwargs):
        return {'text':text,'model_id':'fixture','turn_id':uuid.uuid4().hex,**kwargs}
    def upload(self,raw,name='조건.txt'):
        return self.chat.attachments.upload({'name':name,'data':base64.b64encode(raw).decode()})
    def run_chat(self,p):return list(self.chat.stream(p))[-1]['session']

    def test_open_ended_history_no_automatic_recommendations(self):
        s=self.run_chat(self.payload())
        for i in range(4):s=self.run_chat(self.payload(f'추가 조건 {i}',session_id=s['id']))
        self.assertEqual(s['turns'],5)
        self.assertEqual(len(self.models.calls[-1]),9)
        self.assertIn('FKM',self.models.calls[-1][0]['content'])
        self.assertIsNone(s['result']);self.assertFalse(s['ready'])
        with patch.object(self.service.engine,'recommend',return_value={'candidates':[]}) as recommend:
            result=self.chat.prepare({'session_id':s['id']})
            query=recommend.call_args.args[0]
            self.assertIn('FKM',query)
            self.assertNotIn('60도인가요',query)
            self.assertTrue(result['ready'])

    def test_attachment_only_failure_retry_and_idempotency(self):
        f=self.upload('시연 HX-17 장비, PAO, 65도'.encode())
        p=self.payload('',attachments=[f['id']]);self.models.fail=True
        s=self.run_chat(p)
        self.assertEqual(s['messages'][-1]['status'],'error')
        self.assertEqual(s['messages'][0]['input_text'],'')
        self.models.fail=False
        s=self.run_chat({**p,'session_id':s['id']})
        self.assertEqual(s['turns'],1);self.assertEqual(len(s['messages']),2)
        self.assertIn('HX-17',self.models.calls[-1][0]['content'])
        self.run_chat(p)
        self.assertEqual(len(self.models.calls),2)
        with self.assertRaises(ValueError):self.run_chat({**p,'text':'changed'})

    def test_cancel_concurrency_and_restart_recovery(self):
        p=self.payload();stream=self.chat.stream(p);s=next(stream)['session']
        with self.assertRaises(ValueError):self.run_chat(self.payload(session_id=s['id']))
        self.assertEqual(next(stream)['type'],'delta');stream.close()
        s=self.chat.get(s['id']);self.assertFalse(s['pending'])
        self.assertEqual(s['messages'][-1]['status'],'cancelled')
        self.run_chat(self.payload('새 질문',session_id=s['id']))
        self.assertEqual([m['role'] for m in self.models.calls[-1]],['user','user'])
        interrupted=self.payload('재시작',session_id=s['id']);self.chat.begin(interrupted)
        restored=Conversation(self.service,self.models).get(s['id'])
        self.assertIsNone(restored['pending']);self.assertEqual(restored['messages'][-1]['status'],'error')

    def test_document_limits_and_image_capability(self):
        f=self.upload(('FKM '+('a'*18000)).encode())
        self.assertTrue(f['truncated']);self.assertEqual(f['characters'],16000)
        s=self.run_chat(self.payload('자료 검토',attachments=[f['id']]))
        s=self.chat.prepare({'session_id':s['id']})
        for candidate in s['result']['candidates']:
            self.assertLess(len(self.service.draft(s['id'],candidate['id'])['body']),30000)
        image=self.upload(b'\x89PNG\r\n\x1a\nfixture','x.png')
        with self.assertRaisesRegex(ValueError,'이미지'):self.run_chat(self.payload(attachments=[image['id']]))
        with self.assertRaises(ValueError):self.chat.attachments.load('../../x')
        with self.assertRaises(ValueError):self.upload(b'bad','x.exe')
        with self.assertRaises(ValueError):self.run_chat(self.payload(attachments=[{}]))

    def test_docx_and_pdf_text_extraction(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>DOCX HX-17 65도</w:t></w:r></w:p></w:body></w:document>')
        f=self.upload(raw.getvalue(),'test.docx')
        self.assertIn('HX-17',self.chat.attachments.load(f['id'])['text'])
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject,NameObject,DictionaryObject
        writer=PdfWriter();page=writer.add_blank_page(width=300,height=300)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 20 200 Td (PDF HX-17 65C) Tj ET')
        page[NameObject('/Contents')]=content
        raw=io.BytesIO();writer.write(raw)
        f=self.upload(raw.getvalue(),'test.pdf')
        self.assertIn('PDF HX-17 65C',self.chat.attachments.load(f['id'])['text'])


class ProviderTests(unittest.TestCase):
    def model(self):
        m=ChatModels({});m.refreshed=time.monotonic()
        m.local=[{'id':'ollama:fixture','name':'fixture','provider':'ollama','enabled':True,'local':True,'vision':False}]
        return m
    def test_ollama_streams_continue_past_200_calls(self):
        m=self.model()
        raw=b'{"message":{"content":"hello"},"done":true,"done_reason":"stop"}\n'
        with patch('rndplz.chat_models.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=lambda *args,**kwargs:io.BytesIO(raw)
            for call in range(1,202):
                with self.subTest(call=call):
                    self.assertEqual(''.join(m.stream('ollama:fixture',[])),'hello')
            self.assertEqual(opener.return_value.open.call_count,201)
            self.assertEqual(m.calls['ollama:fixture'],201)
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(json.loads(request.data)['options']['num_predict'],700)
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],180)

    def test_paid_provider_budgets_remain_limited_to_20_calls(self):
        streams={
            'openai':b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n',
            'claude':b'data: {"type":"content_block_delta","delta":{"text":"hello"}}\ndata: {"type":"message_stop"}\n'}
        for provider,raw in streams.items():
            with self.subTest(provider=provider):
                m=self.model()
                m.configure({'provider':provider,'model':'fixture-model','key':'fixture-secret'})
                with patch('rndplz.chat_models.urllib.request.build_opener') as opener:
                    opener.return_value.open.side_effect=lambda *args,**kwargs:io.BytesIO(raw)
                    for _ in range(20):
                        self.assertEqual(''.join(m.stream(provider,[])),'hello')
                    with self.assertRaisesRegex(ValueError,'호출 한도'):
                        list(m.stream(provider,[]))
                    self.assertEqual(opener.return_value.open.call_count,20)
                    self.assertEqual(m.calls[provider],20)

    def test_stream_contracts_and_secret_boundary(self):
        streams={
            'ollama:fixture':[{'message':{'content':'hello'},'done':False},{'message':{'content':''},'done':True,'done_reason':'stop'}],
            'openai':[{'choices':[{'delta':{'content':'hello'},'finish_reason':None}]},{'choices':[{'delta':{},'finish_reason':'stop'}]}],
            'claude':[{'type':'content_block_delta','delta':{'type':'text_delta','text':'hello'}},{'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}]}
        for provider,events in streams.items():
            with self.subTest(provider=provider):
                m=self.model()
                if provider!='ollama:fixture':m.configure({'provider':provider,'model':'fixture-model','key':'fixture-secret'})
                self.assertNotIn('fixture-secret',json.dumps(m.catalog()))
                raw='\n'.join(('' if provider.startswith('ollama:') else 'data: ')+json.dumps(e) for e in events)+'\n'
                with patch('rndplz.chat_models.urllib.request.build_opener') as opener:
                    opener.return_value.open.return_value=io.BytesIO(raw.encode())
                    self.assertEqual(''.join(m.stream(provider,[{'role':'user','content':'question'}])),'hello')
                    request=opener.return_value.open.call_args.args[0]
                    body=json.loads(request.data)
                    self.assertTrue(body['stream']);self.assertIn('question',json.dumps(body))
                    self.assertNotIn('fixture-secret',json.dumps(body))
    def test_astra_default_standard_tier_and_explicit_override(self):
        from .public_web import PublicModels
        m=PublicModels({'OPENAI_API_KEY':'fixture-secret'})
        self.assertEqual(m.catalog()['default'],'openai')
        self.assertIn('gpt-6-astra',m.catalog()['models'][0]['name'])
        raw=b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n'
        with patch('rndplz.chat_models.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(raw)
            self.assertEqual(''.join(m.stream('openai',[])),'hello')
            request=opener.return_value.open.call_args.args[0]
            body=json.loads(request.data)
            self.assertEqual(body['model'],'gpt-6-astra')
            self.assertEqual(body['service_tier'],'default')
            self.assertEqual(body['reasoning_effort'],'low')
            self.assertNotIn('temperature',body)
            self.assertNotIn('fixture-secret',json.dumps(body)+json.dumps(m.catalog()))
        m=PublicModels({'OPENAI_API_KEY':'fixture-secret','RNDPLZ_OPENAI_MODEL':'explicit-model'})
        self.assertEqual(m.configs['openai']['model'],'explicit-model')
        self.assertEqual(PublicModels({}).catalog()['default'],'guide')
        local=self.model();local.configs['openai']={'key':'fixture-secret','model':'gpt-6-astra'}
        self.assertEqual(local.catalog()['default'],'openai')

    def test_incomplete_stream_and_remote_local_address(self):
        m=self.model()
        with patch('rndplz.chat_models.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(b'{"message":{"content":"partial"}}\n')
            with self.assertRaisesRegex(ValueError,'중간'):list(m.stream('ollama:fixture',[]))
        with self.assertRaises(ValueError):ChatModels({'RNDPLZ_OLLAMA_URL':'https://example.com'})


if __name__=='__main__':unittest.main()
