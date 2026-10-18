import copy
import unittest
from game_rules import create_initial_game_state, apply_player_move


class GameRulesTests(unittest.TestCase):
    def play(self, moves):
        state = create_initial_game_state()
        for cell in moves:
            state = apply_player_move(state, cell)
        return state

    def test_initial_states_are_independent(self):
        first, second = create_initial_game_state(), create_initial_game_state()
        self.assertEqual(first, dict(board=[''] * 9, current_player='X', winner=None, is_draw=False))
        first['board'][0] = 'X'
        self.assertEqual(second['board'][0], '')

    def test_move_copies_board_and_alternates(self):
        before = create_initial_game_state()
        snapshot = copy.deepcopy(before)
        after = apply_player_move(before, 4)
        self.assertEqual(before, snapshot)
        self.assertIsNot(after['board'], before['board'])
        self.assertEqual(after['board'][4], 'X')
        self.assertEqual(after['current_player'], 'O')

    def test_invalid_indices_preserve_state(self):
        state = create_initial_game_state()
        for cell in (-1, 9, True, False, '1', 1.5, None):
            with self.subTest(cell=cell):
                snapshot = copy.deepcopy(state)
                with self.assertRaises(ValueError):
                    apply_player_move(state, cell)
                self.assertEqual(state, snapshot)

    def test_occupied_cell_preserves_state(self):
        state = self.play([4])
        snapshot = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            apply_player_move(state, 4)
        self.assertEqual(state, snapshot)

    def test_all_eight_winning_lines(self):
        lines = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]
        for line in lines:
            with self.subTest(line=line):
                board = [''] * 9
                board[line[0]] = board[line[1]] = 'X'
                state = dict(board=board, current_player='X', winner=None, is_draw=False)
                result = apply_player_move(state, line[2])
                self.assertEqual(result['winner'], 'X')
                self.assertEqual(result['current_player'], 'X')
                self.assertFalse(result['is_draw'])

    def test_o_can_win(self):
        self.assertEqual(self.play([0,3,1,4,8,5])['winner'], 'O')

    def test_full_board_draw(self):
        result = self.play([0,1,2,4,3,5,7,6,8])
        self.assertTrue(result['is_draw'])
        self.assertIsNone(result['winner'])

    def test_last_cell_win_takes_precedence(self):
        result = self.play([0,1,2,3,4,5,7,6,8])
        self.assertEqual(result['winner'], 'X')
        self.assertFalse(result['is_draw'])

    def test_no_moves_after_win_or_draw(self):
        for state in (self.play([0,3,1,4,2]), self.play([0,1,2,4,3,5,7,6,8])):
            snapshot = copy.deepcopy(state)
            with self.assertRaises(ValueError):
                apply_player_move(state, 8)
            self.assertEqual(state, snapshot)


    def test_only_the_planned_function_bodies_are_implemented(self):
        import game_rules
        declared_functions = sorted(name for name, value in vars(game_rules).items()
                                    if callable(value) and getattr(value, '__module__', None) == 'game_rules')
        self.assertEqual(declared_functions, ['apply_player_move', 'create_initial_game_state'])
