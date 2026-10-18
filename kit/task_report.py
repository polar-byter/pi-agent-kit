"""Read a completed task's frozen report without starting work or collecting new usage."""
import argparse
from pathlib import Path
import sys

from .task_metrics import TaskMetrics


def read_completed_task_report(project, task, language=None):
    metrics = TaskMetrics(Path(project).resolve())
    events = metrics.read(task)
    finished = next((event for event in events if event['kind'] == 'finish'), None)
    if not finished:
        raise ValueError('This task has not recorded finish yet.')
    if language is None:
        from .localization import load_language
        language = load_language(metrics.root)
    return metrics.render(task, events, finished['usage'], finished['ended'], language)


def main(arguments=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--task', required=True)
    parser.add_argument('--language', choices=('ru', 'en'))
    options = parser.parse_args(arguments)
    try:
        print(read_completed_task_report(options.root, options.task, options.language))
        return 0
    except (OSError, ValueError) as error:
        print('Report unavailable: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
