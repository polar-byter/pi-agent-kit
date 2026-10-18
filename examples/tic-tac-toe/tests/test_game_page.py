import copy
from html.parser import HTMLParser
import unittest
from game_page import render_game_page


class PageElements(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class GamePageTests(unittest.TestCase):
    def state(self, **changes):
        return dict(board=[''] * 9, current_player='X', winner=None, is_draw=False, **changes)

    def cells(self, text):
        return [attrs for tag, attrs in PageElements(text).elements if tag == 'button' and attrs.get('name') == 'cell']

    def test_nine_accessible_cells_and_forms(self):
        page = render_game_page(self.state())
        elements = PageElements(page).elements
        cells = self.cells(page)
        self.assertEqual(len(cells), 9)
        self.assertEqual({cell['value'] for cell in cells}, {str(i) for i in range(9)})
        self.assertTrue(all(cell.get('aria-label') for cell in cells))
        forms = [attrs for tag, attrs in elements if tag == 'form']
        self.assertTrue(any(form.get('method','').lower() == 'post' and form.get('action') == '/move' for form in forms))
        self.assertTrue(any(form.get('method','').lower() == 'post' and form.get('action') == '/restart' for form in forms))

    def test_status_for_both_players(self):
        for player in ('X','O'):
            state = self.state()
            state['current_player'] = player
            self.assertIn('Ход: ' + player, render_game_page(state))

    def test_taken_and_finished_cells_are_disabled(self):
        state = self.state()
        state['board'][0] = 'X'
        self.assertIn('disabled', self.cells(render_game_page(state))[0])
        self.assertNotIn('disabled', self.cells(render_game_page(state))[1])
        for outcome in ('X','O','draw'):
            terminal = self.state()
            terminal['winner'] = outcome if outcome != 'draw' else None
            terminal['is_draw'] = outcome == 'draw'
            page = render_game_page(terminal)
            self.assertTrue(all('disabled' in cell for cell in self.cells(page)))
            self.assertIn('Ничья' if outcome == 'draw' else 'Победил: ' + outcome, page)

    def test_render_preserves_state_and_escapes_values(self):
        state = self.state()
        state['current_player'] = '<script>alert(1)</script>'
        state['board'][0] = '<img src=x onerror=alert(1)>'
        before = copy.deepcopy(state)
        page = render_game_page(state)
        self.assertEqual(state, before)
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertNotIn('<img src=x', page)

    def test_page_is_local_responsive_and_keyboard_accessible(self):
        page = render_game_page(self.state())
        self.assertIn('lang="ru"', page)
        self.assertIn('viewport', page)
        self.assertIn('grid-template-columns', page)
        self.assertIn(':focus', page)
        self.assertNotIn('https://', page)
        self.assertNotIn('<script src=', page)


    def test_only_the_render_body_changes(self):
        import ast
        from pathlib import Path
        import game_page
        tree = ast.parse(Path(game_page.__file__).read_text(encoding='utf-8'))
        definitions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        self.assertEqual(definitions, ['render_game_page'])
        self.assertFalse(any(isinstance(node, (ast.Assign, ast.AnnAssign)) for node in tree.body))
