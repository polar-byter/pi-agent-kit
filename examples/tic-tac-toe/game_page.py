"""Render accessible game controls using ordinary HTML forms."""
from html import escape


def render_game_page(game_state):
    """Render the full responsive page without mutating the supplied state.

    Follow CONTRACTS.md for forms, labels, disabling and Russian status text.
    Escape visible state values, include a viewport and clear focus styles.
    Keep every asset inline so the page works without external services.
    """
    page_style = """
    :root { color-scheme: light; }
    body { font-family: system-ui, sans-serif; margin: 0; padding: 1rem; background: #f5f6f8; color: #1b1b1b; }
    main { max-width: 28rem; margin: 0 auto; }
    h1 { font-size: 1.4rem; margin-bottom: 0.5rem; }
    .status { font-size: 1.1rem; margin: 0.5rem 0 1rem; }
    .board { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; margin-bottom: 1rem; }
    .cell { min-height: 4rem; font-size: 1.6rem; font-weight: 600; cursor: pointer; border: 2px solid #4a4a4a; border-radius: 6px; background: #ffffff; color: #1b1b1b; }
    .cell:disabled { cursor: not-allowed; background: #e3e4e7; color: #5a5a5a; }
    .restart { padding: 0.6rem 1.2rem; border: 2px solid #4a4a4a; border-radius: 6px; background: #ffffff; color: #1b1b1b; font-size: 1rem; cursor: pointer; }
    *:focus { outline: 3px solid #1a56db; outline-offset: 2px; }
    @media (max-width: 24rem) { .cell { min-height: 3rem; font-size: 1.3rem; } }
""".strip()

    cell_coordinates = ('строка 1, столбец 1', 'строка 1, столбец 2', 'строка 1, столбец 3',
                        'строка 2, столбец 1', 'строка 2, столбец 2', 'строка 2, столбец 3',
                        'строка 3, столбец 1', 'строка 3, столбец 2', 'строка 3, столбец 3')

    def build_status_text(game_state):
        """Return the Russian status line for the supplied game state."""
        winner = game_state['winner']
        if winner is not None:
            return 'Победил: ' + str(winner)
        if game_state['is_draw']:
            return 'Ничья'
        return 'Ход: ' + str(game_state['current_player'])

    def build_cell_button(cell_index, cell_value, game_finished):
        """Return one labelled submit button for a single board cell."""
        escaped_value = escape(str(cell_value))
        coordinate = cell_coordinates[cell_index]
        label = coordinate if escaped_value in ('', ' ') else coordinate + ': ' + escaped_value
        disabled = cell_value != '' or game_finished
        attributes = ['type="submit"', 'name="cell"', 'value="{index}"'.format(index=cell_index),
                      'class="cell"', 'aria-label="{label}"'.format(label=escape(label, quote=True))]
        if disabled:
            attributes.append('disabled')
        display = escaped_value if escaped_value not in ('', ' ') else '&nbsp;'
        return '<button {attrs}>{display}</button>'.format(attrs=' '.join(attributes), display=display)

    board = list(game_state['board'])
    game_finished = bool(game_state['winner']) or bool(game_state['is_draw'])
    status_text = build_status_text(game_state)
    cell_buttons = '\n        '.join(
        build_cell_button(cell_index, board[cell_index], game_finished)
        for cell_index in range(9)
    )
    return (
        '<!DOCTYPE html>\n'
        '<html lang="ru">\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '  <title>Крестики-нолики</title>\n'
        '  <style>\n{style}\n  </style>\n'
        '</head>\n'
        '<body>\n'
        '  <main>\n'
        '    <h1>Крестики-нолики</h1>\n'
        '    <p class="status" role="status">{status}</p>\n'
        '    <form method="post" action="/move">\n'
        '      <div class="board">\n'
        '        {cells}\n'
        '      </div>\n'
        '    </form>\n'
        '    <form method="post" action="/restart">\n'
        '      <button class="restart" type="submit">Начать заново</button>\n'
        '    </form>\n'
        '  </main>\n'
        '</body>\n'
        '</html>\n'
    ).format(style=page_style, status=escape(status_text, quote=True), cells=cell_buttons)
