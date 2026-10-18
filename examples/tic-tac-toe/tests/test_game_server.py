import http.client
import threading
import unittest
from server import GameServer


class GameServerTests(unittest.TestCase):
    def setUp(self):
        self.server = GameServer(('127.0.0.1', 0))
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def request(self, path='/', body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request('POST' if body is not None else 'GET', path, body=body,
                               headers={'Content-Type': 'application/x-www-form-urlencoded'})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode('utf-8')
        finally:
            connection.close()

    def test_initial_page_and_move_redirect(self):
        status, headers, page = self.request()
        self.assertEqual(status, 200)
        self.assertIn('charset=utf-8', headers['Content-Type'])
        self.assertIn('Ход: X', page)
        status, headers, _ = self.request('/move', 'cell=0')
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/')
        self.assertIn('Ход: O', self.request()[2])

    def test_invalid_moves_do_not_change_the_game(self):
        self.request('/move', 'cell=0')
        before = self.request()[2]
        for body in ('cell=0', 'cell=-1', 'cell=9', 'cell=bad', 'cell=1&cell=2', ''):
            with self.subTest(body=body):
                self.assertEqual(self.request('/move', body)[0], 400)
                self.assertEqual(self.request()[2], before)

    def test_win_blocks_more_moves_then_restart_clears_board(self):
        for cell in (0,3,1,4,2):
            self.assertEqual(self.request('/move', 'cell='+str(cell))[0], 303)
        self.assertIn('Победил: X', self.request()[2])
        self.assertEqual(self.request('/move', 'cell=8')[0], 400)
        self.assertEqual(self.request('/restart', '')[0], 303)
        self.assertIn('Ход: X', self.request()[2])
        self.assertEqual(self.server.game_state['board'], [''] * 9)

    def test_unknown_routes_and_large_forms_are_rejected(self):
        self.assertEqual(self.request('/missing')[0], 404)
        self.assertEqual(self.request('/missing', '')[0], 404)
        self.assertEqual(self.request('/move', 'x' * 1025)[0], 400)
