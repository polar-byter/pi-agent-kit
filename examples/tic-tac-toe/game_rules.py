"""Immutable rules for a local two-player game."""

def create_initial_game_state():
    """Return a fresh empty board with X to move and no terminal outcome.

    The returned dictionary and its board list are newly allocated on every
    call, so callers can keep two games side by side without sharing cells.
    """
    return {
        'board': ['' for _ in range(9)],
        'current_player': 'X',
        'winner': None,
        'is_draw': False,
    }


def apply_player_move(game_state, cell_index):
    """Validate a move before changing a copy, then detect all terminal outcomes.

    Reject bool and non-int indices, values outside 0..8, occupied cells and
    finished games with ValueError. Preserve every input value after success
    or failure. Prefer a winning line over a draw on the final free cell.
    """
    if isinstance(cell_index, bool) or not isinstance(cell_index, int):
        raise ValueError('Cell index must be an integer between 0 and 8')
    if cell_index < 0 or cell_index > 8:
        raise ValueError('Cell index must be an integer between 0 and 8')

    if game_state['winner'] is not None or game_state['is_draw']:
        raise ValueError('Cannot move in a finished game')
    if game_state['board'][cell_index] != '':
        raise ValueError('Cannot move into an occupied cell')

    # Copy only after validation so a rejected move never touches the input.
    updated_board = list(game_state['board'])
    updated_board[cell_index] = game_state['current_player']
    moved_player = game_state['current_player']

    # The eight lines are the three rows, three columns and two diagonals.
    winning_lines = (
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
        (0, 4, 8), (2, 4, 6),
    )
    has_winning_line = any(
        updated_board[first] == moved_player
        and updated_board[second] == moved_player
        and updated_board[third] == moved_player
        for first, second, third in winning_lines
    )

    if has_winning_line:
        return {
            'board': updated_board,
            'current_player': moved_player,
            'winner': moved_player,
            'is_draw': False,
        }

    if all(cell != '' for cell in updated_board):
        return {
            'board': updated_board,
            'current_player': moved_player,
            'winner': None,
            'is_draw': True,
        }

    return {
        'board': updated_board,
        'current_player': 'O' if moved_player == 'X' else 'X',
        'winner': None,
        'is_draw': False,
    }
