"""Serve one local game through plain HTTP forms."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import parse_qs
from game_rules import create_initial_game_state, apply_player_move
from game_page import render_game_page


class GameServer(ThreadingHTTPServer):
    def __init__(self, address):
        super().__init__(address, GameRequestHandler)
        self.game_state = create_initial_game_state()
        self.game_lock = threading.Lock()


class GameRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/':
            self.send_error(404)
            return
        with self.server.game_lock:
            page = render_game_page(self.server.game_state).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self):
        if self.path not in ('/move', '/restart'):
            self.send_error(404)
            return
        try:
            content_length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= content_length <= 1024:
                raise ValueError('Invalid form size')
            form = parse_qs(self.rfile.read(content_length).decode('utf-8'))
            with self.server.game_lock:
                if self.path == '/restart':
                    self.server.game_state = create_initial_game_state()
                else:
                    cell_values = form.get('cell', [])
                    if len(cell_values) != 1:
                        raise ValueError('Choose exactly one cell')
                    self.server.game_state = apply_player_move(self.server.game_state, int(cell_values[0]))
        except (ValueError, UnicodeError):
            self.send_error(400, 'Invalid move')
            return
        self.send_response(303)
        self.send_header('Location', '/')
        self.send_header('Content-Length', '0')
        self.end_headers()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    options = parser.parse_args()
    server = GameServer(('127.0.0.1', options.port))
    print('Game: http://127.0.0.1:' + str(server.server_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
