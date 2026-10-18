"""Project model settings: progressive disclosure and non-blocking model discovery."""
from __future__ import annotations

from pathlib import Path
import queue
import threading

from . import api_connection, app, catalog, i18n, icons, keys, models_choices_configurator, openrouter, sources, workflow

tk, ttk = app.tk, app.ttk
BG, INK, MUTED, BLUE = '#f2f5fa', '#17243b', '#52627a', '#2563eb'


class DesktopConfigurator:
    """Keep Tk on its owning thread; workers only put plain results in a queue."""

    def __init__(self, window, root: Path = app.PROJECT_ROOT, *, language=None, on_prepared=None):
        self.window, self.root = window, Path(root)
        self.on_prepared = on_prepared
        self.translator = i18n.Translator(language if language is not None else i18n.load_language(self.root))
        self.tr = self.translator.tr
        self.vars = {name: tk.StringVar(value=value) for name, value in app.EMPTY_FORM.items()}
        self.typed_keys = {role: tk.StringVar() for role in workflow.ROLES}
        self.status = self.translator.var('Choose a role and connection type.')
        self.dirty = self.translator.var()
        self.results = queue.Queue()
        self.generations = dict.fromkeys(workflow.ROLES, 0)
        self.busy = dict.fromkeys(workflow.ROLES, False)
        self.widgets, self.pages, self.canvases = {}, {}, {}
        self.advanced = {role: tk.BooleanVar() for role in workflow.ROLES}
        self.revealed = {role: tk.BooleanVar() for role in workflow.ROLES}
        self.loading, self.preparing, self.closed = True, False, False
        self.visibility_jobs = {}
        self.saved = None
        self.configure_style()
        self.build()
        self.load()
        self.text_bindings = []
        self.capture_text(self.window)
        self.localize()
        self.loading = False
        for name, variable in self.vars.items():
            role = 'master_chief' if name.startswith('master_chief_') else 'bug_fixer' if name.startswith('bug_fixer_') else 'exec'
            variable.trace_add('write', lambda *args, role=role: self.changed(role))
        for role, variable in self.typed_keys.items():
            variable.trace_add('write', lambda *args, role=role: self.changed(role))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = self.window.after(70, self.poll)

    def configure_style(self):
        self.window.title('Project models — Pi Kit')
        self.window_icons = icons.application(self.window)
        self.window.configure(background=BG)
        self.window.geometry('940x820')
        self.window.minsize(760, 720)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)
        style = ttk.Style(self.window)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), foreground=INK)
        style.configure('TFrame', background=BG)
        style.configure('Card.TFrame', background='white')
        style.configure('TLabel', background=BG)
        style.configure('Card.TLabel', background='white')
        style.configure('Title.TLabel', font=('Segoe UI', 23, 'bold'))
        style.configure('Heading.TLabel', font=('Segoe UI', 14, 'bold'), background='white')
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Hint.TLabel', foreground=MUTED, background='white', font=('Segoe UI', 9))
        style.configure('TEntry', padding=7, fieldbackground='white')
        style.configure('TCombobox', padding=7, fieldbackground='white')
        style.configure('TButton', padding=(12, 8), background='#e7edf7', borderwidth=0)
        style.map('TButton', background=[('active', '#dbe5f5')])
        style.configure('Primary.TButton', background=BLUE, foreground='white')
        style.map('Primary.TButton', background=[('disabled', '#a1b7e6'), ('active', '#1d4ed8')],
                  foreground=[('disabled', '#f3f6ff')])
        style.configure('TRadiobutton', background='white', padding=(0, 5))
        style.configure('TCheckbutton', background='white', padding=0)
        style.configure('Content.TNotebook', background=BG, borderwidth=0, tabmargins=0)
        style.layout('Content.TNotebook.Tab', [])
        style.configure('Navigation.TButton', font=('Segoe UI', 10, 'bold'), padding=(12, 12),
                        background='white', foreground=INK, borderwidth=1, relief='flat', anchor='center')
        style.map('Navigation.TButton', background=[('selected', BLUE), ('active', '#e3ebfa')],
                  foreground=[('selected', 'white')], bordercolor=[('focus', '#102d65'), ('selected', BLUE)])

    def build(self):
        header = self.header = ttk.Frame(self.window, padding=(26, 20, 26, 12))
        header.grid(row=0, column=0, sticky='ew')
        header.columnconfigure(0, weight=1)
        language_bar = ttk.Frame(header)
        language_bar.grid(row=0, column=1, rowspan=2, sticky='ne', padx=(12, 0))
        ttk.Label(language_bar, text='Language').pack(side='left', padx=(0, 8))
        self.language = tk.StringVar(value='Russian' if self.translator.language == 'ru' else 'English')
        self.language_combo = ttk.Combobox(language_bar, textvariable=self.language,
                                          values=tuple(i18n.LANGUAGES), state='readonly', width=10)
        self.language_combo.pack(side='left')
        self.language_combo.bind('<<ComboboxSelected>>', self.change_language)
        ttk.Label(header, text='Project models', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        self.header_subtitle = ttk.Label(header, text='Choose who plans the work and who writes the code.', style='Muted.TLabel')
        self.header_subtitle.grid(row=1, column=0, sticky='w', pady=(4, 10))
        ttk.Label(header, textvariable=self.translator.var(i18n.text('Project: {name}', name=self.root.name)),
                  font=('Segoe UI', 10, 'bold')).grid(row=2, column=0, sticky='w')
        self.header_path = ttk.Label(header, text=str(self.root), style='Muted.TLabel', wraplength=850)
        self.header_path.grid(row=3, column=0, columnspan=2, sticky='w', pady=(2, 0))
        self.navigation = ttk.Frame(self.window)
        self.navigation.grid(row=1, column=0, sticky='ew', padx=26, pady=(0, 12))
        self.notebook = ttk.Notebook(self.window, style='Content.TNotebook')
        self.notebook.grid(row=2, column=0, sticky='nsew', padx=26)
        for role in workflow.ROLES:
            self.build_role(role)
        self.catalog = catalog.CatalogTab(self)
        self.build_navigation()
        self.window.bind('<MouseWheel>', self.scroll_mouse)
        footer = self.footer = ttk.Frame(self.window, padding=(26, 14, 26, 20))
        footer.grid(row=3, column=0, sticky='ew')
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.dirty, foreground=BLUE).grid(row=0, column=0, sticky='w', pady=(0, 6))
        actions = ttk.Frame(footer)
        actions.grid(row=1, column=0, sticky='ew')
        self.save_button = ttk.Button(actions, text='Save settings', style='Primary.TButton', command=self.on_save)
        self.save_button.pack(side='left')
        self.prepare_button = ttk.Button(actions, text='Prepare Pi', command=self.on_prepare)
        self.prepare_button.pack(side='left', padx=8)
        self.reset_button = ttk.Button(actions, text='Restore defaults', command=self.on_reset)
        self.reset_button.pack(side='right')
        ttk.Label(footer, text='Save selects models for the next kit launch. Prepare builds the configuration now.\nThe current Pi session is not switched automatically.', style='Muted.TLabel',
                  wraplength=850).grid(row=2, column=0, sticky='w', pady=(10, 7))
        self.status_label = ttk.Label(footer, textvariable=self.status, wraplength=850, justify='left')
        self.status_label.grid(row=3, column=0, sticky='ew')
        footer.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(400, event.width - 52)))
        self.notebook.bind('<<NotebookTabChanged>>', self.show_active_tab, add='+')

    def build_navigation(self):
        self.navigation_pages = dict(self.pages, catalog=self.catalog.page)
        self.navigation_buttons = {}
        self.navigation_labels = {}
        self.navigation_icons = icons.navigation(self.window)
        descriptions = {'master_chief': 'Planning & review', 'exec': 'Code implementation', 'bug_fixer': 'Corrections & recovery',
                        'catalog': 'Model catalog & prices'}
        for index, (key, page) in enumerate(self.navigation_pages.items()):
            self.navigation.columnconfigure(index, weight=1, uniform='sections')
            title = workflow.ROLE_NAMES[key] if key in workflow.ROLE_NAMES else 'OpenRouter'
            label = self.translator.var(i18n.text('{title}\n{hint}', title=i18n.text(title),
                                                hint=i18n.text(descriptions[key])))
            self.navigation_labels[key] = (label, title, descriptions[key])
            button = ttk.Button(self.navigation, textvariable=label, style='Navigation.TButton', width=1,
                                image=self.navigation_icons[key]['blue'], compound='left',
                                command=lambda page=page: self.notebook.select(page), takefocus=True)
            button.grid(row=0, column=index, sticky='ew', padx=(0 if index == 0 else 8, 0))
            button.bind('<Right>', lambda event: self.cycle_section(1))
            button.bind('<Left>', lambda event: self.cycle_section(-1))
            self.navigation_buttons[key] = button
        self.window.bind('<Control-Tab>', lambda event: self.cycle_section(1))
        self.window.bind('<Control-Shift-Tab>', lambda event: self.cycle_section(-1))
        self.navigation.bind('<Configure>', self.layout_navigation)
        self.update_navigation()

    def layout_navigation(self, event=None):
        """Keep four role/catalog buttons readable on narrow windows."""
        compact_catalog = self.notebook.select() == str(self.catalog.page) and self.navigation.winfo_width() < 820
        columns = 2 if self.navigation.winfo_width() < 820 and not compact_catalog else 4
        for label, title, hint in self.navigation_labels.values():
            if compact_catalog:
                label.set('{title}', title=i18n.text(title))
            else:
                label.set('{title}\n{hint}', title=i18n.text(title), hint=i18n.text(hint))
        for index in range(4):
            self.navigation.columnconfigure(index, weight=1 if index < columns else 0,
                                            uniform='sections' if index < columns else '')
        for index, button in enumerate(self.navigation_buttons.values()):
            button.grid(row=index // columns, column=index % columns,
                        padx=(0 if index % columns == 0 else 8, 0), pady=(0 if index < columns else 8, 0))

    def update_navigation(self):
        current = self.notebook.select()
        for key, page in self.navigation_pages.items():
            selected = current == str(page)
            self.navigation_buttons[key].state(['selected' if selected else '!selected'])
            self.navigation_buttons[key].configure(image=self.navigation_icons[key]['white' if selected else 'blue'])

    def cycle_section(self, delta):
        keys = list(self.navigation_pages)
        current = next(index for index, key in enumerate(keys)
                       if str(self.navigation_pages[key]) == self.notebook.select())
        key = keys[(current + delta) % len(keys)]
        self.notebook.select(self.navigation_pages[key])
        self.navigation_buttons[key].focus_set()
        return 'break'

    def capture_text(self, widget):
        """Remember source labels once; model IDs, input fields and live text are separate."""
        options = widget.keys()
        if 'text' in options and not ('textvariable' in options and str(widget.cget('textvariable'))):
            value = widget.cget('text')
            if value:
                self.text_bindings.append((widget, value))
        for child in widget.winfo_children():
            self.capture_text(child)

    def localize(self):
        self.window.title(self.tr('Project models — Pi Kit'))
        for widget, source in self.text_bindings:
            widget.configure(text=self.tr(source))
        for role, page in self.pages.items():
            self.notebook.tab(page, text=self.tr(workflow.ROLE_NAMES[role]))
        self.notebook.tab(self.catalog.page, text=self.tr('OpenRouter · catalog'))
        self.catalog.localize()

    def change_language(self, event=None):
        language = i18n.LANGUAGES.get(self.language.get(), 'en')
        self.translator.switch(language)
        self.localize()
        try:
            i18n.save_language(self.root, language)
        except OSError:
            self.status.set('Language changed, but the preference could not be saved.')

    def show_active_tab(self, event=None):
        self.update_navigation()
        self.layout_navigation()
        if self.notebook.select() == str(self.catalog.page):
            self.footer.grid_remove()
            self.header_subtitle.grid_remove()
            self.header_path.grid_remove()
            self.header.configure(padding=(26, 12, 26, 10))
        else:
            self.footer.grid()
            self.header_subtitle.grid()
            self.header_path.grid()
            self.header.configure(padding=(26, 20, 26, 12))

    def build_role(self, role):
        holder = ttk.Frame(self.notebook, style='Card.TFrame')
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        canvas = tk.Canvas(holder, background='white', borderwidth=0, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=scrollbar.set)
        page = ttk.Frame(canvas, padding=20, style='Card.TFrame')
        item = canvas.create_window((0, 0), window=page, anchor='nw')
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        page.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        page.columnconfigure(0, weight=1)
        self.pages[role], self.canvases[role] = holder, canvas
        self.notebook.add(holder, text=workflow.ROLE_NAMES[role])
        title = workflow.ROLE_NAMES[role]
        description = ('Plans, designs the architecture, and reviews the result.' if role == 'master_chief'
                       else 'Bounded corrections after a code error or execution limit. API failures pause work.' if role == 'bug_fixer'
                       else 'Implement independent work items from the Master Chief architecture. One model for all executor slots.')
        ttk.Label(page, text=title, style='Heading.TLabel').grid(sticky='w')
        ttk.Label(page, text=description, style='Hint.TLabel', wraplength=650).grid(sticky='w', pady=(3, 10))
        if role == 'exec':
            limits = ttk.Frame(page, style='Card.TFrame')
            limits.grid(row=5, column=0, sticky='ew', pady=(16, 0))
            for row, (label, field, high) in enumerate((('Concurrent executors', 'max_executors', 8),
                                                       ('Steps per attempt', 'max_steps', 256),
                                                       ('Seconds per attempt', 'max_seconds', 3600),
                                                       ('Repeated actions without progress', 'max_repeated_actions', 32),
                                                       ('Executor failures per work item', 'executor_max_attempts', 100),
                                                       ('Total code failures per work item', 'max_attempts', 200))):
                ttk.Label(limits, text=label, style='Card.TLabel').grid(row=row, column=0, sticky='w', padx=(0, 12))
                ttk.Spinbox(limits, from_=1, to=high, textvariable=self.vars[field], width=8).grid(row=row, column=1, pady=3)
        if role == 'bug_fixer':
            limits = ttk.Frame(page, style='Card.TFrame')
            limits.grid(row=5, column=0, sticky='ew', pady=12)
            for row, (label, field, high) in enumerate((('Steps per attempt', 'fixer_max_steps', 256),
                                                       ('Seconds per attempt', 'fixer_max_seconds', 3600),
                                                       ('Bug Fixer failures per work item', 'fixer_max_attempts', 100))):
                ttk.Label(limits, text=label, style='Card.TLabel').grid(row=row, column=0, sticky='w', padx=(0, 12))
                ttk.Spinbox(limits, from_=1, to=high, textvariable=self.vars[field], width=8).grid(row=row, column=1, pady=3)
        source_bar = ttk.Frame(page, style='Card.TFrame')
        source_bar.grid(row=2, column=0, sticky='ew', pady=(0, 8))
        first = (('default', 'Project defaults') if role == 'master_chief' else
                 ('disabled', 'Disabled') if role == 'bug_fixer' else ('lmstudio', 'Local · LM Studio'))
        for index, (value, text) in enumerate((first, ('pi', 'Model from Pi'), ('api', 'Own API'))):
            ttk.Radiobutton(source_bar, text=text, variable=self.vars[role + '_source'], value=value).grid(
                row=0, column=index, sticky='w', padx=(0, 22))
        panels = {}
        self.widgets[role] = {'panels': panels, 'fields': {}}
        for source in ('default', 'lmstudio', 'pi', 'api', 'disabled'):
            panel = ttk.Frame(page, style='Card.TFrame')
            panel.grid(row=3, column=0, sticky='nsew')
            panel.columnconfigure(0, weight=1)
            panels[source] = panel
        ttk.Label(panels['default'], text='The model from the project configuration will be used.',
                  style='Card.TLabel').grid(sticky='w', pady=(12, 7))
        ttk.Label(panels['default'], text='Choose Pi or connect your own API to use another model.',
                  style='Hint.TLabel').grid(sticky='w')
        local = panels['lmstudio']
        ttk.Label(local, text='Loaded model', style='Card.TLabel').grid(sticky='w', pady=(8, 5))
        self.widgets[role]['instance'] = ttk.Combobox(local, textvariable=self.vars['exec_instance'])
        self.widgets[role]['instance'].grid(row=1, column=0, sticky='ew')
        ttk.Button(local, text='Refresh list', command=lambda: self.fetch(role)).grid(row=1, column=1, padx=(10, 0))
        ttk.Label(local, text='Load a model in LM Studio first. Leave blank to select the only loaded model.\nThis utility does not load or unload models.', style='Hint.TLabel',
                  wraplength=650).grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))
        connected = panels['pi']
        ttk.Label(connected, text='Pi model', style='Card.TLabel').grid(sticky='w', pady=(8, 5))
        combo = ttk.Combobox(connected, textvariable=self.vars[role + '_model'])
        combo.grid(row=1, column=0, sticky='ew')
        ttk.Button(connected, text='Get models', command=lambda: self.fetch(role)).grid(row=1, column=1, padx=(10, 0))
        self.widgets[role]['pi_model'] = combo
        ttk.Label(connected, text='Connections already known to Pi. Use the full provider/model ID.\nFetch the list or enter the ID manually.', style='Hint.TLabel',
                  wraplength=650).grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))
        self.build_api(role, panels['api'])
        activity = self.translator.var()
        self.widgets[role]['activity'] = activity
        ttk.Label(page, textvariable=activity, style='Hint.TLabel', wraplength=670).grid(
            row=4, column=0, sticky='ew', pady=(12, 0))

    def build_api(self, role, panel):
        fields = self.widgets[role]['fields']
        address_header = ttk.Frame(panel, style='Card.TFrame')
        address_header.grid(sticky='ew', pady=(5, 4))
        address_header.columnconfigure(0, weight=1)
        ttk.Label(address_header, text='1. API address', style='Card.TLabel').grid(row=0, column=0, sticky='w')
        button = ttk.Button(address_header, text='Check connection', command=lambda: self.check_connection(role))
        button.grid(row=0, column=1, sticky='e')
        self.widgets[role]['connection_button'] = button
        fields['url'] = ttk.Entry(panel, textvariable=self.vars[role + '_url'])
        fields['url'].grid(sticky='ew')
        ttk.Label(panel, text='Example: https://api.example.com/v1 — without /chat/completions or /models.',
                  style='Hint.TLabel').grid(sticky='w', pady=(3, 9))
        key_title = self.translator.var('2. API key')
        self.widgets[role]['key_title'] = key_title
        ttk.Label(panel, textvariable=key_title, style='Card.TLabel').grid(sticky='w', pady=(0, 4))
        key_badge = self.translator.var()
        self.widgets[role]['key_badge'] = key_badge
        badge = ttk.Label(panel, textvariable=key_badge, style='Card.TLabel')
        badge.grid(sticky='w', pady=(0, 5))
        self.widgets[role]['key_badge_label'] = badge
        key_row = ttk.Frame(panel, style='Card.TFrame')
        key_row.grid(sticky='ew')
        key_row.columnconfigure(0, weight=1)
        fields['key'] = ttk.Entry(key_row, textvariable=self.typed_keys[role], show='•')
        fields['key'].grid(row=0, column=0, sticky='ew')
        hint = ttk.Label(key_row, text='Saved key will be used', style='Hint.TLabel')
        self.widgets[role]['key_hint'] = hint
        hint.grid(row=0, column=0, sticky='w', padx=(12, 0))
        hint.bind('<Button-1>', lambda event: (hint.grid_remove(), fields['key'].focus_set()))
        fields['key'].bind('<FocusIn>', lambda event: hint.grid_remove(), add='+')
        fields['key'].bind('<FocusOut>', lambda event, role=role: self.render(role), add='+')
        ttk.Checkbutton(key_row, text='Show', variable=self.revealed[role],
                        command=lambda: fields['key'].configure(show='' if self.revealed[role].get() else '•')).grid(
                            row=0, column=1, padx=(12, 0))
        key_status = self.translator.var()
        self.widgets[role]['key_status'] = key_status
        ttk.Label(panel, textvariable=key_status, style='Hint.TLabel', wraplength=640).grid(sticky='w', pady=(3, 9))
        connection_status = self.translator.var()
        self.widgets[role]['connection_status'] = connection_status
        ttk.Label(panel, textvariable=connection_status, style='Hint.TLabel', wraplength=640).grid(sticky='w', pady=(0, 9))
        ttk.Label(panel, text='3. Model', style='Card.TLabel').grid(sticky='w', pady=(0, 4))
        model_row = ttk.Frame(panel, style='Card.TFrame')
        model_row.grid(sticky='ew')
        model_row.columnconfigure(0, weight=1)
        fields['model'] = ttk.Combobox(model_row, textvariable=self.vars[role + '_model'])
        fields['model'].grid(row=0, column=0, sticky='ew')
        models_button = ttk.Button(model_row, text='Get models', command=lambda: self.fetch(role))
        models_button.grid(row=0, column=1, padx=(10, 0))
        self.widgets[role]['models_button'] = models_button
        ttk.Label(panel, text='Select a model or enter its exact ID at your service.',
                  style='Hint.TLabel').grid(sticky='w', pady=(3, 9))
        ttk.Checkbutton(panel, text='Advanced', variable=self.advanced[role],
                        command=lambda: self.toggle_advanced(role)).grid(sticky='w', pady=(0, 4))
        advanced = ttk.Frame(panel, style='Card.TFrame')
        advanced.grid(sticky='ew')
        advanced.columnconfigure(1, weight=1)
        ttk.Label(advanced, text='Key variable', style='Card.TLabel').grid(row=0, column=0, padx=(0, 12))
        fields['key_env'] = ttk.Entry(advanced, textvariable=self.vars[role + '_key_env'])
        fields['key_env'].grid(row=0, column=1, sticky='ew')
        self.widgets[role]['advanced'] = advanced
        advanced.grid_remove()
        for widget in fields.values():
            widget.bind('<FocusIn>', lambda event, role=role: self.ensure_visible(role, event.widget), add='+')

    def scroll_mouse(self, event):
        role = next((role for role, page in self.pages.items() if str(page) == self.notebook.select()), None)
        if role is None or event.widget.winfo_class() == 'TCombobox':
            return
        if str(event.widget).startswith(str(self.pages[role]) + '.'):
            canvas = self.canvases[role]
            if canvas.yview() != (0.0, 1.0):
                canvas.yview_scroll(-int(event.delta / 120), 'units')
                return 'break'

    def ensure_visible(self, role, widget):
        self.window.update_idletasks()
        canvas = self.canvases[role]
        top = canvas.canvasy(0)
        y, node = 0, widget
        while node.master is not canvas:
            y += node.winfo_y()
            node = node.master
        bottom = y + widget.winfo_height()
        height = canvas.winfo_height()
        region = canvas.bbox('all')
        if region and region[3] > height:
            if y < top:
                canvas.yview_moveto(max(0, y - 8) / region[3])
            elif bottom > top + height:
                canvas.yview_moveto((bottom - height + 8) / region[3])

    def form(self):
        return {name: variable.get().strip() for name, variable in self.vars.items()}

    def snapshot(self):
        return self.form(), {role: variable.get() for role, variable in self.typed_keys.items()}

    def load(self):
        try:
            data = models_choices_configurator.load_choices(self.root)
            from ..pi_configuration import load_project_defaults
            defaults = load_project_defaults(self.root)
            data = {**defaults, **data}
            form = app.choices_to_form(data)
            for section in ('masterChief', 'executors', 'bugFixer'):
                if section in data:
                    allowed = ('pi', 'api') if section == 'masterChief' else ('lmstudio', 'pi', 'api')
                    if not isinstance(data[section], dict) or data[section].get('source') not in allowed:
                        raise ValueError('Invalid choice source')
            for name, value in form.items():
                self.vars[name].set(value)
            self.status.set('Saved selection loaded.' if data else 'Showing the defaults.')
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            self.status.set('Could not read the saved selection. The file was not changed. Check the settings before saving.')
        self.saved = self.snapshot()
        for role in workflow.ROLES:
            self.render(role)

    def changed(self, role):
        if self.loading:
            return
        self.generations[role] += 1
        self.widgets[role]['connection_status'].set('')
        if not self.busy[role]:
            self.widgets[role]['activity'].set('')
        self.widgets[role]['fields']['model']['values'] = ()
        self.widgets[role]['pi_model']['values'] = ()
        self.render(role)
        for other in workflow.ROLES:
            if (other != role and self.vars[other + '_source'].get() == 'api'
                    and self.vars[role + '_key_env'].get() == self.vars[other + '_key_env'].get()):
                self.generations[other] += 1
                self.widgets[other]['connection_status'].set('')
                self.widgets[other]['fields']['model']['values'] = ()
                self.render(other)
        self.dirty.set('Unsaved changes' if self.snapshot() != self.saved else '')

    def shared_key_role(self, role):
        """Find an entered key for the same API variable across all three roles."""
        matches = [other for other in workflow.ROLES if other != role
                   and self.vars[other + '_source'].get() == 'api'
                   and self.vars[other + '_key_env'].get() == self.vars[role + '_key_env'].get()]
        return next((other for other in matches if self.typed_keys[other].get().strip()),
                    matches[0] if matches else 'exec' if role == 'master_chief' else 'master_chief')

    def render(self, role):
        source = self.vars[role + '_source'].get()
        for name, panel in self.widgets[role]['panels'].items():
            panel.grid() if name == source else panel.grid_remove()
        typed = self.typed_keys[role].get().strip()
        present = workflow.existing_key(self.vars[role + '_key_env'].get().strip())
        self.widgets[role]['key_title'].set('2. Replace API key (optional)' if present and not typed else '2. API key')
        self.widgets[role]['key_badge'].set('New key entered' if typed else '✓ Key found' if present else 'No saved key found')
        self.widgets[role]['key_badge_label'].configure(foreground='#187047' if present and not typed else MUTED)
        hint = self.widgets[role]['key_hint']
        if present and not typed and self.window.focus_get() is not self.widgets[role]['fields']['key']:
            hint.grid()
        else:
            hint.grid_remove()
        note = ('New key entered; it will be saved with the settings.' if typed else
                'A key is already saved on this computer. Leave blank to keep it.' if present else
                'Paste your service key. The key itself is not written to the project file.')
        self.widgets[role]['key_status'].set(note)
        if present and not typed:
            self.widgets[role]['key_status'].set('Available from {name}. No need to enter it again. Enter a new key only to replace it.',
                                                name=self.vars[role + '_key_env'].get().strip())
        other = self.shared_key_role(role)
        if (not typed and not present and source == 'api' and self.vars[other + '_source'].get() == 'api'
                and self.vars[role + '_key_env'].get() == self.vars[other + '_key_env'].get()
                and self.typed_keys[other].get().strip()):
            self.widgets[role]['key_status'].set('A shared key has already been entered for the other role and will be used here too.')
            self.widgets[role]['key_badge'].set('Shared key entered for the other role')

    def choose_openrouter(self, model_id, role):
        """Fill one role's draft only; never send or persist a key on a catalog click."""
        if role not in workflow.ROLES or model_id not in self.catalog.by_id:
            return
        same_service = openrouter.is_openrouter(self.vars[role + '_url'].get())
        self.loading = True
        self.vars[role + '_source'].set('api')
        self.vars[role + '_url'].set(openrouter.API_URL)
        self.vars[role + '_model'].set(model_id)
        if not same_service:
            self.typed_keys[role].set('')
            self.vars[role + '_key_env'].set(openrouter.KEY_ENV)
        self.loading = False
        self.changed(role)
        self.status_label.configure(foreground=INK)
        self.status.set('{role}: selected {model}. The OpenRouter address is filled in; check the API key and save settings.',
                        role=i18n.text(workflow.ROLE_NAMES[role]), model=model_id)

    def toggle_advanced(self, role):
        panel = self.widgets[role]['advanced']
        panel.grid() if self.advanced[role].get() else panel.grid_remove()
        if role in self.visibility_jobs:
            self.window.after_cancel(self.visibility_jobs.pop(role))
        if self.advanced[role].get():
            def reveal():
                self.visibility_jobs.pop(role, None)
                self.ensure_visible(role, self.widgets[role]['fields']['key_env'])
            self.visibility_jobs[role] = self.window.after(30, reveal)

    def show_error(self, error):
        self.status_label.configure(foreground='#b42338')
        if isinstance(error, workflow.FormError):
            self.notebook.select(self.pages[error.role])
            if error.field == 'key_env':
                self.advanced[error.role].set(True)
                self.toggle_advanced(error.role)
            widget = self.widgets[error.role]['fields'].get(error.field)
            if error.field == 'model' and self.vars[error.role + '_source'].get() == 'pi':
                widget = self.widgets[error.role]['pi_model']
            if widget:
                widget.focus_set()
            self.status.set('{role}: {message}', role=i18n.text(workflow.ROLE_NAMES[error.role]),
                            message=i18n.text(str(error)))
        else:
            self.status.set('Could not save settings. Check access to the project folder and Windows user variables. Keys are not printed in the log.')

    def fetch(self, role):
        if self.busy[role]:
            return
        form = self.form()
        source = form[role + '_source']
        try:
            if source == 'api':
                typed = self.typed_keys[role].get()
                other = self.shared_key_role(role)
                if (not typed.strip() and form[other + '_source'] == 'api'
                        and form[role + '_key_env'] == form[other + '_key_env']):
                    typed = self.typed_keys[other].get()
                arguments = workflow.connection(form, role, typed)
                fetcher = sources.api_models
            elif source == 'pi':
                arguments, fetcher = (self.root,), sources.pi_models
            elif source == 'lmstudio':
                arguments, fetcher = (), sources.lmstudio_instances
            else:
                return
        except workflow.FormError as error:
            self.show_error(error)
            return
        generation = self.generations[role]
        self.set_request_busy(role, True)
        self.widgets[role]['activity'].set('Fetching models… You can keep using this window.')
        self.status_label.configure(foreground=INK)
        self.status.set('{role}: {message}', role=i18n.text(workflow.ROLE_NAMES[role]),
                        message=i18n.text('Fetching models…'))

        def work():
            try:
                result, failed = fetcher(*arguments), ''
            except Exception as error:
                result, failed = [], workflow.model_error(source, error)
            self.results.put(('models', role, generation, source, result, failed))

        threading.Thread(target=work, daemon=True).start()

    def set_request_busy(self, role, busy):
        self.busy[role] = busy
        for name in ('connection_button', 'models_button'):
            self.widgets[role][name].state(['disabled'] if busy else ['!disabled'])

    def check_connection(self, role):
        if self.busy[role] or self.vars[role + '_source'].get() != 'api':
            return
        form = self.form()
        typed = self.typed_keys[role].get()
        other = self.shared_key_role(role)
        if (not typed.strip() and form[other + '_source'] == 'api'
                and form[role + '_key_env'] == form[other + '_key_env']):
            typed = self.typed_keys[other].get()
        try:
            arguments = workflow.connection(form, role, typed)
        except workflow.FormError as error:
            self.widgets[role]['connection_status'].set(i18n.text(str(error)))
            self.show_error(error)
            return
        generation = self.generations[role]
        self.set_request_busy(role, True)
        self.render(role)
        self.widgets[role]['connection_status'].set('Checking connection… No generation requests are sent.')
        self.status_label.configure(foreground=INK)
        self.status.set('{role}: {message}', role=i18n.text(workflow.ROLE_NAMES[role]),
                        message=i18n.text('Checking connection… No generation requests are sent.'))

        def work():
            try:
                result, failed = api_connection.check(*arguments), ''
            except Exception as error:
                result, failed = {}, api_connection.error_message(error)
            self.results.put(('connection', role, generation, result, failed))

        threading.Thread(target=work, daemon=True).start()

    def receive_connection(self, role, generation, result, failed):
        self.set_request_busy(role, False)
        activity = self.widgets[role]['connection_status']
        if generation != self.generations[role]:
            activity.set('Settings changed during the check. Check connection again.')
        elif failed:
            activity.set(failed)
        elif result.get('authenticated') is True:
            activity.set('Connected. OpenRouter accepted the key. Model generation and tools were not tested.')
        else:
            activity.set('API reachable: {count} models listed. This endpoint may be public; key acceptance and generation are not confirmed.',
                         count=result.get('models', 0))
        self.status_label.configure(foreground='#b42338' if failed else INK)
        self.status.set('{role}: {message}', role=i18n.text(workflow.ROLE_NAMES[role]), message=activity.message)

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                result = self.results.get_nowait()
                if result[0] == 'models':
                    self.receive_models(*result[1:])
                elif result[0] == 'connection':
                    self.receive_connection(*result[1:])
                elif result[0] == 'catalog':
                    self.catalog.receive(*result[1:])
                else:
                    self.receive_preparation(*result[1:])
        except queue.Empty:
            pass
        self.poll_id = self.window.after(70, self.poll)

    def receive_models(self, role, generation, source, models, failed):
        self.set_request_busy(role, False)
        activity = self.widgets[role]['activity']
        if generation != self.generations[role]:
            activity.set('Settings changed during the request. Fetch the list again.')
            self.status.set('{role}: {message}', role=i18n.text(workflow.ROLE_NAMES[role]), message=activity.message)
            return
        if failed:
            activity.set(failed)
            self.status_label.configure(foreground='#b42338')
            self.status.set('{role}: {message}', role=i18n.text(workflow.ROLE_NAMES[role]), message=i18n.text(failed))
            return
        if source == 'lmstudio':
            self.widgets[role]['instance']['values'] = [pair[0] for pair in models]
            if models:
                activity.set('Loaded: {names}', names=', '.join(pair[1] for pair in models))
            else:
                activity.set('No models are loaded. Load a model in LM Studio and refresh the list.')
        else:
            combo = self.widgets[role]['fields']['model'] if source == 'api' else self.widgets[role]['pi_model']
            combo['values'] = models
            if models:
                activity.set('Found {count} models. Choose one from the list.', count=len(models))
            else:
                activity.set('The service returned an empty list. You can enter the model ID manually.')
            if source == 'api':
                activity.set([activity.message, i18n.text('\nOnly /models was checked; generation and tools were not tested.')])
        self.status_label.configure(foreground=INK)
        self.status.set('{role}: {message}', role=i18n.text(workflow.ROLE_NAMES[role]), message=activity.message)

    def on_save(self):
        if self.preparing:
            return False
        try:
            path, choices = workflow.save(self.root, *self.snapshot())
        except (ValueError, OSError, AttributeError) as error:
            self.show_error(error)
            return False
        self.loading = True
        for role in workflow.ROLES:
            if self.vars[role + '_source'].get() == 'api':
                self.typed_keys[role].set('')
                self.revealed[role].set(False)
                self.widgets[role]['fields']['key'].configure(show='•')
        self.loading = False
        self.saved = self.snapshot()
        self.dirty.set('')
        for role in workflow.ROLES:
            self.render(role)
        self.status_label.configure(foreground='#187047')
        self.status.set('Settings saved. The next kit launch will use this selection.')
        self.saved_choices = choices
        return True

    def on_prepare(self):
        if not self.on_save():
            return
        self.preparing = True
        for button in (self.save_button, self.prepare_button, self.reset_button):
            button.state(['disabled'])
        self.status_label.configure(foreground=INK)
        self.status.set('Preparing Pi settings… The current session is not being restarted.')
        choices = self.saved_choices

        def work():
            try:
                code, output = workflow.prepare(self.root, choices)
                successful = code == 0
            except Exception:
                successful = False
            self.results.put(('prepare', successful))

        threading.Thread(target=work, daemon=True).start()

    def receive_preparation(self, successful):
        self.preparing = False
        for button in (self.save_button, self.prepare_button, self.reset_button):
            button.state(['!disabled'])
        self.status_label.configure(foreground='#187047' if successful else '#b42338')
        self.status.set('Settings prepared. Resume a paused task to use this selection; new sessions will use it too.' if successful else
                        'Selection saved, but preparation failed. Check Pi, API keys, or the loaded LM Studio model. The current session was not changed.')
        if successful and self.on_prepared:
            self.on_prepared()

    def on_reset(self):
        if self.preparing:
            return
        try:
            models_choices_configurator.reset_choices(self.root)
        except OSError as error:
            self.show_error(error)
            return
        self.loading = True
        for name, value in app.EMPTY_FORM.items():
            self.vars[name].set(value)
        for role in workflow.ROLES:
            self.generations[role] += 1
            self.typed_keys[role].set('')
            self.revealed[role].set(False)
            self.widgets[role]['fields']['key'].configure(show='•')
            self.advanced[role].set(False)
            self.toggle_advanced(role)
            self.widgets[role]['activity'].set('')
            self.render(role)
        self.loading = False
        self.saved = self.snapshot()
        self.dirty.set('')
        self.status_label.configure(foreground=INK)
        self.load()
        self.status.set('Project defaults restored. Saved Windows keys were kept.')

    def close(self):
        self.closed = True
        self.window.after_cancel(self.poll_id)
        for job in self.visibility_jobs.values():
            self.window.after_cancel(job)
        self.window.update_idletasks()
        self.window.destroy()


def main() -> int:
    if tk is None:
        print('Python with tkinter is required for this window.')
        return 1
    window = tk.Tk()
    DesktopConfigurator(window)
    window.mainloop()
    return 0
