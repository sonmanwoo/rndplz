import json
import io
import time
import tempfile
import threading
import unittest
from .gemma_bridge import GemmaRelay
from .public_web import PublicApp,PublicModels


class BridgeTests(unittest.TestCase):
    def test_isolated_streams_and_idempotent_chunks(self):
        relay=GemmaRelay('fixture-token',timeout=3);relay.seen=time.monotonic()
        results={}
        def request(name): results[name]=''.join(relay.stream([{'role':'user','content':name}]))
        threads=[threading.Thread(target=request,args=(name,)) for name in ('a','b')]
        for t in threads:t.start()
        jobs=[relay.poll(),relay.poll()]
        for job in reversed(jobs):
            payload={'id':job['id'],'lease':job['lease'],'sequence':0,'text':job['messages'][0]['content']+' answer'}
            relay.deliver(payload);relay.deliver(payload)
            relay.deliver({'id':job['id'],'lease':job['lease'],'sequence':1,'done':True})
        for t in threads:t.join(4)
        self.assertEqual(results,{'a':'a answer','b':'b answer'})
        self.assertFalse(relay.jobs)
        with self.assertRaises(ValueError):relay.deliver(payload)

    def test_no_worker_wrong_lease_cancellation_and_timeout(self):
        relay=GemmaRelay('fixture-token',timeout=.05)
        with self.assertRaisesRegex(ValueError,'기다리고'):list(relay.stream([]))
        relay.seen=time.monotonic()
        with self.assertRaisesRegex(ValueError,'시간'):list(relay.stream([]))
        self.assertFalse(relay.jobs)
        relay.jobs['fixture']={'lease':'valid','claimed':True}
        with self.assertRaises(ValueError):relay.deliver({'id':'fixture','lease':'invalid'})
        self.assertFalse(relay.authorized('wrong'))
        self.assertFalse(GemmaRelay('').authorized(''))

    def test_worker_auth_does_not_create_visitor_or_expose_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            app=PublicApp(directory,{'RNDPLZ_BRIDGE_TOKEN':'fixture-secret','RNDPLZ_PUBLIC_MODEL':'bridge'})
            result={}
            def start(status,headers):result['status']=status
            env={'HTTP_HOST':'localhost','PATH_INFO':'/api/worker/poll','REQUEST_METHOD':'POST',
                 'CONTENT_LENGTH':'2','wsgi.input':io.BytesIO(b'{}')}
            data=b''.join(app(env,start))
            self.assertTrue(result['status'].startswith('403'))
            self.assertFalse(app.contexts)
            self.assertNotIn(b'fixture-secret',data)
            self.assertEqual(app.models.catalog()['default'],'guide')
            app.models.bridge.seen=time.monotonic()
            self.assertEqual(app.models.catalog()['default'],'bridge')
            self.assertNotIn('fixture-secret',json.dumps(app.models.catalog()))
            self.assertNotIn('openai',[m['id'] for m in app.models.catalog()['models']])


if __name__=='__main__':unittest.main()
