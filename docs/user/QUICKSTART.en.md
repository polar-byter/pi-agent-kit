> Материал исходной версии OpenCode. Сохранён для изучения общего кита и истории.
> Для текущей адаптации используй [быстрый старт Pi](../user/PI_QUICKSTART.ru.md)
> и [карту адаптеров](../kit/PI_ADAPTERS.ru.md). Команды OpenCode здесь не являются командами Pi.

# Quick start: the OpenCode kit, step by step in plain words

> A from-scratch guide for people who do not write code every day.
> Русская версия: [QUICKSTART.ru.md](QUICKSTART.ru.md) · Project overview: [README.en.md](../../README.en.md) ·
> Short setup-wizard guide: [OPENCODE_KIT.en.md](OPENCODE_KIT.en.md)

This guide shows, step by step, how to install the kit, choose models and give the
first task. Eight animated diagrams show each stage; their data is sample data.
The manual setup example is a small Java application, but the order is the same for
any language.

---

## 1. What this is and why

Think of a building site. There is a **foreman** who reads the order, draws the plan,
hands out work and accepts the result. There are **workers** who build small sections
exactly as drawn, and several of them can work at the same time. If a section
did not work out, **another builder** redoes it.

The kit works the same way:

- 🪖 **Master Chief** — the main AI agent (called `build` in OpenCode). It understands
  the task, designs the program and the contracts between its parts, writes a code
  "skeleton" with detailed explanations plus the tests, reviews the work and, at the
  end, checks the application interface.
- 🛠 **Executors** — models that fill in the "insides" of functions from a ready
  description. There can be one to eight of them; each works in its own copy of the files.
- 🩹 **Bug Fixer** — a separate model with its own budget to repair the work if an
  executor made a mistake or hit a limit.
- ⚙ **Controller** — not AI but a plain kit program: it hands out file copies, watches
  the limits and moves accepted code into the project.
- 📒 **Journal and dashboard** — a tracking script records every step, and a browser
  page shows the progress.

Your part: say what you need, answer questions and accept the result.
The Master Chief runs the commands, checks and statistics itself.

![Who is in the team](../../readme_gif/en/02_team.gif)

### How the Master Chief prepares the work

When it gets a task, the Master Chief first reads the project documents: the
requirements (your message or a `TASK.md` file), the kit rules (`AGENTS.md`), the plan
from earlier sessions (`currentsteps.md`) and a description of the existing code. Then
it decides which parts the program needs and in what order, and writes down the
contracts between parts: which functions exist, what they take and return. For each
part it creates a blank — function names and a detailed description. It writes the
tests right away — small automatic checks. While the functions are empty the tests fail
("red") until the work is done.

![How the Master Chief prepares the work](../../readme_gif/en/03_plan.gif)

### How the executors work

If parts of the program do not depend on each other, they can be built at the same
time. The controller gives each executor its own copy of the files — they never touch
the main project. A watchdog guards every attempt: how many steps, how long, whether
the model keeps repeating itself. The Master Chief reviews each copy separately: what
changed, whether its tests pass, whether every requirement is met. Accepted files are
moved into the project one by one, and nothing else is overwritten on the way.

![Several executors at once](../../readme_gif/en/04_parallel.gif)

### When the Bug Fixer is called

If review finds a bug or an executor runs out of its limit, the work goes to the Bug
Fixer once: the same file, the same requirements and the error output. A service error
(for example a `429` rate limit), a broken test setup, a pause or a cancel never calls
the Bug Fixer. When the correction budget is exhausted, work stops with `STOP` and waits for your
decision.

![The Bug Fixer](../../readme_gif/en/05_bugfixer.gif)

---

## 2. A few words you will meet

| Word | Meaning |
| --- | --- |
| **Model** | The AI "brain" that writes text and code. Cloud models run on the internet, local ones on your computer. |
| **LM Studio** | An app that runs a model on your own computer. Free and offline, but needs a strong graphics card. |
| **OpenRouter** | A service that gives access to hundreds of cloud models, including free ones (their name ends with `:free`). |
| **API and API key** | The address of a model service and the "password" for it. The key lives in a Windows user variable, not in project files. |
| **Test** | A tiny program that checks a function works correctly. Green = passed, red = failed. |
| **Skeleton, blank** | Code with function names and descriptions but without the "insides". |
| **Contracts** | What each part of the program promises the others: functions, their inputs and outputs, shared types, database schema. |
| **Attempt** | One model run for one job. A rework or a Bug Fixer handoff is a new attempt. |
| **File copy** | A separate folder where an executor works without touching the main project. |
| **Tokens** | Pieces of text a model reads and writes. They show how much work each model did. |
| **Dashboard** | A browser page showing how the task is going. It opens by itself. |

