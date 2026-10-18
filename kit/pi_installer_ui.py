"""Create a project, prepare Pi on the template disk, then open its configurator."""
from pathlib import Path
import queue
import threading

from . import localization, pi_installation
from .configurator import app, icons
from .configurator.desktop import DesktopConfigurator

tk, ttk = app.tk, app.ttk
SOURCE = Path(__file__).resolve().parents[1]


class PiInstallerWindow:
    """Keep installation work outside Tk's event loop and show its actual result."""

    def __init__(self, window, source=SOURCE):
        self.window = window
        self.source = Path(source)
        self.language = tk.StringVar(value=localization.system_language())
        self.project_directory = tk.StringVar(value=str(self.source.parent / 'my-pi-project'))
        self.status = tk.StringVar()
        self.results = queue.Queue()
        self.configuration_windows = []
        self.running = False
        self.window.title('Pi Agent Kit')
        self.window.geometry('820x390')
        self.window.minsize(650, 370)
        self.window_icons = icons.application(self.window)
        frame = ttk.Frame(window, padding=24)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        self.heading = ttk.Label(frame, font=('Segoe UI', 20, 'bold'))
        self.heading.grid(row=0, column=0, sticky='w')
        language_choice = ttk.Combobox(frame, textvariable=self.language, values=('ru', 'en'), state='readonly', width=5)
        language_choice.grid(row=0, column=1, padx=(12, 0))
        language_choice.bind('<<ComboboxSelected>>', lambda event: self.localize())
        self.explanation = ttk.Label(frame, wraplength=730, justify='left')
        self.explanation.grid(row=1, column=0, columnspan=2, sticky='w', pady=(15, 16))
        ttk.Entry(frame, textvariable=self.project_directory).grid(row=2, column=0, sticky='ew', ipady=6)
        self.browse_button = ttk.Button(frame, command=self.choose_project_directory)
        self.browse_button.grid(row=2, column=1, padx=(12, 0))
        self.create_button = ttk.Button(frame, command=self.install_and_configure)
        self.create_button.grid(row=3, column=0, columnspan=2, sticky='ew', pady=18)
        ttk.Label(frame, textvariable=self.status, wraplength=730).grid(row=4, column=0, columnspan=2, sticky='w')
        self.localize()
        self.poll_identifier = self.window.after(100, self.receive_installation_result)
        self.window.protocol('WM_DELETE_WINDOW', self.close)

    def text(self, english, russian):
        return russian if self.language.get() == 'ru' else english

    def localize(self):
        self.heading.configure(text=self.text('Create a Pi project', 'Создать проект с Pi'))
        self.explanation.configure(text=self.text(
            'Choose a separate project folder. Setup installs Pi beside this template, copies the kit and opens the model configurator. Keys and model caches are not copied. Then use start.cmd or start.sh in your project.',
            'Выберите отдельную папку проекта. Установка разместит Pi рядом с этим шаблоном, скопирует кит и откроет конфигуратор моделей. Ключи и кеши моделей не копируются. Затем запускайте start.cmd или start.sh из проекта.'))
        self.browse_button.configure(text=self.text('Choose folder', 'Выбрать папку'))
        self.create_button.configure(text=self.text('Install and configure models', 'Установить и настроить модели'))

    def choose_project_directory(self):
        from tkinter import filedialog
        selected = filedialog.askdirectory(parent=self.window, mustexist=False)
        if selected:
            self.project_directory.set(selected)

    def install_and_configure(self):
        if self.running:
            return
        destination = self.project_directory.get()
        try:
            pi_installation.project_path(destination, self.source)
        except ValueError as error:
            self.status.set(str(error))
            return
        self.running = True
        self.create_button.state(['disabled'])
        self.status.set(self.text('Preparing Pi and project files…', 'Подготавливаем Pi и файлы проекта…'))
        def perform_installation():
            try:
                pi_installation.install_pi_runtime(self.source)
                result = pi_installation.install_project(self.source, destination)
                self.results.put((result, None))
            except Exception as error:
                self.results.put((None, str(error)))
        threading.Thread(target=perform_installation, daemon=True).start()

    def receive_installation_result(self):
        try:
            result, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.running = False
            self.create_button.state(['!disabled'])
            if error:
                self.status.set(error)
            else:
                self.status.set(self.text('Project ready. Select models and click Prepare Pi.', 'Проект готов. Выберите модели и нажмите «Подготовить Pi».'))
                configuration_window = tk.Toplevel(self.window)
                configuration = DesktopConfigurator(configuration_window, Path(result['project']), language=self.language.get())
                self.configuration_windows.append(configuration)
        self.poll_identifier = self.window.after(100, self.receive_installation_result)

    def close(self):
        if self.running:
            self.status.set(self.text('Wait until installation finishes.', 'Дождитесь завершения установки.'))
            return
        self.window.after_cancel(self.poll_identifier)
        self.window.destroy()


def main():
    if tk is None:
        print('The graphical installer requires the kit Python runtime with Tk.')
        return 1
    window = tk.Tk()
    PiInstallerWindow(window)
    window.mainloop()
    return 0
