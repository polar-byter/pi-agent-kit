"""English source messages and saved UI language with an OS-language fallback."""
from dataclasses import dataclass, field

from . import app
from ..localization import PREFERENCES, load_language, save_language

LANGUAGES = {'English': 'en', 'Russian': 'ru'}

RU = {
    'Bounded corrections after a code error or execution limit. API failures pause work.': 'Исправляет код в пределах своего запаса попыток. При сбое API работа приостанавливается.',
    'Executor failures per work item': 'Неудачных попыток исполнителя на модуль',
    'Bug Fixer failures per work item': 'Неудачных попыток Bug Fixer на модуль',
    'Total code failures per work item': 'Общий предел ошибок кода на модуль',
    'Settings prepared. Resume a paused task to use this selection; new sessions will use it too.': 'Настройки подготовлены. Продолжите приостановленную задачу — она использует новый выбор; новые сессии тоже.',
    'Bug Fixer': 'Исправитель ошибок',
    'Implement independent work items from the Master Chief architecture. One model for all executor slots.': 'Выполняют независимые поручения по архитектуре Чифа. Одна модель для всех исполнителей.',
    'Project defaults restored. Saved Windows keys were kept.': 'Восстановлены настройки проекта. Сохранённые ключи Windows оставлены.',
    'Corrections & recovery': 'Исправление ошибок',
    'Disabled': 'Выключен',
    'Concurrent executors': 'Одновременных исполнителей',
    'Steps per attempt': 'Шагов на попытку',
    'Seconds per attempt': 'Секунд на попытку',
    'Repeated actions without progress': 'Повторов без прогресса',
    'Enter valid whole-number limits: workers 1–8, steps 1–256, seconds 1–3600, repeats 2–32, role failures 1–100, total failures 1–200.': 'Введите целые числа: исполнителей 1–8, шагов 1–256, секунд 1–3600, повторов 2–32, ошибок роли 1–100, общий предел 1–200.',
    'One correction attempt after a code error or execution limit. Never used for API failures.': 'Одна попытка исправления после ошибки кода или лимита выполнения. Ошибки API не запускают исправителя.',
    '2. Replace API key (optional)': '2. Заменить API-ключ (необязательно)',
    'New key entered': 'Введён новый ключ',
    '✓ Key found': '✓ Ключ найден',
    'No saved key found': 'Сохранённого ключа нет',
    'Shared key entered for the other role': 'Общий ключ введён для другой роли',
    'Saved key will be used': 'Будет использован сохранённый ключ',
    'Available from {name}. No need to enter it again. Enter a new key only to replace it.': 'Доступен из {name}. Повторно вводить не нужно. Введите новый ключ только для замены.',
    'Check connection': 'Проверить связь',
    'Checking connection… No generation requests are sent.': 'Проверяем связь… Запросы генерации не отправляются.',
    'Settings changed during the check. Check connection again.': 'Настройки изменились во время проверки. Проверьте связь ещё раз.',
    'Connected. OpenRouter accepted the key. Model generation and tools were not tested.': 'Связь установлена. OpenRouter принял ключ. Генерация модели и инструменты не проверялись.',
    'API reachable: {count} models listed. This endpoint may be public; key acceptance and generation are not confirmed.': 'API доступен, моделей в списке: {count}. Этот адрес может быть публичным; принятие ключа и генерация не подтверждены.',
    'Connection check endpoint not found. Check the API base URL.': 'Адрес проверки связи не найден. Проверьте базовый адрес API.',
    'Connection check failed. The service returned an error; try again later.': 'Проверка связи не удалась: сервис вернул ошибку. Повторите позже.',
    'The service returned an unreadable connection-check response.': 'Сервис вернул непонятный ответ на проверку связи.',
    'Choose a role and connection type.': 'Выберите роль и способ подключения.',
    'Project models — Pi Kit': 'Модели проекта — Pi Kit',
    'Project models': 'Модели проекта',
    'Choose who plans the work and who writes the code.': 'Выберите, кто планирует работу и кто пишет код.',
    'Project: {name}': 'Проект: {name}',
    'Language': 'Язык',
    'Save settings': 'Сохранить настройки',
    'Prepare Pi': 'Подготовить Pi',
    'Restore defaults': 'Вернуть по умолчанию',
    'Save selects models for the next kit launch. Prepare builds the configuration now.\nThe current Pi session is not switched automatically.': 'Сохранение — для следующего запуска через кит. Подготовка — собрать настройки сейчас.\nТекущая сессия Pi автоматически не переключается.',
    'Master Chief': 'Мастер Чиф',
    'Executors': 'Исполнители',
    'Planning & review': 'Архитектура и ревью',
    'Code implementation': 'Реализация кода',
    'Model catalog & prices': 'Каталог и цены',
    'Plans, designs the architecture, and reviews the result.': 'Планирует, создаёт архитектуру и проверяет результат.',
    'Implement code from the Master Chief architecture. One selection for both executors.': 'Реализуют код по архитектуре Мастер Чифа. Один выбор для обоих исполнителей.',
    'Project defaults': 'Из настроек проекта',
    'Local · LM Studio': 'Локально · LM Studio',
    'Model from Pi': 'Модель из Pi',
    'Own API': 'Свой API',
    'The model from the project configuration will be used.': 'Будет использована модель из настроек проекта.',
    'Choose Pi or connect your own API to use another model.': 'Для другой модели выберите Pi или подключите свой API.',
    'Loaded model': 'Загруженная модель',
    'Refresh list': 'Обновить список',
    'Load a model in LM Studio first. Leave blank to select the only loaded model.\nThis utility does not load or unload models.': 'Сначала загрузите модель в LM Studio. Пустое поле — выбрать единственную загруженную.\nУтилита сама не загружает и не выгружает модели.',
    'Pi model': 'Модель Pi',
    'Get models': 'Получить модели',
    'Connections already known to Pi. Use the full provider/model ID.\nFetch the list or enter the ID manually.': 'Подключения, уже известные Pi. Полное имя: провайдер/модель.\nСписок можно получить кнопкой или ввести имя вручную.',
    '1. API address': '1. Адрес API',
    'Example: https://api.example.com/v1 — without /chat/completions or /models.': 'Например: https://api.example.com/v1 — без /chat/completions и /models.',
    '2. API key': '2. API-ключ',
    'Show': 'Показать',
    '3. Model': '3. Модель',
    'Select a model or enter its exact ID at your service.': 'Выберите из списка или введите точное имя модели у своего сервиса.',
    'Advanced': 'Дополнительно',
    'Key variable': 'Переменная ключа',
    'Saved selection loaded.': 'Сохранённый выбор загружен.',
    'Showing the defaults.': 'Показаны настройки по умолчанию.',
    'Could not read the saved selection. The file was not changed. Check the settings before saving.': 'Не удалось прочитать сохранённый выбор. Файл не изменён. Проверьте настройки перед сохранением.',
    'Unsaved changes': 'Есть несохранённые изменения',
    'New key entered; it will be saved with the settings.': 'Новый ключ введён; будет сохранён вместе с настройками.',
    'A key is already saved on this computer. Leave blank to keep it.': 'Ключ уже сохранён на этом компьютере. Пустое поле оставит его прежним.',
    'Paste your service key. The key itself is not written to the project file.': 'Вставьте ключ сервиса. В файл проекта сам ключ не записывается.',
    'A shared key has already been entered for the other role and will be used here too.': 'Общий ключ уже введён для другой роли; будет использован и здесь.',
    '{role}: selected {model}. The OpenRouter address is filled in; check the API key and save settings.': '{role}: подставлена {model}. Адрес OpenRouter заполнен; проверьте API-ключ и сохраните настройки.',
    '{role}: {message}': '{role}: {message}',
    'Could not save settings. Check access to the project folder and Windows user variables. Keys are not printed in the log.': 'Не удалось сохранить настройки. Проверьте доступ к папке проекта и пользовательским переменным Windows. Ключи не выводятся в журнал.',
    'Fetching models… You can keep using this window.': 'Получаем список моделей… Окном можно пользоваться.',
    'Fetching models…': 'получаем список моделей…',
    'Settings changed during the request. Fetch the list again.': 'Настройки изменились во время запроса. Получите список заново.',
    'Loaded: {names}': 'Загружено: {names}',
    'No models are loaded. Load a model in LM Studio and refresh the list.': 'Загруженных моделей нет. Загрузите модель в LM Studio и обновите список.',
    'Found {count} models. Choose one from the list.': 'Получено моделей: {count}. Выберите модель в списке.',
    'The service returned an empty list. You can enter the model ID manually.': 'Сервис вернул пустой список. Название модели можно ввести вручную.',
    '\nOnly /models was checked; generation and tools were not tested.': '\nПроверен только /models; генерация и инструменты не проверялись.',
    'Settings saved. The next kit launch will use this selection.': 'Настройки сохранены. Они будут использованы при следующем запуске через кит.',
    'Preparing Pi settings… The current session is not being restarted.': 'Готовим настройки Pi… Текущая сессия не перезапускается.',
    'Saved settings prepared. A new kit session will use this selection.': 'Сохранённые настройки подготовлены. Новая сессия через кит использует этот выбор.',
    'Selection saved, but preparation failed. Check Pi, API keys, or the loaded LM Studio model. The current session was not changed.': 'Выбор сохранён, но подготовка не удалась. Проверьте доступность Pi, API-ключи или загруженную модель LM Studio. Текущая сессия не изменена.',
    'Selection reset: Master Chief from project defaults, executors from LM Studio. Saved Windows keys were kept.': 'Выбор сброшен: Мастер Чиф из настроек проекта, исполнители из LM Studio. Сохранённые ключи Windows оставлены.',
    'Python with tkinter is required for this window.': 'Для окна настроек нужен Python с tkinter.',
    'For coding': 'Для кода',
    'All text models': 'Все текстовые',
    'All prices': 'Все цены',
    'Free models': 'Бесплатные',
    'Paid models': 'Платные',
    'Free to paid': 'От бесплатных к платным',
    'By input price': 'По цене входа',
    'By output price': 'По цене выхода',
    'By context': 'По контексту',
    'By name': 'По имени',
    'The catalog loads when this tab is opened. No API key is needed to browse.': 'Каталог загружается при открытии вкладки. API-ключ для просмотра не нужен.',
    'Choose a role, then click a model to fill in its own API settings.': 'Выберите роль, затем щёлкните по модели — поля своего API заполнятся автоматически.',
    'OpenRouter · catalog': 'OpenRouter · витрина',
    'OpenRouter models': 'Модели OpenRouter',
    'Refresh prices': 'Обновить цены',
    'USD per 1M tokens: input and output separately. Base catalog rates, excluding cache and special conditions.': 'USD за 1 млн токенов: вход и выход отдельно. Базовые ставки каталога, без учёта кэша и особых условий.',
    'Search': 'Поиск',
    'Tool support only': 'Только с инструментами',
    'Assign to:': 'Подставить в:',
    'Model · API ID': 'Модель · API ID',
    'Pricing': 'Тариф',
    'Input $/1M': 'Вход $/1M',
    'Output $/1M': 'Выход $/1M',
    'Context': 'Контекст',
    'Tools': 'Инструменты',
    'Role settings': 'К настройкам роли',
    'Model page': 'Страница модели',
    'Showing the previous catalog. ': 'Показан прежний каталог. ',
    'Updating prices from OpenRouter…': 'Обновляем цены из OpenRouter…',
    'Could not refresh the catalog. Check your connection and click Refresh prices.': 'Обновить каталог не удалось. Проверьте интернет и нажмите «Обновить цены».',
    ' Previous data is shown; prices may have changed.': ' Показаны прежние данные; цены могут измениться.',
    'Cache · ': 'Кэш · ',
    'Updated {time} (Vladivostok). ': 'Обновлено {time} (Владивосток). ',
    'Connect to the internet for fresh prices. ': 'Для свежих цен нужен интернет. ',
    'For coding: OpenRouter programming picks and code mentions in descriptions. ': '«Для кода»: подборка OpenRouter и упоминание кода в описании. ',
    '{shown} of {total}': '{shown} из {total}',
    'Yes': 'Да',
    'No': 'Нет',
    'Select a role and click a row. Enter also assigns the model. Save changes separately.': 'Выберите роль и щёлкните строку. Enter тоже подставляет модель. Изменения сохраняются отдельной кнопкой.',
    'Text model': 'Текстовая модель',
    '{name} · {kind}': '{name} · {kind}',
    '{role} ← {name}. Open role settings to save.': '{role} ← {name}. Для сохранения откройте настройки роли.',
    '\nCache: read {read}, write {write} per 1M.': '\nКэш: чтение {read}, запись {write} за 1M.',
    ' Per request: {price}.': ' За запрос: {price}.',
    ' Conditional rates apply for time or context length; see the model page.': ' Есть условные ставки: время или длина контекста; смотрите страницу модели.',
    ' Tool support is not declared; agents require it.': ' Поддержка инструментов не заявлена; для работы агентов она необходима.',
    'Unknown': 'Неизвестно',
    'Conditional': 'Условный',
    'Free': 'Бесплатно',
    'Paid': 'Платно',
    'OpenRouter picks': 'Подборка OpenRouter',
    'Code in name/description': 'Код в названии/описании',
    'Programming picks unavailable; For coding uses model names and descriptions.': 'Подборка programming недоступна; фильтр «Для кода» использует название и описание.',
    ' Could not save the cache.': ' Кэш сохранить не удалось.',
    'Enter an API base URL, for example https://api.example.com/v1. Do not include a key, login, or query parameters.': 'Укажите базовый адрес API: например, https://api.example.com/v1. Без ключа, логина и параметров в адресе.',
    'Enter the API base URL without /chat/completions, /responses, or /models.': 'Нужен базовый адрес API, без /chat/completions, /responses или /models.',
    'In Advanced, enter a variable name using Latin letters, digits, and _. Start with a letter or _.': 'В дополнительных настройках укажите имя переменной: латинские буквы, цифры и _, первый символ — буква или _.',
    'Paste an API key. If a key is already saved, check its variable name in Advanced.': 'Вставьте API-ключ. Если ключ уже сохранён, проверьте имя переменной в дополнительных настройках.',
    'The API key must be a single line.': 'API-ключ должен быть одной строкой.',
    'The roles have different keys but the same variable name. Use different variable names in Advanced.': 'У двух ролей разные ключи, но одинаковое имя переменной. Задайте разные имена в дополнительных настройках.',
    'Choose a model connection type.': 'Выберите способ подключения модели.',
    'Select a model or enter its exact ID.': 'Выберите модель из списка или введите её точное название.',
    'Pi requires the full provider/model ID.': 'Для Pi нужно полное имя: провайдер/модель.',
    'LM Studio did not respond. Start its server and load a model in LM Studio.': 'LM Studio не ответил. Запустите сервер и загрузите модель в LM Studio.',
    'Could not fetch models. Check that Pi is installed and available.': 'Не удалось получить список. Проверьте, что Pi установлен и доступен.',
    'Access denied. Check the API key and its permissions.': 'Сервис отклонил доступ. Проверьте API-ключ и его права.',
    'Model list not found. Check the base URL; you can enter a model ID manually.': 'Адрес списка моделей не найден. Проверьте базовый адрес; модель можно ввести вручную.',
    'Rate limited (429). Try again later; your entries remain in the form.': 'Сервис ограничил запросы (429). Попробуйте позже; введённые настройки сохранены в форме.',
    'The service returned an error. Check availability or enter a model ID manually.': 'Сервис вернул ошибку. Проверьте его доступность; модель можно ввести вручную.',
    'The service timed out. Check the connection or try again later.': 'Сервис не ответил вовремя. Проверьте соединение или повторите запрос позже.',
    'Could not connect. Check the API address, internet connection, and service availability.': 'Не удалось подключиться. Проверьте адрес API, интернет и доступность сервиса.',
    'The response is not an OpenAI-compatible model list. Check the address or enter a model ID manually.': 'Ответ не похож на список OpenAI-совместимого API. Проверьте адрес или введите модель вручную.',
    'Language changed, but the preference could not be saved.': 'Язык изменён, но сохранить выбор языка не удалось.',
}


