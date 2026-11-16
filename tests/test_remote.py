import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote


class FakeCore:
    def __init__(self):
        self.actions = []

    def terminals(self):
        return [{'address': 't1', 'state': 'live', 'status': 'idle'}]

    def snapshot(self):
        return {'terminals': self.terminals(), 'spaces': [], 'warning': None}

    def read(self, address):
        if address != 't1':
            raise ValueError('unknown terminal')
        return {'text': '<script>untrusted output</script> 中文', 'complete': True}

    def act(self, data):
        self.actions.append(data)
        return {'sent': True}


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = FakeCore()
        cls.stop = threading.Event()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), remote.handler(cls.core, 'secret', 'instance', cls.stop))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.http = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, data=None, token='secret', extra=None):
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', **(extra or {})}
        req = Request(self.base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
        return self.http.open(req, timeout=3)

    def test_no_auth_cannot_read_or_write(self):
        for path in ['/api/terminals', '/api/action', '/api/spaces/create', '/api/terminals/create']:
            with self.assertRaises(HTTPError) as caught:
                self.request(path, {'action': 'send', 'address': 't1', 'text': 'bad'}, token='wrong')
            self.assertEqual(caught.exception.code, 401)

    def test_authenticated_list_and_read(self):
        with self.request('/api/terminals', {}) as response:
            self.assertEqual(json.load(response)['terminals'][0]['address'], 't1')
        with self.request('/api/read', {'address': 't1'}) as response:
            self.assertIn('中文', json.load(response)['text'])

    def test_snapshot_is_authenticated(self):
        with self.request('/api/snapshot', {}) as response:
            self.assertEqual(json.load(response)['terminals'][0]['address'], 't1')
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/snapshot', {}, token='wrong')
        self.assertEqual(caught.exception.code, 401)

    def test_shutdown_requires_instance(self):
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/shutdown', {})
        self.assertEqual(caught.exception.code, 403)
        self.assertFalse(self.stop.is_set())

    def test_invalid_json_shape(self):
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/read', ['wrong'])
        self.assertEqual(caught.exception.code, 400)

    def test_static_content_and_security_headers(self):
        with self.request('/') as response:
            self.assertIn('frame-ancestors', response.headers['Content-Security-Policy'])
            self.assertIn(b'<meta name="viewport"', response.read())
        with self.assertRaises(HTTPError) as caught:
            self.request('/.runtime/token')
        self.assertEqual(caught.exception.code, 404)

    def test_write_acknowledgement(self):
        with self.request('/api/action', {'action': 'key', 'address': 't1', 'key': 'enter'}) as response:
            self.assertTrue(json.load(response)['ok'])


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.core = remote.Core('hc')

    def test_send_preserves_text_and_does_not_force(self):
        with patch.object(self.core, 'terminals', return_value=[{'address': 't1'}]), patch.object(self.core, 'call', return_value={'sent': True}) as call:
            self.core.act({'address': 't1', 'action': 'send', 'text': '--force 中文\nsecond line'})
            call.assert_called_once_with('send', '--json', 't1', '--', '--force 中文\nsecond line', timeout=90)

    def test_rejects_unknown_terminal(self):
        with patch.object(self.core, 'terminals', return_value=[]):
            with self.assertRaises(ValueError):
                self.core.act({'address': 't1', 'action': 'send', 'text': 'hello'})

    def test_rejects_unapproved_key_and_oversize_message(self):
        with patch.object(self.core, 'terminals', return_value=[{'address': 't1'}]):
            for data in [{'action': 'key', 'key': 'ctrl+z'}, {'action': 'send', 'text': 'x' * 10001}]:
                with self.assertRaises(ValueError):
                    self.core.act({'address': 't1', **data})

    def test_core_error_propagates(self):
        import subprocess
        failed = subprocess.CompletedProcess([], 9, '', '{"error":{"kind":"blocked"}}')
        with patch('remote.subprocess.run', return_value=failed):
            with self.assertRaisesRegex(RuntimeError, 'blocked'):
                self.core.call('send', 't1', 'hello')

    def test_create_space_validates_and_starts_only_default_shell(self):
        import subprocess
        root = str(Path(__file__).resolve().parents[1])
        success = subprocess.CompletedProcess([], 0, '{"space":"s-new","terminal":"t-new"}', '')
        with patch('remote.shutil.which', return_value='herdr-app'), patch('remote.subprocess.run', return_value=success) as run:
            result = self.core.create_space({'name':'  Demo  ', 'folder':root, 'argv':['codex']})
            self.assertEqual(result['space'], 's-new')
            args = run.call_args.args[0]
            self.assertEqual(args[:3], ['herdr-app', 'do', 'space.new'])
            payload = json.loads(args[3])
            self.assertEqual(payload['name'], 'Demo')
            self.assertEqual(payload['machine'], '')
            self.assertNotIn('argv', payload)
        for data in [{'name':'', 'folder':root}, {'name':'ok','folder':'relative'}, {'name':'ok','folder':root+'-missing'}]:
            with self.assertRaises(ValueError):
                self.core.create_space(data)

    def test_create_terminal_targets_explicit_space_and_folder(self):
        import subprocess
        success = subprocess.CompletedProcess([],0,'{"tab":"tab-new","terminal":"t-new"}','')
        with patch.object(self.core,'snapshot',return_value={'spaces':[{'id':'s2','folder':'D:/second'}]}), patch('remote.shutil.which',return_value='herdr-app'), patch('remote.subprocess.run',return_value=success) as run:
            self.assertEqual(self.core.create_terminal({'space':'s2'})['terminal'],'t-new')
            args=run.call_args.args[0]
            self.assertEqual(args[:3],['herdr-app','do','tab.new'])
            self.assertEqual(json.loads(args[3]),{'space':'s2','folder':'D:/second','name':'终端'})
            with self.assertRaises(ValueError):
                self.core.create_terminal({'space':'missing'})

    def test_space_keeps_finished_and_missing_panes(self):
        import subprocess
        records = [{'address':'agent','state':'live','agent':'codex'}, {'address':'shell','state':'live','agent':None}, {'address':'ended','state':'finished'}, {'address':'old','state':'finished'}]
        spaces = [{'id':'space','tabs':[{'id':'tab','terminals':[{'terminal':a} for a in ['agent','shell','ended','pending']]}]}]
        result = subprocess.CompletedProcess([],0,json.dumps({'spaces':spaces}),'')
        with patch.object(self.core, 'terminals', return_value=records), patch('remote.shutil.which', return_value='herdr-app'), patch('remote.subprocess.run', return_value=result):
            snapshot = self.core.snapshot()
        self.assertEqual({t['address'] for t in snapshot['terminals']}, {'agent','shell','ended','pending'})
        self.assertEqual(next(t for t in snapshot['terminals'] if t['address']=='pending')['state'], 'unavailable')

    def test_finished_terminal_rejects_input_but_allows_read(self):
        with patch.object(self.core,'terminals',return_value=[{'address':'t1','state':'finished'}]), patch.object(self.core,'call',return_value={'text':'old output'}) as call:
            self.assertEqual(self.core.read('t1')['text'], 'old output')
            with self.assertRaisesRegex(ValueError,'已结束'):
                self.core.act({'address':'t1','action':'send','text':'hello'})
            self.assertEqual(call.call_count,1)

    def test_snapshot_does_not_count_powershell_as_agent(self):
        with patch.object(self.core, 'terminals', return_value=[{'address':'t1','agent':r'C:\Tools\pwsh.exe'}]), patch('remote.shutil.which', return_value=None):
            result = self.core.snapshot()
            self.assertIsNone(result['terminals'][0]['agent'])
            self.assertTrue(result['terminals'][0]['program'])

    def test_snapshot_cache_and_app_fallback(self):
        with patch.object(self.core, 'terminals', return_value=[{'address': 't1'}]) as terminals, patch('remote.shutil.which', return_value=None):
            first = self.core.snapshot()
            second = self.core.snapshot()
            self.assertIs(first, second)
            self.assertEqual(first['spaces'], [])
            self.assertTrue(first['warning'])
            terminals.assert_called_once()

    def test_unsent_message_is_not_acknowledged(self):
        with patch.object(self.core, 'terminals', return_value=[{'address': 't1'}]), patch.object(self.core, 'call', return_value={'sent': False, 'reason': 'draft'}):
            with self.assertRaisesRegex(RuntimeError, 'not submitted'):
                self.core.act({'address': 't1', 'action': 'send', 'text': 'hello'})


if __name__ == '__main__':
    unittest.main()
