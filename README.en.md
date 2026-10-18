# Pi Agent Kit

[Русская версия](README.md) · [Quick start](docs/user/PI_QUICKSTART.en.md) · [Architecture guide in Russian](docs/kit/PI_ADAPTERS.ru.md)

A Pi adaptation of [opencode-environmental-tune](https://github.com/polar-byter/opencode-environmental-tune),
based on commit `03c128d7fd46e4b1346d37c0521b4b6cb4ea3361`.
The original Git history and MIT license are preserved. See [SOURCE.md](SOURCE.md).

The Chief plans the task, writes requirements, skeletons and tests, then delegates
small pieces to executors. Each executor works in a separate copy. The controller
tracks budgets; the Chief inspects and reviews results before accepted files are
integrated. A Bug Fixer receives failed implementations within its own budget.

## Start on Windows

Keep the repository on a drive with enough free space. Run `install.cmd` and
choose a separate target project folder. The installer copies the kit there and
opens its model configurator. Choose the role models, save and prepare Pi, then
run `start.cmd` from that target project and enter a task in the Chief console.

Pi **1.3.0** is installed locally in the template’s `.tools/pi`. Installed projects
reference it through `.pi/installation.json`, so keep the template folder. Settings,
histories and metrics remain with each target project. API keys are referenced by environment variable name;
they are not written into the generated JSON configuration. OpenCode Desktop is
not needed for this launch path. See the quick start for Python and Node details.

For a built-in Pi provider, run `start.cmd --authenticate` in your target project,
use `/login`, then `/quit`. Reopen `start.cmd --configure` and refresh the model
catalog. Global Pi login is not used: project credentials stay in the Git-ignored
`.pi/agent/auth.json`. Custom APIs still use the configurator's connection fields.

![Illustrated installation and configuration flow](readme_gif/pi_install.gif)

These GIFs are explanatory diagrams in Russian, not screen recordings or evidence
of a successful model run. Their reproducible source is in
[readme_gif](readme_gif/README.md).

## Shared rules, separate runtime

Planning, requirements, file snapshots, acceptance checks, tests, attempt budgets,
STOP and integration remain in the shared kit. The runtime adapter translates
session operations to Pi. A local project service owns Pi RPC processes and lets
the console, controller and dashboard use the same session state.

![Shared rules and runtime adapters](readme_gif/pi_adapters.gif)

Whole-task pause includes the Chief and executors. Closing the dashboard browser
does not stop them. Closing the console with `/quit` leaves the service running.
Use `start.cmd --stop-service` to close the service safely. A saved conversation
can be reopened; an interrupted generation is not silently treated as live work.

![Whole-task pause and resume](readme_gif/pi_sessions.gif)

The configurator retains custom APIs, OpenRouter browsing, loaded LM Studio
instances and execution limits. Model access configured in OpenCode does not
automatically become available in Pi; select a Pi connection explicitly.

Inherited OpenCode guides describe the source implementation. Use the Pi quick
start for current launch commands. Original test counts are not Pi validation;
see [validation status](docs/kit/PI_VALIDATION.ru.md).

## Verified example

[Tic-tac-toe](examples/tic-tac-toe/README.md) was built through real Pi sessions
using OpenRouter: DeepSeek for architecture and corrections, MiMo for workers.
The game has 20 tests and needs no external application dependencies.
The [live scenario report](docs/kit/PI_LIVE_SCENARIO.ru.md) records the defects
found and the actual pause, restore, resume, cancel and deletion checks.

The following is a recording of the actual game in the browser:

![Moves, an X win and a new game](readme_gif/pi_game_live.gif)

## Autonomous Chief exercise

In a fresh project the Chief received only the game requirements, dispatched two workers,
reviewed and integrated their results, checked the interface and recorded finish.
The observer did not guide development or perform acceptance. System defects,
subsequent fixes and evidence limits are recorded in the [run report](docs/kit/PI_CLEAN_RUN.ru.md).
