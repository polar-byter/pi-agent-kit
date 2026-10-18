> Материал исходной версии OpenCode. Сохранён для изучения общего кита и истории.
> Для текущей адаптации используй [быстрый старт Pi](../user/PI_QUICKSTART.ru.md)
> и [карту адаптеров](../kit/PI_ADAPTERS.ru.md). Команды OpenCode здесь не являются командами Pi.

# OpenCode: the Master Chief and executors

> Русская версия: [README.md](../../README.md) · Step-by-step start: [QUICKSTART.en.md](../../docs/user/QUICKSTART.en.md) · [Быстрый старт (RU)](../../docs/user/QUICKSTART.ru.md) · [Beginner guide](../../docs/user/OPENCODE_KIT.en.md)

You describe a task in OpenCode, and a team of AI agents takes it from there. The
**Master Chief** (the main `build` agent) plans the work and the contracts between
parts of the program, writes blanks and tests, hands implementation to **executors**,
reviews their work and, at the end, checks the application interface.
If an executor makes a mistake or hits a limit, the **Bug Fixer** takes over with its own retry budget.
Every step goes into a journal, and a browser dashboard shows the progress.

**It works like a building site.** The Master Chief is the foreman: reads the
order, draws the plan, hands out work and accepts the result. Executors are the workers:
each builds a small section exactly as drawn, and several can work at the same time.
The Bug Fixer redoes a section that did not work out.
Your part is to say what you need, answer questions and accept the result.

## How it works — in eight diagrams

The diagrams are animated; their data is sample data. The same diagrams with detailed
steps are in the [quick start](../../docs/user/QUICKSTART.en.md).

### 1. Installation in four steps