---

## 3. What to install

| What | Why | How to check |
| --- | --- | --- |
| OpenCode Desktop 2.x | the app where the agents live | the OpenCode window opens |
| Python 3.13.16 with Tk | prepared automatically on first launch | no manual installation needed |
| Access to models | free OpenCode models are preselected in the template; LM Studio, OpenRouter or your own API also work | see section 6 |
| Tools for your language | for the example below: JDK 21 and Maven | `java -version`, `mvn -v` |

> The kit prepares its own private Python and preserves system installations.
> Commands below use `kit\python.cmd` on Windows; on Ubuntu/Debian/Mint replace it
> with `sh kit/python.sh`. Regular users do not need to enter these commands.
> macOS still requires a manual installation of Python with Tk.

---

## 4. Path A: the setup wizard (recommended)

![Installation in four steps](../../readme_gif/en/01_install.gif)

Here is how it looks in the wizard itself:

![The setup wizard](../../readme_gif/en/01_install_live.gif)

1. On the [repository page](https://github.com/polar-byter/opencode-environmental-tune)
   click **Code → Download ZIP** and fully extract the archive into a separate folder.
2. Double-click **install.cmd**. The "Project setup" wizard opens.
3. **Step 1** — the wizard finds OpenCode Desktop itself. If not, click
   "Download OpenCode", install it and then "Check again".
4. **Step 2** — choose a folder for your application or type a new path, for example
   `D:\Projects\my-home-app`. Missing folders are created. A folder outside the
   downloaded kit is best. If the folder already contains your code, conflicting kit
   settings are never overwritten — the wizard explains the problem.
5. **Step 3** — "Create project and configure models". The wizard copies the kit and
   opens the model settings. A starting choice is already there: the Master Chief and
   Bug Fixer use DeepSeek V4.1 Flash Free, executors use MiMo V2.6 Flash Free, one at
   a time. Click "Save settings", then "Prepare OpenCode", and wait for success.
6. **Step 4** — the wizard launches Desktop with a request to open the project folder.
   Check the project name in Desktop: if a different one opened, click "Copy folder
   path" in the wizard, choose **Open Project** in Desktop and paste the path.
7. Copy the example prompt from the wizard, adjust it if you like, paste it into a
   **new build chat** and send it. The wizard never sends anything to a model itself.

Free model availability changes: if a model is unavailable, pick another one in the
settings window (section 6). A screen-by-screen guide to the wizard:
[OPENCODE_KIT.en.md](OPENCODE_KIT.en.md).

---

## 5. Path B: add the kit to your project by hand

If you already have a project and do not need the wizard, you can copy the kit by hand.
The example below is a Java project from [start.spring.io](https://start.spring.io)
(Maven, Java 21, dependencies `Spring Web` and `Validation`) extracted to `D:\PROJECTS\task-api`.

**Copy four things from this repository into the project root:**

```
opencode.jsonc        ← which agents exist and what they may do
AGENTS.md             ← the Master Chief's working rules
kit/                  ← kit scripts (tracking, controller, dashboard, model settings)
.opencode/commands/   ← optional /plan-project and /module commands
```

Add these lines to the project `.gitignore` so personal settings and journals stay out of Git:

```gitignore
.opencode/opencode.jsonc
.opencode/opencode.jsonc.tmp
.opencode/kit-models.json
.metrics/
```

**Tell the kit about your project in `AGENTS.md`.** Only the sections marked `# EDIT` change.

`Project stack` — the language and, most importantly, the test command:

```md
## Project stack  # EDIT: language, build tool, test command
- Language: Java 21 (`java -version`). Build tool: Maven (`mvn`).
- Tests: JUnit 5. Maven writes one JUnit XML file per test class into `target/surefire-reports`.
- Test command (always through task_metrics):
  `kit\python.cmd kit/task_metrics.py test --task <ID> --junit-dir target/surefire-reports -- mvn -q test`
- Compile only: `mvn -q compile`.
- Run the app: `mvn spring-boot:run`.
```

`Project layout` — where the code and tests live:

```md
## Project layout  # EDIT: folders and files of this project
- `src/main/java/com/example/taskapi/` — application code.
- `src/test/java/com/example/taskapi/` — tests.
- `pom.xml` — Maven build file.
```

`Work plan (memory)` — the plan file name, `currentsteps.md` by default. With Obsidian
the plan lives in your vault; without it, in the project root.

Ready-made test commands for other languages are in
[Adding your language](../../README.en.md#adding-your-language).

**Check that the kit can read test results.** Run this once in the project root:

```bash
kit\python.cmd kit/task_metrics.py check --junit-dir target/surefire-reports -- mvn -q test
```

- `CHECK OK` — all good. Failing tests do not matter at this step.
- `CHECK FAILED` — the script cannot read the result; hints follow below the line.

The Master Chief also runs this check before every task and writes no code until it
passes. The model settings window runs with `kit\python.cmd -m kit.configurator.app` from the
project root (or ask the Master Chief to open it).

---

## 6. Models, number of executors and limits

![Models, limits and keys](../../readme_gif/en/07_models.gif)

The "Project models" window opens from the setup wizard, the **Model settings** button
in the dashboard, or when you ask the Master Chief. At the top there are four sections:
**Master Chief**, **Executors**, **Bug Fixer** and **OpenRouter** (a catalog with prices).

**Where the model comes from** — each role has its own choice:

| Role | Source options |
| --- | --- |
| Master Chief | "Project defaults", "Model from OpenCode", "Own API" |
| Executors | "Local · LM Studio", "Model from OpenCode", "Own API" |
| Bug Fixer | "Disabled", "Model from OpenCode", "Own API" |

- **Model from OpenCode** — models OpenCode already knows: free models of the OpenCode
  catalog and anything connected with `/connect` (OpenCode Go, a ChatGPT subscription,
  OpenRouter and more).
- **Local · LM Studio** — executors only. Load a model in LM Studio (the **Load**
  button) and start the server (**Developer → Start Server**). You choose the load
  settings: the kit never loads or unloads models itself.
- **Own API** — any OpenAI-compatible service: an address like `https://api.example.com/v1`
  (without `/chat/completions` or `/models`), a key and the exact model ID.
  "Get models" fetches the list.

**How many executors and which limits.** In the Executors section:

| Field | Default | Meaning |
| --- | --- | --- |
| Concurrent executors | 2 | 1 = one after another; 2–8 = in parallel, but only for independent parts |
| Steps per attempt | 24 | how many actions a model may take in one attempt |
| Seconds per attempt | 600 | how much time one attempt gets |
| Executor failures per work item | 3 | executor code-repair budget |
| Bug Fixer failures per work item | 6 | corrections stay with the Bug Fixer |
| Total code failures per work item | 9 | combined limit; API and setup interruptions are excluded |
| Repeated actions without progress | 3 | how many identical actions without a result are allowed |

This is a maximum: with fewer parts, or parts that depend on each other, fewer executors run. A part that depends
on another part not yet accepted waits its turn. Provider account limits are shared by
all executors.

**Bug Fixer** — its own source and limits (32 steps and 600 seconds by default).
Choose "Disabled" to have no Bug Fixer at all.

**OpenRouter catalog.** The list loads without a key; prices are in US dollars per 1M
tokens, input and output separately. Turn on "For coding", "Tool support only" (agents
cannot work without tools) and, if you like, "Free models". In "Assign to:" pick a role
and click a row: the role gets "Own API", the address `https://openrouter.ai/api/v1`
and the exact model ID. The click saves nothing yet.

**Keys.** The key lives in a Windows user variable; the project stores only its name.
If a key is already saved, the window shows **Key found** and you need not type it
again. One `OPENROUTER_API_KEY` works for every role. **Check connection** tells you
whether the service answers; no generation runs and nothing is saved.

**Save and apply.** "Save settings" writes the choice to `.opencode/kit-models.json`
for this folder. "Prepare OpenCode" builds the overlay file `.opencode/opencode.jsonc`.
The current chat does not switch models — open a **new build chat**. If you just added
a new key, fully restart OpenCode Desktop.

> Parallel executors and the watchdog run in the shared OpenCode Desktop service. If
> you launch OpenCode separately (`kit\python.cmd kit/run_opencode.py` in the private `--standalone`
> mode), the kit keeps the earlier sequential protocol.

The configurator follows the system language (English or Russian) until you choose one
with Language. More: [configurator guide](../../kit/configurator/UX.ru.md),
[LOCAL_MODELS.ru.md](LOCAL_MODELS.ru.md), [how executors and metrics work](../kit/EXECUTION_GUIDE.ru.md)
(all in Russian).

---

## 7. Give the task

Open the project folder in OpenCode and create a new **build** chat. There are two
equal ways:

**Way A — straight in chat.** Just describe what you need:

```text
Create a local to-do application. I need to add tasks, choose a due date,
mark them complete and filter by status. Keep data between restarts.
Choose a simple stack, use SQLite for storage, and include a clear launch file.
Design a readable interface. Follow the kit rules, create the plan and tests,
delegate implementation to the configured workers and complete the whole plan.
Show the final test results and explain how to run the application.
```

**Way B — with a `TASK.md` file.** Write the requirements and acceptance criteria in
`TASK.md` in the project root, save it and send one word in chat: **"Start"**.

A few rules:

- If chat and file disagree, the chat message wins.
- The Master Chief never overwrites `TASK.md` unless you ask.
- You do not need to list documents: it finds `AGENTS.md`, the plan and README itself.
- Opening the folder alone starts nothing; a chat message does.

The Master Chief opens task tracking and launches the dashboard in your browser, then
shows the plan: which parts the task splits into and in what order. Check the plan
matches your task and reply, for example: "The plan looks good. Implement the whole
plan, verify it, and show task statistics."

---

## 8. Watch the work in the dashboard

![The dashboard](../../readme_gif/en/08_dashboard.gif)

While you do other things, the dashboard shows:

- **Working now** — every participant: which executor or Bug Fixer works on which
  function, how much is done, tokens and time used.
- **Overview** — task status, rework requests, test runs, executor failures and the
  latest events. Refreshes every 2 seconds.
- **Work details** — every attempt of each job: who did it, how it ended, whether the
  changes were integrated.
- **Tokens** — usage per model and per attempt. If some messages have no data, the sum
  is marked "≥" and zero is never substituted.

The page language follows the browser (English or Russian); the **Language** switch
remembers your choice for the project.

Task control buttons:

| Button | What happens |
| --- | --- |
| **⏸ Pause** | The Master Chief and all executors stop. Code, plan and history are kept. New actions for the task are blocked until you resume. |
| **▶ Resume** | The Master Chief is asked to continue the same task: re-read the plan and check what was done before the pause. Loop guards are not reset. |
| **■ Cancel** | The task is cancelled and message queues are cleared. This is not a "successful finish". |
| **Delete task…** | After confirmation, this task's sessions and journal are deleted. Your application code stays. |
| **Model settings** | Opens the model selection window. Nothing applies by itself; the choice is for the next task. |

Details and limits: [task controls](../../kit/dashboard/CONTROLS.ru.md) (in Russian).

---

## 9. What the Master Chief does after you approve the plan

From here it runs on its own, part by part:

1. Creates a function **skeleton** with a description and a placeholder, for example:
   ```java
   public Task create(String title) {
       throw new UnsupportedOperationException("TODO: executor");
   }
   ```
2. Writes the **tests** and runs them — they fail for now.
3. Gives an **executor** one small complete class. With more than one executor selected
   and independent parts, it hands them out in parallel — each in its own file copy.
4. The executor fills in **only the function bodies**; the watchdog tracks its steps and time.
5. The Master Chief checks nothing else was touched, matches requirements against code
   and runs the tests of that very copy. A mistake means a rework; after a code bug or
   a limit — a bounded Bug Fixer correction. A build or setup problem the Master Chief fixes
   itself or brings to you.
6. The accepted file is integrated into the main project, the part is ticked off in
   the plan and the Master Chief takes the next one.
7. A guard fires (`STOP`) — it explains why and waits for your decision: clarify the
   job, fix the tests, the setup or the model.

It comes to you only when access or tools are missing, or a decision would change the
task. Moving between parts needs no further approval.

---

## 10. Get the result

![The finish](../../readme_gif/en/06_final.gif)

When every part is accepted and integrated, the UI/UX improvement stage begins. The
Master Chief runs the application and walks through normal scenarios: opens forms,
fills them in, saves, checks error messages. It notes what is inconvenient and fixes
the interface — logic and contracts stay the same. The outcome is recorded in the
journal, and the task cannot be finished without that record. The report shows "UI/UX
improvement stage completed…", "…skipped due to …" (for example, no browser) or
"…not required" (the application has no interface).

Then it always runs **all** project tests and shows the outcome and statistics:

- how long the task took;
- tokens of paid models, local ones (LM Studio) and free cloud ones
  (`:free` on OpenRouter, `-free` on OpenCode);
- usage per executor and Bug Fixer attempt — included in the total;
- how many times work was sent back and how many test runs passed.

The dashboard shows a **✓ Work completed** block with buttons to open the project
folder, view the launch file and the final report.

To try the application for real, ask:

```text
Start the application and check the main scenarios. Show the results
and explain how to stop the application.
```

---

## 11. Continuing after a break

The Master Chief writes what is done, the decisions and the next steps into
`currentsteps.md`. In a new chat just say:

> Read the project plan and continue with the next task.

---

## 12. Troubleshooting

| What you see | Why | What to do |
| --- | --- | --- |
| Python preparation failed | No internet, insufficient disk space or a corrupt download | Read the launch-window error, correct the cause and retry; do not install another Python version |
| Desktop opened a different folder | Not every Desktop version selects a folder from the link | "Copy folder path" in the wizard → **Open Project** in Desktop |
| The selected model is unavailable | Free models and limits change | Pick another model in the settings, "Prepare OpenCode", new chat |
| Work stalls, the report shows a rate limit / `429` | Provider limit (free OpenRouter models have a daily one) | Wait or choose another model; the Bug Fixer is not started for this |
| Executors do not run in parallel | 1 executor selected, parts depend on each other, or OpenCode runs in private mode | Check the number in the settings; parallel work needs the shared Desktop service |
| `Result: test failed` in `check_env` | LM Studio is not running or no model is loaded | Developer → Start Server; press Load on the model |
| No "Key found" although you saved a key | OpenCode or the window started before the key was saved | Restart OpenCode Desktop and reopen the settings window |
| The chat still uses the old model | The current chat never switches | "Prepare OpenCode", then a new build chat |
| `/module` not visible | `.opencode/` not copied, or OpenCode opened outside the project root | Check the project folder |
| OpenCode rejects `providers`/`agents` | An old OpenCode from PATH is running | See [Which OpenCode the kit uses](../../README.en.md#which-opencode-the-kit-uses) |
| Tests do not compile | An import is missing in the skeleton (executors never add imports) | Tell the Master Chief: "add the missing import to the skeleton" |
| `CHECK FAILED` | The script cannot read test results | Read the hints; check the test command in `AGENTS.md` |
| The Master Chief writes `STOP` and waits | A loop guard fired or the Bug Fixer failed | Read the reason, decide, and tell it to continue |
| The Master Chief does everything itself | It cannot see `AGENTS.md` | Make sure `AGENTS.md` is in the project root |

---

## 13. Next steps

- [README.en.md](../../README.en.md) — project overview, statistics, other languages.
- [OPENCODE_KIT.en.md](OPENCODE_KIT.en.md) — the setup wizard screen by screen.
- [docs/kit/EXECUTION_GUIDE.ru.md](../kit/EXECUTION_GUIDE.ru.md) — how executors, the Bug Fixer and metrics work, with a map of modules and functions (Russian).
- [PIPELINE.ru.md](../kit/PIPELINE.ru.md) — exactly how executor work is checked (Russian).
- [METRICS.ru.md](../kit/METRICS.ru.md) — how statistics are counted (Russian).
- [kit/prompts/README.ru.md](../../kit/prompts/README.ru.md) — the role prompts.

After the one-time setup you simply describe the task and approve the plan.
The Master Chief manages the order of work, the executors, the checks and the statistics.