@dataclass
class Text:
    key: str
    values: dict = field(default_factory=dict)


def text(key, **values):
    return Text(key, values)


class Translator:
    def __init__(self, language='en'):
        self.language = language if language in ('en', 'ru') else 'en'
        self.variables = []

    def render(self, value):
        if isinstance(value, (list, tuple)):
            return ''.join(self.render(part) for part in value)
        if not isinstance(value, Text):
            return str(value)
        template = RU.get(value.key, value.key) if self.language == 'ru' else value.key
        return template.format(**{key: self.render(item) for key, item in value.values.items()}) if value.values else template

    def tr(self, key):
        return self.render(Text(key))

    def var(self, value=''):
        variable = LocalizedVar(self, value)
        self.variables.append(variable)
        return variable

    def switch(self, language):
        self.language = language
        for variable in self.variables:
            variable.refresh()


class LocalizedVar(app.tk.StringVar if app.tk else object):
    def __init__(self, translator, value=''):
        self.translator = translator
        self.message = value if isinstance(value, (Text, list, tuple)) else Text(value)
        super().__init__(value=translator.render(self.message))

    def set(self, value='', **values):
        self.message = value if isinstance(value, (Text, list, tuple)) else Text(value, values)
        self.refresh()

    def refresh(self):
        super().set(self.translator.render(self.message))
