"""Local-only web host for the shared browser and desktop UI."""
import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import webbrowser
from urllib.parse import urlparse, unquote

from simulator import Simulator


def main():
    default_root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--web-root',type=Path)
    parser.add_argument('--root',type=Path,default=default_root)
    parser.add_argument('--open-browser',action='store_true',help='Open the local HTML interface after startup')
    args=parser.parse_args()
    web=(args.web_root or args.root/'web').resolve()
    simulator=Simulator(args.root)

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
            if path=='/api/state':return self._send(200,simulator.state())
            if path=='/api/project':return self._send(200,simulator.project())
            if path=='/api/health':return self._send(200,{'ok':True,'version':'0.1.0'})
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
            if urlparse(self.path).path!='/api/command':return self._send(404,{'error':'Not found'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=6*1024*1024:return self._send(413,{'error':'Request too large or empty'})
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):raise ValueError('Request must be a JSON object')
                result=simulator.command(data)
                self._send(200,result)
            except (ValueError,KeyError,TypeError,UnicodeError) as e:self._send(400,{'error':str(e)})
            except Exception as e:self._send(500,{'error':str(e)})

    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    args.port=server.server_address[1]
    print(f'CIMC Lab 0.1.0 http://127.0.0.1:{args.port}',flush=True)
    if args.open_browser:
        threading.Timer(0.35,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}/')).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:simulator.closed=True;server.server_close()


if __name__=='__main__':main()
