"""Local-only web host for the shared browser and desktop UI."""
import argparse
import json
import mimetypes
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import webbrowser
from urllib.parse import urlparse, unquote

from simulator import Simulator
from desktop_session import APP_ID, DesktopSession, open_browser
from updates import UpdateChecker


def main():
    default_root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int)
    parser.add_argument('--web-root',type=Path)
    parser.add_argument('--root',type=Path,default=default_root)
    parser.add_argument('--open-browser',action='store_true',help='Open the local HTML interface after startup')
    parser.add_argument('--desktop',action='store_true',help='Linux managed desktop session (single instance, browser, idle exit)')
    parser.add_argument('--no-open-browser',action='store_true',help='Do not launch a browser (headless desktop acceptance)')
    parser.add_argument('--session-idle-seconds',type=float,default=180,help='Desktop session client inactivity limit (default: 180)')
    args=parser.parse_args()
    if args.desktop and not sys.platform.startswith('linux'):
        parser.error('--desktop is only available on Linux; Windows uses CIMC-Studio.exe')
    if not 1 <= args.session_idle_seconds <= 86400:
        parser.error('--session-idle-seconds must be between 1 and 86400')
    if args.port is None:args.port=0 if args.desktop else 8765
    session=DesktopSession(idle_seconds=args.session_idle_seconds) if args.desktop else None
    try:
        if session and not session.acquire():
            url=session.existing_url()
            print(f'CIMC Studio existing session {url}',flush=True)
            if not args.no_open_browser:open_browser(url)
            return 0
        return serve(args,session)
    finally:
        if session:session.close()


def serve(args,session):
    web=(args.web_root or args.root/'web').resolve()
    simulator=Simulator(args.root)
    updates=UpdateChecker('0.3.0')
    stop_event=threading.Event()
    launch_errors=[]

    def decorate(state):
        state['engine'].update(desktopSession=bool(session),instanceId=session.instance_id if session else None)
        return state

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass

        def _send(self,status,body,content_type='application/json; charset=utf-8'):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass

        def _allowed(self):
            host=self.headers.get('Host','')
            valid={f'127.0.0.1:{args.port}',f'localhost:{args.port}'}
            if host not in valid:return False
            origin=self.headers.get('Origin')
            return not origin or origin in {'http://'+v for v in valid}

        def do_GET(self):
            if not self._allowed():return self._send(403,{'error':'Only local same-origin requests are allowed'})
            path=urlparse(self.path).path
            if path=='/api/state':
                if session:session.touch()
                return self._send(200,decorate(simulator.state()))
            if path=='/api/project':return self._send(200,simulator.project())
            if path=='/api/updates':
                result=updates.check(force=urlparse(self.path).query=='force=1')
                result['platform']='windows' if sys.platform=='win32' else 'linux'
                return self._send(200,result)
            if path=='/api/health':return self._send(200,{'ok':True,'app':APP_ID,'version':'0.3.0','desktopSession':bool(session),'instanceId':session.instance_id if session else None})
            if path=='/api/demo':
                p=args.root/'firmware'/'demo.hex'
                return self._send(200,p.read_bytes(),'application/octet-stream')
            target=(web/unquote(path.lstrip('/') or 'index.html')).resolve()
            if not target.is_relative_to(web) or not target.is_file():return self._send(404,{'error':'Not found'})
            typ=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            if typ.startswith('text/') or typ=='application/javascript':typ+='; charset=utf-8'
            return self._send(200,target.read_bytes(),typ)

        def do_POST(self):
            if not self._allowed():return self._send(403,{'error':'Only local same-origin requests are allowed'})
            path=urlparse(self.path).path
            if path not in ('/api/command','/api/session/quit'):return self._send(404,{'error':'Not found'})
            if path=='/api/session/quit':
                if not session:return self._send(404,{'error':'No managed desktop session'})
                if not self.headers.get('Origin') or self.headers.get_content_type()!='application/json':
                    return self._send(403,{'error':'Desktop exit requires a same-origin JSON request'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=6*1024*1024:return self._send(413,{'error':'Request too large or empty'})
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):raise ValueError('Request must be a JSON object')
                if path=='/api/session/quit':
                    if not session.authorized(data.get('instanceId')):return self._send(403,{'error':'Invalid desktop instance'})
                    self._send(200,{'ok':True})
                    stop_event.set()
                    return
                if session:session.touch()
                result=simulator.command(data)
                self._send(200,decorate(result))
            except (ValueError,KeyError,TypeError,UnicodeError) as e:self._send(400,{'error':str(e)})
            except Exception as e:self._send(500,{'error':str(e)})

    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    args.port=server.server_address[1]
    url=f'http://127.0.0.1:{args.port}/'
    print(f'CIMC Lab 0.3.0 {url}',flush=True)
    old_sigterm=None
    if session:
        session.publish(url)
        session.log(f'Started {url}')
        def monitor():
            if not args.no_open_browser:
                try:open_browser(url)
                except Exception as error:
                    launch_errors.append(str(error));session.log(str(error));print(str(error),file=sys.stderr,flush=True)
                    stop_event.set()
            while not stop_event.wait(.2):
                if session.expired():
                    session.log('Closed after client inactivity')
                    stop_event.set()
            server.shutdown()
        old_sigterm=signal.signal(signal.SIGTERM,lambda *_:stop_event.set())
        threading.Thread(target=monitor,daemon=True).start()
    elif args.open_browser:
        threading.Timer(0.35,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}/')).start()
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:
        stop_event.set()
        server.server_close()
        simulator.close()
        if old_sigterm is not None:signal.signal(signal.SIGTERM,old_sigterm)
        if session:session.log('Stopped')
    return 1 if launch_errors else 0


if __name__=='__main__':raise SystemExit(main())
