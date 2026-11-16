"""Opt-in integration check: creates and cleans up only its own hc terminal."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote

cfg = remote.config()
token = remote.init_state()
core = remote.Core(cfg['hc'])
created = core.call('run', '--bg', '--no-parent', '--no-notify', '--name', 'core-remote-smoke',
                    'powershell.exe', '-NoLogo', '-NoProfile', '-NoExit')
# hc run returns the actual address; never infer one from another terminal.
address = created.get('address') or created.get('terminal', {}).get('address')
if not address:
    raise RuntimeError('Unexpected hc run result: ' + json.dumps(created))
print('Created owned smoke terminal:', address)
try:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        screen = core.read(address).get('text', '')
        if 'PS ' in screen:
            break
        time.sleep(0.2)
    result = remote.local_request(cfg, token, '/api/action', {
        'address': address, 'action': 'send', 'text': "Write-Output ('core-remote-' + 'smoke-ok')"
    })
    assert result['ok'], result
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        screen = remote.local_request(cfg, token, '/api/read', {'address': address})
        if 'core-remote-smoke-ok' in screen.get('text', ''):
            break
        time.sleep(0.2)
    else:
        raise AssertionError('Expected output missing')
    result = remote.local_request(cfg, token, '/api/action', {'address': address, 'action': 'key', 'key': 'esc'})
    assert result['ok'], result
    print('PASS: real hc terminal listed, message submitted, output read, key sent')
finally:
    core.call('kill', address)
    core.call('rm', address)
    print('Removed owned smoke terminal:', address)
