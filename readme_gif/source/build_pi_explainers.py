"""Build the Pi README diagrams using the original project's drawing toolkit."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from gifkit import (
    BLUE, BORDER, CYAN, GREEN, MUTED, ORANGE, PANEL, PURPLE, TEXT,
    Cv, build, card, chrome, seg,
)


OUTPUT_DIRECTORY = Path(__file__).resolve().parents[1]


def draw_explanation_label(canvas: Cv) -> None:
    canvas.t(40, 82, "Поясняющая схема · не запись экрана", 16, fill=MUTED)


def draw_connected_cards(
    canvas: Cv, descriptions: list[tuple[str, str]], current_step: int,
    progress: float,
) -> None:
    for card_index, (title, explanation) in enumerate(descriptions):
        horizontal_position = 40 + card_index * 390
        card(
            canvas, horizontal_position, 230, 340, 150, title, explanation,
            BLUE, active=card_index == current_step, tsize=23, ssize=18,
        )
        if card_index < len(descriptions) - 1:
            arrow_progress = seg(progress, 0.05, 0.65) if current_step == card_index else 1
            canvas.arrow(
                [(horizontal_position + 345, 305), (horizontal_position + 385, 305)],
                BLUE if current_step == card_index else BORDER,
                prog=arrow_progress,
            )


INSTALLATION_STEPS = [
    {"cap": "Помести отдельный репозиторий на D. Пакеты Pi и кеш его установки останутся рядом с проектом.", "T": 8, "hold": 3200},
    {"cap": "В install.cmd выбери отдельную папку проекта. Мастер установит Pi рядом с шаблоном и откроет конфигуратор.", "T": 8, "hold": 3600},
    {"cap": "Выбери модели, сохрани и подготовь Pi. Затем запусти start.cmd из своего проекта и напиши задачу Чифу.", "T": 8, "hold": 3800},
]


def draw_installation(canvas: Cv, current_step: int, progress: float) -> None:
    draw_explanation_label(canvas)
    draw_connected_cards(canvas, [
        ("Папка на D", "Исходники, .tools/pi и локальные данные проекта"),
        ("install.cmd", "Pi 1.3.0, затем окно настройки моделей"),
        ("start.cmd", "Консоль Чифа и служба сессий Pi"),
    ], current_step, progress)
    canvas.t(40, 450, "Чиф · исполнители · исправитель", 21, "s", fill=CYAN)
    canvas.para(40, 490, "Собственные API, LM Studio, OpenRouter и лимиты остаются в конфигураторе.", 1100, 21)


ADAPTER_STEPS = [
    {"cap": "Кит хранит требования, попытки, проверки, лимиты и решения о приёмке. Это общие правила задачи.", "T": 8, "hold": 3600},
    {"cap": "Общий шлюз выражает действия: создать сессию, передать поручение, остановить и подтвердить состояние.", "T": 8, "hold": 3700},
    {"cap": "Адаптер Pi обращается к службе, которая владеет RPC-процессами. OpenCode использует свою реализацию шлюза.", "T": 8, "hold": 4200},
]


def draw_adapters(canvas: Cv, current_step: int, progress: float) -> None:
    draw_explanation_label(canvas)
    card(canvas, 40, 220, 340, 190, "Общий кит", "Журнал, требования, тесты, приёмка, STOP и перенос файла", GREEN, active=current_step == 0, tsize=24, ssize=20)
    card(canvas, 435, 220, 315, 190, "Шлюз выполнения", "Сессии, события, модели и подтверждение остановки", BLUE, active=current_step == 1, tsize=23, ssize=19)
    card(canvas, 810, 160, 345, 145, "Адаптер Pi", "Локальная служба и процессы Pi RPC", PURPLE, active=current_step == 2, tsize=24, ssize=18)
    card(canvas, 810, 350, 345, 145, "Адаптер OpenCode", "Сервер и сессии исходной среды", CYAN, tsize=23, ssize=18)
    canvas.arrow([(385, 315), (429, 315)], GREEN, prog=seg(progress, 0, 0.7) if current_step == 0 else 1)
    for vertical_position, color in [(230, PURPLE), (420, CYAN)]:
        canvas.arrow([(755, 315), (780, 315), (780, vertical_position), (805, vertical_position)], color, prog=seg(progress, 0, 0.7) if current_step == 2 else 1)
    canvas.t(40, 510, "Решение кита остаётся тем же. Способ исполнения выбирает адаптер.", 22, fill=TEXT)


SESSION_STEPS = [
    {"cap": "Служба проекта связывает Чифа и исполнителей с одной задачей. Браузер дашборда можно закрыть.", "T": 8, "hold": 3600},
    {"cap": "Пауза останавливает участников и очищает очередь. Дождись подтверждения, прежде чем менять настройки.", "T": 8, "hold": 3900},
    {"cap": "На паузе сохрани и подготовь новые модели. Проверка ревизии настроек относится к общей логике кита.", "T": 8, "hold": 3900},
    {"cap": "Продолжение использует прежнюю задачу и историю. После перезапуска не считается, что старый запрос ещё выполняется.", "T": 8, "hold": 4400},
]


def draw_sessions(canvas: Cv, current_step: int, progress: float) -> None:
    draw_explanation_label(canvas)
    status = "В работе" if current_step in (0, 3) else "Пауза подтверждена"
    status_color = GREEN if current_step in (0, 3) else ORANGE
    card(canvas, 40, 135, 1115, 110, "Локальная служба проекта", "Владеет процессами и хранит связи сессий", BLUE, active=True, tsize=25, ssize=20)
    for role_index, title in enumerate(["Мастер Чиф", "Исполнитель 1", "Исполнитель 2"]):
        horizontal_position = 40 + role_index * 390
        canvas.arrow([(horizontal_position + 170, 250), (horizontal_position + 170, 285)], status_color, prog=seg(progress, 0, 0.7))
        card(canvas, horizontal_position, 290, 340, 135, title, status, status_color, active=True, tsize=23, ssize=19)
    if current_step == 2:
        canvas.t(40, 490, "Конфигуратор → сохранить → подготовить Pi", 25, "s", fill=ORANGE)
    else:
        labels = ["Общая задача и отдельные процессы", "Остановка подтверждается для всей задачи", "", "История сохранена · новые действия разрешены"]
        canvas.t(40, 490, labels[current_step], 24, fill=TEXT)


PARALLEL_STEPS = [
    {"cap": "Чиф готовит поручения. Независимые части могут выполняться одновременно в отдельных копиях.", "T": 8, "hold": 3500},
    {"cap": "Исполнитель правит назначенный исходник и файл прогресса. Контроллер следит за бюджетом попытки.", "T": 8, "hold": 3800},
    {"cap": "Чиф проверяет изменения, требования и тесты. Принятый файл переносится после проверки исходного состояния.", "T": 8, "hold": 4200},
]


def draw_parallel_execution(canvas: Cv, current_step: int, progress: float) -> None:
    draw_explanation_label(canvas)
    card(canvas, 40, 260, 285, 130, "Мастер Чиф", "План, требования и тесты", BLUE, active=current_step == 0, tsize=24, ssize=19)
    for vertical_position, label in [(150, "Копия исполнителя 1"), (360, "Копия исполнителя 2")]:
        card(canvas, 420, vertical_position, 350, 140, label, "Свой исходник и прогресс", ORANGE, active=current_step == 1, tsize=22, ssize=19)
        canvas.arrow([(330, 325), (370, 325), (370, vertical_position + 70), (415, vertical_position + 70)], ORANGE, prog=seg(progress, 0, 0.6) if current_step == 1 else 1)
        canvas.arrow([(775, vertical_position + 70), (815, vertical_position + 70), (815, 325), (855, 325)], GREEN, prog=seg(progress, 0, 0.6) if current_step == 2 else 1)
    card(canvas, 860, 260, 295, 130, "Проверка и перенос", "inspect → тесты → review", GREEN, active=current_step == 2, tsize=22, ssize=18)


EXPLAINERS = [
    ("pi_install", "Установка и настройка", INSTALLATION_STEPS, draw_installation),
    ("pi_adapters", "Общие правила и адаптеры", ADAPTER_STEPS, draw_adapters),
    ("pi_sessions", "Пауза, модели и продолжение", SESSION_STEPS, draw_sessions),
    ("pi_parallel", "Параллельные исполнители", PARALLEL_STEPS, draw_parallel_execution),
]


def save_review_contact_sheet(output_directory: Path) -> None:
    review_frames = []
    for filename, title, steps, draw_diagram in EXPLAINERS:
        for step_index in range(len(steps)):
            canvas = Cv()
            draw_diagram(canvas, step_index, 1.0)
            chrome(canvas, "Pi Kit", title, step_index, steps, 1.0)
            review_frames.append(canvas.im.resize((600, 338)))
    contact_sheet = Image.new("RGB", (1200, 338 * ((len(review_frames) + 1) // 2)), PANEL)
    for frame_index, frame in enumerate(review_frames):
        contact_sheet.paste(frame, ((frame_index % 2) * 600, (frame_index // 2) * 338))
    contact_sheet.save(output_directory / "pi_review_frames.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=OUTPUT_DIRECTORY)
    arguments = parser.parse_args()
    arguments.output_directory.mkdir(parents=True, exist_ok=True)
    for filename, title, steps, draw_diagram in EXPLAINERS:
        output_path = arguments.output_directory / (filename + ".gif")
        frame_count = build(str(output_path), steps, draw_diagram, "Pi Kit", title)
        print(f"{output_path.name}: {frame_count} frames, {output_path.stat().st_size} bytes")
    save_review_contact_sheet(arguments.output_directory)


if __name__ == "__main__":
    main()
