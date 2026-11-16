"""Authenticated, dependency-free browser bridge for herdr-core on Windows."""
import argparse
from contextlib import contextmanager
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.runtime'
HTTP = build_opener(ProxyHandler({}))
KEYS = {'enter', 'esc', 'tab', 'up', 'down', 'left', 'right', 'ctrl+c'}


def config():
    path = ROOT / 'config.json'
    if not path.exists():
        shutil.copyfile(ROOT / 'config.example.json', path)
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(cfg.get('port'), int) or not 1024 <= cfg['port'] <= 65535:
        raise ValueError('port must be between 1024 and 65535')
    if cfg.get('tunnel') not in {'none', 'named', 'temp'}:
        raise ValueError('tunnel must be none, named or temp')
    return cfg


def init_state():
    STATE.mkdir(exist_ok=True)
    if os.name == 'nt':
        # Local token and private connection URL belong only to this Windows user.
        user = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True)
        sid = re.search(r'S-1-\d+(?:-\d+)+', user).group()
        result = subprocess.run(['icacls', str(STATE), '/inheritance:r', '/grant:r',
                                 f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Could not restrict .runtime permissions: ' + result.stderr)
    token_path = STATE / 'token'
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), encoding='ascii')
    if os.name != 'nt':
        STATE.chmod(0o700)
        token_path.chmod(0o600)
    return token_path.read_text(encoding='ascii').strip()


@contextmanager
def manager_lock():
    """Serialize start/stop to prevent double launches and reused-state races."""
    with open(STATE / 'manager.lock', 'a+b') as lock:
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('Another service command is running; retry when it finishes') from None
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