You need [OpenCode Desktop](https://opencode.ai/download) and this repository's
ZIP (**Code → Download ZIP**). The installer automatically prepares pinned Python
3.13.16 with Tk from python.org; internet access is needed on first launch.
Extract the ZIP and double-click **install.cmd**. The setup
wizard finds Desktop, creates the project folder, copies the kit there and opens the
model settings. Free models are already filled in — just click "Save settings" and
"Prepare OpenCode". Then the project opens in Desktop: copy the example prompt, paste
it into a new **build** chat and send it. The wizard never sends anything to a model itself.

For Ubuntu, Debian and Mint, use the [`.deb` installer](../../docs/user/LINUX_INSTALL.ru.md)
(Russian guide): open the package with the mouse, then launch OpenCode Project Setup from the applications menu.

![Installation in four steps](../../readme_gif/en/01_install.gif)

Here is how it looks in the wizard itself:

![The setup wizard](../../readme_gif/en/01_install_live.gif)

### 2. Who is in the team

Everyone has a role. The Master Chief thinks and reviews. Executors write code from
ready descriptions — from one to eight of them, each in its own copy of the files.
The Bug Fixer has its own correction budget when an executor does not finish. The **controller** is not AI but
a plain kit program: it hands out file copies, watches the limits and moves accepted
code into the project. The journal and dashboard make all of this visible.

![Who is in the team](../../readme_gif/en/02_team.gif)

### 3. How the Master Chief prepares the work

Write the task straight into chat, or put it in `TASK.md` and send "Start"; if they
disagree, chat wins. The Master Chief reads the kit rules (`AGENTS.md`), the plan from
earlier sessions (`currentsteps.md`) and what the project already has. It decides
which parts the program needs and in what order, and fixes the contracts between parts
up front — which functions exist, what they take and return. It writes blanks with
detailed descriptions and the tests right away. While the functions are empty the tests
fail.

![How the Master Chief prepares the work](../../readme_gif/en/03_plan.gif)

### 4. Several executors at once

If two parts of the program do not depend on each other, they can be built in parallel.
The controller gives each executor **its own copy of the files** — they never touch the
main project or each other. A watchdog guards every attempt: how many steps, how long,
whether the model keeps repeating the same actions. The Master Chief reviews each
copy separately — its changes, its tests, every requirement. Accepted files are moved
into the project one by one, and if a file changed there meanwhile, nothing is
overwritten. Finally the full test suite runs on the main project. There is one
executor by default; the number is set in the settings.

![Several executors at once](../../readme_gif/en/04_parallel.gif)

### 5. The Bug Fixer: when and how

If review finds a bug in an executor's code, or the executor runs out of steps or time,
the work goes to the Bug Fixer: the same file, the same requirements and the test
error output. It only repairs function bodies, and the Master Chief reviews again.
A service error (including a `429` rate limit), a broken test setup, a pause or a cancel
never calls the Bug Fixer — those are not code bugs. When its repair or total budget is exhausted, work
stops with `STOP` and waits for your decision; it never bounces back to the executor.

![The Bug Fixer](../../readme_gif/en/05_bugfixer.gif)

The animation shows one handoff. Further corrections stay with the Bug Fixer.
Defaults per work item: 3 executor code failures, 6 Bug Fixer failures, 9 combined.
API and setup interruptions do not spend these budgets. Change the limits in model settings.

### 6. The finish: interface, tests, report

When every part is accepted and integrated, the UI/UX improvement stage begins. The
Master Chief runs the application and walks through normal scenarios by hand: opens
forms, fills them in, saves, enters a deliberate error. It notes what gets in the
user's way — faint text, an unlabeled button, a cryptic error message — and fixes the
interface without touching the logic. Then the full test suite, the final report and a
launch file.

The stage is recorded in the task journal, and the kit will not finish the task without
that record. The report and dashboard show one line: "UI/UX improvement stage completed:
5 scenarios checked, 3 issues fixed", "UI/UX improvement stage skipped due to no browser
available" or "UI/UX improvement stage not required: the application has no interface".

![The finish](../../readme_gif/en/06_final.gif)

### 7. Models, limits and keys

In the "Project models" window every role has its own model: from the OpenCode catalog,
through your own API or — for executors — locally in LM Studio. This is also where you
set how many executors run at once and the limits of one attempt (steps, seconds,
repeats), the Bug Fixer's own limits, or switch the Bug Fixer off. The OpenRouter
catalog shows prices and fills a role with one click. The API key lives in a Windows
variable; the project stores only its name. "Check connection" never generates anything.
After "Prepare OpenCode", open a new build chat.

![Models, limits and keys](../../readme_gif/en/07_models.gif)

### 8. The dashboard: every executor in view

The dashboard opens by itself. "Working now" shows every participant and the function
it is working on. "Work details" lists every attempt: who did it, how it ended, whether
it was integrated. "Tokens" shows usage per model and per attempt; if some data is
missing, the sum is marked "≥" and zero is never substituted. Buttons pause, resume,
cancel or delete the whole task with all its executors. The interface is in English or
Russian, following the browser, with a manual switch.

![The dashboard](../../readme_gif/en/08_dashboard.gif)

Diagram files and how to rebuild them: [readme_gif/README.md](../../readme_gif/README.md).
To look inside: [developer guide with diagrams and a map of modules, classes and
functions (Russian)](../../docs/kit/EXECUTION_GUIDE.ru.md), [installer architecture (Russian)](../../docs/kit/INSTALLER.ru.md),
[localization (Russian)](../../docs/kit/LOCALIZATION.ru.md), [role prompts](../../kit/prompts/README.ru.md).

## How to use it

The easiest path is the setup wizard (diagram 1) and the [beginner guide](../../docs/user/OPENCODE_KIT.en.md).
To add the kit to an existing project by hand, use the [quick start](../../docs/user/QUICKSTART.en.md).
Tools are installed once per computer.

You can write the requirements straight into chat, or save them in `TASK.md` and send
a short "Start". The file is optional when the task is already in chat. Your current
instructions take priority. The Master Chief reads the kit rules, the plan and other
needed documents itself; you do not have to list them. For example:

> Add expense tracking: amount, category and date. Negative amounts are not allowed. Show me the plan first.

The Master Chief proposes a solution. You discuss the requirements and approve the
plan. After that it assigns jobs, calls the needed scripts and checks the result. If
it lacks information or access, it explains what it needs from you.

To change models during a task, pause it in the dashboard, save and prepare the new selection, then resume. See [live model changes](../../docs/user/LIVE_MODELS.ru.md) (Russian). If the executors use LM Studio, the
model must be loaded and its server running; other sources do not need that. The
Master Chief prepares the selected models as described in `AGENTS.md`;
`kit/run_opencode.py` remains the configuration preparer and an alternative launcher.

Parallel executors and the watchdog run in the shared OpenCode Desktop service. In the
private `--standalone` mode the kit keeps the earlier sequential protocol. Existing
saved choices and journals remain readable.

In the dashboard you can pause the task with all its executors, resume it, cancel it,
or delete its sessions and metrics while keeping the source code.
Semantics and limits: [task controls](../../kit/dashboard/CONTROLS.ru.md) (Russian).
The dashboard and configurator support **EN/RU**; agent messages stay in their original language.

To repeat our experiment from Desktop there is a [short guide](../../docs/history/DESKTOP_EXPERIMENT.ru.md) (Russian).
Own API, the OpenRouter catalog with prices, roles and language are described in
the [configurator guide](../../kit/configurator/UX.ru.md) (Russian).

## What the Master Chief does during the work

The Master Chief splits the task into small pieces so the local executor gets a clear
job. Usually one job is a small complete class: constructor and related methods. A
single function is handed out for a targeted fix or when a class is too large.

1. Reads the project plan and current code, clarifies requirements.
2. Opens task tracking so its statistics do not mix with earlier work. The start
   command automatically launches the project dashboard and opens this task's page.
3. Creates the code skeleton and writes tests. Until the functions are implemented,
   these tests are expected to fail.
4. Hands the executor a small class or related file with requirements written down in advance.
   With more than one executor selected, independent parts run in parallel, each in its own copy of the files.
5. Reviews the returned code. If fixes are needed, records a rework; after a code bug or an
   attempt limit it hands the work to the Bug Fixer.
6. Runs tests through the tracking script and checks the results. Integrates accepted
   files into the main project one by one.
7. Reviews the interface in real scenarios when the tools allow it and fixes it as a separate phase.
8. Runs the full test suite, updates the plan, collects statistics and shows the outcome.


## What you get at the end

During the work the local dashboard shows task status, events, test runs, reworks and
executor failures. The page refreshes every 2 seconds; you can pick another task of
this project and open the final report. The server is reused between tasks. Details:
[dashboard](../../kit/dashboard/README.ru.md) (Russian). The dashboard shows the
architecture, the actual models, handoffs to executors, the current function, reported
and accepted progress, work details and available tokens during the task. The model
settings button opens the project's model configurator. After completion you see the
summary, a link to the folder and a launch-file viewer. Function progress needs a
published registry and executor messages; missing data and tokens are never replaced
with zeros.

The Master Chief explains what was done, which checks passed and what remains open.
A separate block shows:

- task time;
- tokens of paid models;
- tokens of free / local models — everything running through `lmstudio`;
- tokens of free cloud models — OpenRouter models ending in `:free` and OpenCode models ending in `-free`;
- usage per executor and Bug Fixer attempt — included in the total;
- the number of code reworks after review;
- how many full test runs succeeded and how the last one ended.

Tokens are units of text a model receives and generates. They help you see how work
was split between models. The script does not compute money cost or savings yet.

## How the Master Chief collects statistics

The Master Chief calls `kit/task_metrics.py` at the right moments itself. This is part
of its orchestration. In a normal task you do not type these commands.

1. **Task start.** The Master Chief passes the time and session ID (the current
   OpenCode conversation) to the script. This separates the new task from earlier work.
2. **Review.** After checking code, the Master Chief records whether it was accepted or
   sent back. One return counts as one rework, however many remarks it has.
3. **Tests.** The Master Chief runs them through the script, which saves the real
   command result. "3 of 5 green runs" means three successful test commands out of
   five. It also says how many runs covered the full suite and how many a selected
   class or module. An empty suite or skipped tests never count as full success.
4. **Tokens.** Before the final answer the Master Chief has the script read messages
   of the main and child OpenCode sessions. It picks completed messages within the task
   time and sums their counters per model.
5. **Model groups.** Every `lmstudio` model goes into the local group, OpenRouter models
   ending in `:free` and OpenCode models ending in `-free` into the free cloud group, other known providers into the paid
   group by default. New LM Studio models are counted without a manual list.
6. **Report.** The script saves `.metrics/<task ID>/report.md`. The Master Chief puts it
   into the final answer. If a planner writes the answer, it uses the same file.

If OpenCode returns no data, the report says "no data". Time includes waiting for your
answers, and tokens of messages after the report is built are not counted yet. Details
and debug commands: [statistics guide](../../docs/kit/METRICS.ru.md) (Russian).

## Continuing after a break

The Master Chief keeps `currentsteps.md`: completed steps, decisions and next tasks.
In a new conversation you can ask:

> Read the project plan and continue with the next task.

The Master Chief finds the plan by the rule in `AGENTS.md`. By default it lives in the
selected Obsidian vault, or in the project root without Obsidian.

## If something stops working

Start by describing the problem to the Master Chief. For example:

> The local executor stopped responding. Check the settings and the LM Studio connection and show the cause.

The Master Chief can read the config, run the connection check and a small example for
the local model. If the problem needs your action — for example loading a model in
LM Studio — it explains what to do. Diagnostic commands are for the agent and manual
debugging; you do not need to run them all before each task.

## Versions and updates

The kit uses the CLI bundled with your OpenCode Desktop installation. The following reference explains command selection and compatibility checks.

### Which OpenCode the kit uses

One computer often has several OpenCode installs: the Desktop app with its own CLI
inside and separately installed commands, e.g. via npm. Their versions can differ a lot.
An old CLI does not understand the settings the kit writes: it rejects the `providers`
and `agents` keys or silently keeps the old models for agents.

All kit scripts — launch, `--prepare-only`, the model settings window and statistics —
look for OpenCode in the same order (`kit/opencode_cli.py`):

1. The path or command from `--opencode`, if you gave one.
2. The CLI inside OpenCode Desktop: `%LOCALAPPDATA%\Programs\@opencodedesktop\resources\opencode-cli.exe`.
   You work in Desktop, so this CLI sees the same sessions and matches the version of
   the app that reads the settings.
3. The `opencode` command from `PATH` — for Linux, macOS and computers without Desktop.

`.cmd`/`.bat` wrappers (how npm installs commands) are not used for launching: they can
mangle arguments and often lead to another, older version. Only statistics use such a
wrapper as a last resort; it is enough for reading sessions.

How to set it up:

1. Check which OpenCode installs you have and their versions:

   ```powershell
   Get-Command opencode*
   & "$env:LOCALAPPDATA\Programs\@opencodedesktop\resources\opencode-cli.exe" --version
   ```

2. If Desktop is installed, the kit takes its CLI even when another `opencode` is on
   `PATH`. It is better to update or remove the old `PATH` command so you do not run it
   by mistake. Commands with other names (e.g. `opencode2`) are never called by the kit.
3. To use a specific CLI, pass the path explicitly:
   `kit\python.cmd kit/run_opencode.py --opencode "C:\path\opencode-cli.exe"`, and for statistics
   `task_metrics.py finish --opencode ...`.
4. After changing models, check that OpenCode accepted them. `debug agents` is not
   enough: it shows agent models, while the main session runs on the top-level `model`
   key. A reliable check is a short real session and the model from its export:

   ```powershell
   $cli = "$env:LOCALAPPDATA\Programs\@opencodedesktop\resources\opencode-cli.exe"
   $out = kit\python.cmd kit/run_opencode.py -- run --format json "Reply with the single word OK." | Out-String
   $session = [regex]::Match($out, '"sessionID":"(ses_[A-Za-z0-9]+)"').Groups[1].Value
   (& $cli session export $session | ConvertFrom-Json).messages.model | Select-Object -Unique providerID, id
   ```

   It should show the Master Chief's model. The executor model appears in the child
   session export after the first executor job. A config error means the CLI is too old.

After an update, ask the Master Chief to check compatibility:

> OpenCode was updated. Check the version, session access and statistics on a small task.

The Master Chief should check the available commands, run the kit tests and compare the
report with the message export. If the format changed, it shows which part of data
reading needs fixing. We mark a new version as verified after such a run.

## Where the settings live

Useful for the first setup or if you want to change how the system works.

| File | Responsible for |
|---|---|
| `opencode.jsonc` | Models, connections and agent permissions |
| `AGENTS.md` | Workflow, application test command and plan location |
| `.opencode/commands/` | Optional `/plan-project` and `/module` prompt templates |
| `kit/` | Scripts the Master Chief calls, and their tests |
| `.metrics/` | Task journals and reports; not pushed to Git |

`build` currently uses `opencode-go/deepseek-v4.1-flash`. When launched through
`kit/run_opencode.py`, both executors use the already loaded LM Studio instance. With
several models the script picks the loaded model from the `executor` setting or asks for
an ID. Launching OpenCode directly without preparation uses the fixed aliases from the
original config. Details, including launching in an already open app:
[model selection](../../docs/user/LOCAL_MODELS.ru.md) (Russian). The `/plan-project` command also calls `build`.

For another project, copy the kit files and set its language, folders and test command
in `AGENTS.md`. Step-by-step setup is in the quick start. After that you can give tasks
in plain text.

## Adding your language

The kit fits any language, but the statistics script must **read the test results**:
how many there were and how many failed. It understands two formats:

- the Python `unittest` summary line;
- **JUnit XML** — a common test report format that almost every build system can produce.

If the result cannot be read, failed tests still count as failed, but green ones get the
status "unknown", and the Master Chief treats the run as a setup problem. So write the
test command in the `Project stack` section of `AGENTS.md` together with the report flags.

| Language | Install once | Test command for `Project stack` |
| --- | --- | --- |
| Python (unittest) | nothing | `kit\python.cmd kit/task_metrics.py test --task <ID> -- kit\python.cmd -m unittest discover -s tests -v` |
| Python (pytest) | `pip install pytest` | `kit\python.cmd kit/task_metrics.py test --task <ID> --junit .metrics/<ID>/run-NN.xml -- kit\python.cmd -m pytest --junitxml=.metrics/<ID>/run-NN.xml` |
| Java, Kotlin (Maven) | nothing | `kit\python.cmd kit/task_metrics.py test --task <ID> --junit-dir target/surefire-reports -- mvn -q test` |
| Java, Kotlin (Gradle) | nothing | `kit\python.cmd kit/task_metrics.py test --task <ID> --junit-dir build/test-results/test -- gradlew test` (macOS and Linux: `./gradlew test`) |
| C# (.NET) | `dotnet add <TestProject> package JunitXml.TestLogger` | `kit\python.cmd kit/task_metrics.py test --task <ID> --junit .metrics/<ID>/run-NN.xml -- dotnet test --results-directory .metrics/<ID> --logger "junit;LogFileName=run-NN.xml"` |
| JS, TS, React, Vue (Vitest) | nothing | `kit\python.cmd kit/task_metrics.py test --task <ID> --junit .metrics/<ID>/run-NN.xml -- npx vitest run --reporter=junit --outputFile=.metrics/<ID>/run-NN.xml` |
| JS, TS, React (Jest) | `npm i -D jest-junit cross-env` | `kit\python.cmd kit/task_metrics.py test --task <ID> --junit .metrics/<ID>/run-NN.xml -- npx cross-env JEST_JUNIT_OUTPUT_FILE=.metrics/<ID>/run-NN.xml jest --ci --reporters=default --reporters=jest-junit` |
| Go | `go install gotest.tools/gotestsum@latest` | `kit\python.cmd kit/task_metrics.py test --task <ID> --junit .metrics/<ID>/run-NN.xml -- gotestsum --junitfile .metrics/<ID>/run-NN.xml` |
| Rust | `cargo install cargo-nextest` and a profile with `junit` in `.config/nextest.toml` | `kit\python.cmd kit/task_metrics.py test --task <ID> --junit-dir target/nextest -- cargo nextest run` |
| PHP (PHPUnit) | nothing | `kit\python.cmd kit/task_metrics.py test --task <ID> --junit .metrics/<ID>/run-NN.xml -- vendor/bin/phpunit --log-junit .metrics/<ID>/run-NN.xml` |

Rules not to break:

1. **`--junit <file>`** — for tools that write one file. The file must not exist before
   the run, so the Master Chief numbers runs: `run-01.xml`, `run-02.xml` and so on.
   `AGENTS.md` says `run-NN`; the Master Chief fills in the number.
2. **`--junit-dir <folder>`** — for tools that write a file per class or project: Maven,
   Gradle, several .NET test projects (use `LogFilePath=<folder>/{assembly}.xml` in the
   logger). The script reads only files from this run.
3. **No watch mode.** Jest and Vitest wait for file changes by default and never exit.
   Use `vitest run` and `jest --ci`, or the run ends on a timeout.
4. **Windows and `.cmd`.** The script finds `npx`, `npm`, `mvn`, `gradlew` itself; no
   need to add `.cmd`.

After writing the command, check it once:

```bash
kit\python.cmd kit/task_metrics.py check <same report flags> -- <same test command>
```

`CHECK OK` — ready to work. `CHECK FAILED` — hints appear below the line. Details:
`docs/kit/METRICS.ru.md`, section 3 (Russian).

## How results are checked

The Chief records requirements before implementation, then links each requirement to code and a test during review. After integration, the full test suite must pass. A module test alone does not establish application readiness.

See the [review reference](../../docs/kit/PIPELINE.ru.md) (Russian) for commands and examples.

## License

[MIT](../../LICENSE).