class Core:
    def __init__(self, binary):
        self.binary = shutil.which(binary) or binary
        self.slots = threading.BoundedSemaphore(6)
        self.snapshot_lock = threading.Lock()
        self.snapshot_time = 0
        self.snapshot_value = None

    def call(self, *args, timeout=15):
        with self.slots:
            result = subprocess.run([self.binary, *args], capture_output=True,
                                    encoding='utf-8', errors='replace', timeout=timeout,
                                    env={key: value for key, value in os.environ.items() if key != 'HC_TERMINAL_ID'},
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'hc command failed')
        return json.loads(result.stdout)

    def terminals(self):
        return self.call('ls', '--all').get('terminals', [])

    def create_space(self, data):
        name = data.get('name')
        folder = data.get('folder')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError('Space 名称需要 1～80 个字符')
        if not isinstance(folder, str) or not folder.strip():
            raise ValueError('请填写公司电脑上的绝对目录')
        path = Path(folder.strip())
        if not path.is_absolute() or not path.is_dir():
            raise ValueError('目录不存在或不是绝对路径，请填写公司电脑上的现有目录')
        app = shutil.which('herdr-app')
        if not app:
            raise RuntimeError('未找到 Herdr App')
        # Only a normal shell: browser cannot supply argv, task or implicit focused targets.
        result = subprocess.run([app, 'do', 'space.new', json.dumps({
            'name': name.strip(), 'folder': str(path), 'machine': ''
        }, ensure_ascii=False)], capture_output=True, encoding='utf-8', errors='replace',
            timeout=15, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or '创建 Space 失败')
        created = json.loads(result.stdout)
        if created.get('error') or not created.get('space'):
            raise RuntimeError(str(created.get('error', 'Herdr 未返回 Space 标识')))
        with self.snapshot_lock:
            self.snapshot_time = 0
        logging.info('Space created id=%s', created['space'])
        return created

    def create_terminal(self, data):
        space_id = data.get('space')
        if not isinstance(space_id, str) or not space_id:
            raise ValueError('请选择 Space')
        space = next((s for s in self.snapshot()['spaces'] if s['id'] == space_id), None)
        if space is None:
            raise ValueError('Space 不存在，请刷新列表')
        app = shutil.which('herdr-app')
        if not app:
            raise RuntimeError('未找到 Herdr App')
        payload = {'space': space_id, 'name': '终端'}
        if space.get('folder'):
            payload['folder'] = space['folder']
        result = subprocess.run([app, 'do', 'tab.new', json.dumps(payload, ensure_ascii=False)],
            capture_output=True, encoding='utf-8', errors='replace', timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or '创建终端失败')
        created = json.loads(result.stdout)
        if created.get('error') or not created.get('terminal'):
            raise RuntimeError(str(created.get('error', 'Herdr 未返回终端标识')))
        with self.snapshot_lock:
            self.snapshot_time = 0
        logging.info('Terminal created space=%s terminal=%s', space_id, created['terminal'])
        return created

    def snapshot(self):
        with self.snapshot_lock:
            if self.snapshot_value is not None and time.monotonic() - self.snapshot_time < 1:
                return self.snapshot_value
            terminals = self.terminals()
            for terminal in terminals:
                program = re.split(r'[\\/]', terminal.get('agent') or '')[-1].lower()
                if program in {'pwsh', 'pwsh.exe', 'powershell', 'powershell.exe', 'cmd.exe',
                               'cmd', 'bash', 'bash.exe', 'sh', 'zsh', 'fish', 'nu', 'nu.exe'}:
                    terminal['program'] = terminal.get('agent')
                    terminal['agent'] = None
            warning = None
            try:
                app = shutil.which('herdr-app')
                if not app:
                    raise RuntimeError('Herdr App unavailable')
                result = subprocess.run([app, 'ls'], capture_output=True, encoding='utf-8',
                                        errors='replace', timeout=4,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if result.returncode:
                    raise RuntimeError('Herdr App window unavailable')
                spaces = json.loads(result.stdout)['spaces']
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
                spaces = []
                warning = 'Herdr 窗口未连接，仍可通过 Agents 操作所有运行中的终端。'
            # App layout is authoritative for membership. A finished shell can
            # still occupy a pane; hc ls without --all hides it.
            references = {}
            for space in spaces:
                for tab in space.get('tabs', []):
                    for pane in tab.get('terminals', []):
                        address = pane.get('terminal')
                        if not address:
                            continue
                        references[address] = {
                            'address': address, 'agent': pane.get('app'),
                            'name': pane.get('name'), 'state': 'unavailable',
                            'status': None, 'cwd': space.get('folder', ''),
                            'where': f'{space.get("name", "")} / {tab.get("name", "")}'
                        }
            terminals = [t for t in terminals if t.get('state') != 'finished' or t['address'] in references]
            present = {t['address'] for t in terminals}
            terminals.extend(t for address, t in references.items() if address not in present)
            self.snapshot_value = {'terminals': terminals, 'spaces': spaces, 'warning': warning}
            self.snapshot_time = time.monotonic()
            return self.snapshot_value

    def check(self, address):
        if isinstance(address, str):
            for terminal in self.terminals():
                if terminal['address'] == address:
                    return terminal
        raise ValueError('Terminal no longer exists; refresh the list')

    def read(self, address):
        self.check(address)
        return self.call('read', address, '--json', '--lines', '0')

    def act(self, data):
        address = data.get('address')
        terminal = self.check(address)
        if terminal.get('state') == 'finished':
            raise ValueError('终端已结束，仅支持查看输出。请在 Herdr App 中重新打开终端。')
        action = data.get('action')
        if action == 'send':
            text = data.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 10000:
                raise ValueError('Message must contain 1–10000 characters')
            # No force: hc preserves blocked permission dialogs and unfinished drafts.
            result = self.call('send', '--json', address, '--', text, timeout=90)
            if result.get('sent') is False:
                raise RuntimeError('Message was not submitted: ' + str(result.get('reason', result)))
            return result
        if action == 'key':
            key = data.get('key')
            if key not in KEYS:
                raise ValueError('Unsupported key')
            return self.call('keys', '--json', address, key)
        raise ValueError('Unknown action')


def handler(core, token, instance, stop):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Never log query strings, tokens or terminal content.
            logging.info('%s %s', self.command, self.path.split('?')[0])

        def reply(self, status, data, mime='application/json; charset=utf-8'):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            supplied = self.headers.get('Authorization', '')
            return hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode())

        def dispatch(self):
            path = urlsplit(self.path).path
            if self.command == 'GET' and path in {'/', '/app.js', '/style.css', '/HackNerdFont-Regular.woff2', '/HackNerdFont-LICENSE.txt'}:
                name, mime = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              '/style.css': ('style.css', 'text/css; charset=utf-8'),
                              '/HackNerdFont-Regular.woff2': ('HackNerdFont-Regular.woff2', 'font/woff2'),
                              '/HackNerdFont-LICENSE.txt': ('HackNerdFont-LICENSE.txt', 'text/plain; charset=utf-8')}[path]
                return self.reply(200, (ROOT / 'web' / name).read_bytes(), mime)
            if not self.authorized():
                return self.reply(401, {'error': 'Authentication required'})
            if self.command == 'GET' and path == '/api/health':
                return self.reply(200, {'instance': instance, 'pid': os.getpid()})
            if self.command != 'POST':
                return self.reply(404, {'error': 'Not found'})
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                return self.reply(400, {'error': 'Invalid body size'})
            if self.headers.get_content_type() != 'application/json':
                return self.reply(415, {'error': 'JSON required'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
            if path == '/api/terminals':
                return self.reply(200, {'terminals': core.terminals()})
            if path == '/api/snapshot':
                return self.reply(200, core.snapshot())
            if path == '/api/spaces/create':
                return self.reply(200, core.create_space(data))
            if path == '/api/terminals/create':
                return self.reply(200, core.create_terminal(data))
            if path == '/api/read':
                return self.reply(200, core.read(data.get('address')))
            if path == '/api/action':
                result = core.act(data)
                logging.info('action=%s terminal=%s', data.get('action'), data.get('address'))
                return self.reply(200, {'ok': True, 'result': result})
            if path == '/api/shutdown':
                # Even an authenticated browser cannot stop the supervisor through a tunnel.
                if self.headers.get('X-Instance') != instance:
                    return self.reply(403, {'error': 'Local manager required'})
                self.reply(200, {'ok': True})
                stop.set()
                return
            self.reply(404, {'error': 'Not found'})

        def handle_request(self):
            self.connection.settimeout(100)
            try:
                self.dispatch()
            except (ValueError, json.JSONDecodeError) as exc:
                self.reply(400, {'error': str(exc)})
            except subprocess.TimeoutExpired:
                self.reply(504, {'error': '创建结果尚未确认，请先刷新工作区列表，避免重复创建。' if urlsplit(self.path).path in {'/api/spaces/create', '/api/terminals/create'} else 'hc timed out. Delivery is uncertain; read the terminal before retrying.'})
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except Exception as exc:
                logging.exception('Request failed')
                self.reply(502, {'error': str(exc)})

        do_GET = handle_request
        do_POST = handle_request
    return Handler


def local_request(cfg, token, path, body=None, instance=None):
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    if instance:
        headers['X-Instance'] = instance
    request = Request(f'http://127.0.0.1:{cfg["port"]}{path}',
                      data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with HTTP.open(request, timeout=3) as response:
        return json.load(response)


def active(cfg, token):
    try:
        state = json.loads((STATE / 'state.json').read_text())
        health = local_request({**cfg, 'port': state['port']}, token, '/api/health')
        return state if hmac.compare_digest(health['instance'], state['instance']) else None
    except (OSError, ValueError, KeyError, URLError):
        return None


def worker(cfg, token):
    log = RotatingFileHandler(STATE / 'service.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[log], format='%(asctime)s %(levelname)s %(message)s')
    instance = secrets.token_hex(16)
    stop = threading.Event()
    server = ThreadingHTTPServer(('127.0.0.1', cfg['port']), handler(Core(cfg['hc']), token, instance, stop))
    server.daemon_threads = True
    tunnel = None
    tunnel_log = None
    state = {'instance': instance, 'pid': os.getpid(), 'port': cfg['port'], 'url': f'http://127.0.0.1:{cfg["port"]}', 'tunnel': cfg['tunnel']}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if cfg['tunnel'] != 'none':
            binary = shutil.which('cloudflared')
            if not binary:
                raise RuntimeError('cloudflared is not installed')
            args = [binary, 'tunnel']
            if cfg['tunnel'] == 'named':
                tunnel_cfg = Path(cfg['tunnel_config']).expanduser().resolve()
                if not tunnel_cfg.is_file():
                    raise ValueError('Tunnel configuration does not exist')
                if not cfg.get('public_url', '').startswith('https://'):
                    raise ValueError('named tunnel requires an https public_url')
                args += ['--config', str(tunnel_cfg), 'run', cfg['tunnel_name']]
                state['url'] = cfg['public_url'].rstrip('/')
            else:
                args += ['--url', state['url']]
            tunnel_log = open(STATE / 'tunnel.log', 'w', encoding='utf-8')
            tunnel = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=tunnel_log, stderr=tunnel_log,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            state['tunnel_pid'] = tunnel.pid
        (STATE / 'state.json').write_text(json.dumps(state), encoding='utf-8')
        logging.info('Ready on loopback port %s, tunnel=%s', cfg['port'], cfg['tunnel'])
        while not stop.wait(0.5):
            if tunnel and tunnel.poll() is not None:
                raise RuntimeError('Cloudflare tunnel exited; see .runtime/tunnel.log')
            if tunnel and cfg['tunnel'] == 'temp' and 'trycloudflare.com' not in state['url']:
                match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', (STATE / 'tunnel.log').read_text(encoding='utf-8', errors='replace'))
                if match:
                    state['url'] = match[0]
                    (STATE / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    finally:
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait()
        if tunnel_log:
            tunnel_log.close()
        server.shutdown()
        server.server_close()
        (STATE / 'state.json').unlink(missing_ok=True)
        logging.info('Stopped; Herdr core and terminals were left running')


def manage(action):
    cfg = config()
    token = init_state()
    if action == 'worker':
        return worker(cfg, token)
    state = active(cfg, token)
    if action in {'stop', 'restart'} and state:
        local_request({**cfg, 'port': state['port']}, token, '/api/shutdown', {}, state['instance'])
        for _ in range(100):
            if not active(cfg, token):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('Service did not stop; inspect logs before restarting')
        state = None
    if action in {'start', 'restart'} and not state:
        Core(cfg['hc']).terminals()  # Fail before backgrounding if core is unavailable.
        # Detached process + new process group; break away from a parent job when permitted.
        flags = 0
        if os.name == 'nt':
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        output = open(STATE / 'launcher.log', 'ab')
        kwargs = dict(cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output, close_fds=True)
        try:
            if os.name == 'nt':
                try:
                    process = subprocess.Popen([sys.executable, str(ROOT / 'remote.py'), 'worker'],
                                               creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
                except PermissionError:
                    process = subprocess.Popen([sys.executable, str(ROOT / 'remote.py'), 'worker'], creationflags=flags, **kwargs)
            else:
                process = subprocess.Popen([sys.executable, str(ROOT / 'remote.py'), 'worker'], start_new_session=True, **kwargs)
        finally:
            output.close()
        for _ in range(100):
            state = active(cfg, token)
            if state:
                break
            if process.poll() is not None:
                raise RuntimeError('Startup failed; see .runtime/launcher.log and service.log')
            time.sleep(0.1)
        if not state:
            raise RuntimeError('Startup timed out; inspect logs before retrying')
    if action == 'url':
        if not state:
            raise RuntimeError('Service is stopped')
        print(state['url'] + '/#token=' + token)
    elif state:
        print(f'RUNNING pid={state["pid"]} tunnel={state["tunnel"]}')
        print('Local: http://127.0.0.1:' + str(state['port']))
        print('Remote: ' + state['url'])
        print('Run .\\service.ps1 url for the private login link.')
    else:
        print('STOPPED')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status', 'restart', 'url', 'worker'])
    try:
        action = parser.parse_args().action
        if action == 'worker':
            manage(action)
        else:
            STATE.mkdir(exist_ok=True)
            with manager_lock():
                manage(action)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
