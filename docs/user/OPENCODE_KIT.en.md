> Материал исходной версии OpenCode. Сохранён для изучения общего кита и истории.
> Для текущей адаптации используй [быстрый старт Pi](../user/PI_QUICKSTART.ru.md)
> и [карту адаптеров](../kit/PI_ADAPTERS.ru.md). Команды OpenCode здесь не являются командами Pi.

# Your first OpenCode Kit project

To change models or API during a task: **Pause → Model settings → Save → Prepare
OpenCode → Resume**. The same task, session, accepted work and usage history are
preserved. A provider quota/rate-limit error automatically pauses the task and
shows a warning. Failed preparation keeps the task paused. See the
[architecture and detailed guide (Russian)](LIVE_MODELS.ru.md).

The kit coordinates a Chief (architecture and review), executors (implementation),
and an optional Bug Fixer with its own correction budget. Its dashboard shows progress,
tests and token usage. A token is a unit of text counted by a model.

## Windows setup

![The setup wizard](../../readme_gif/en/01_install_live.gif)

1. Install **OpenCode Desktop for Windows** from the [official download page](https://opencode.ai/download). Use Desktop 2.x. Installing only the terminal CLI does not install Desktop.
2. No manual Python installation is needed. On first launch the kit downloads and verifies pinned **Python 3.13.16**, including Tk, from python.org. Internet access is required; other Python installations are preserved.
3. On the [kit repository page](https://github.com/polar-byter/opencode-environmental-tune), choose **Code → Download ZIP**, then extract the entire archive. Do not run the installer inside the ZIP.
4. Double-click **install.cmd** in the extracted folder. Wait for Python preparation, then the graphical wizard opens. Subsequent launches reuse the private runtime.
5. The wizard finds Desktop. Otherwise click **Download OpenCode**, install it, then **Check again**. For a custom installation, choose its `OpenCode.exe` using **Choose application…**.
6. Enter a separate project folder, for example `D:\Projects\my-home-app`. Missing folders are created automatically. Keep it outside the downloaded kit. Existing application code is preserved; conflicting kit/configuration files are rejected with an explanation.
7. Click **Create project and configure models**. The kit is copied and the model configurator opens.

## Models and API credentials

| Role | Responsibility | Template default |
|---|---|---|
| Master Chief | Architecture, assignments, review and tests | OpenCode DeepSeek V4.1 Flash Free |
| Executor | A small implementation assignment | OpenCode MiMo V2.6 Flash Free |
| Bug Fixer | One correction after a defect or execution limit | OpenCode DeepSeek V4.1 Flash Free |

Model availability can change; choose an available alternative if needed. Start
with **1 executor**. Setting **2** allows independent assignments in isolated file
copies, with reviewed integration by the Chief.

For each role select **OpenCode**, **LM Studio**, or **API**. Connect any required
provider in OpenCode first. For LM Studio, load a model and start its server. For an
OpenAI-compatible API, enter the base URL, exact model ID and your API key. The key
is a secret credential: keep it out of chat and Git. The project stores an
environment-variable reference instead of the key itself.

Use the connection check, then **Save** and **Prepare OpenCode**. Saving records
your selection; preparation generates the configuration for a new OpenCode session.
Wait for success. Correct any reported URL, credential or model error before
continuing. Fully restart Desktop after adding a new environment API key.

## Open the project and send a task

After preparation the wizard launches Desktop with a request to open your folder.
Some Desktop versions do not select the folder from that link. Check the project
name. If needed, click **Copy folder path**, choose **Open Project** in Desktop and
paste the path. Starting Desktop does not itself prove the correct folder opened.

Create a **new chat** in that project, select agent **build**, paste your task and
send it. The wizard offers an editable example and **Copy prompt**; it never sends
a prompt automatically. A prompt is simply a written instruction to a model.

```text
Create a local application for household tasks and a daily schedule.
Include tasks with due dates and completion status, and a day table with visible
start time, end time and activity columns. Allow adding, editing and deleting
entries, and validate overlapping time intervals. Persist data in SQLite.
Use clear English labels, readable contrast and straightforward navigation.
Follow the kit rules. Design the architecture, write the plan in currentsteps.md,
prepare tests, delegate implementation to the configured workers and finish the plan.
Run module tests and the full test suite, then review the interface for usability.
Provide a launch file and explain how to use the application.
```

`TASK.md` is optional when the chat contains the requirements. The Chief registers
the task and opens the dashboard. Answer questions in the OpenCode chat. Accepted
work and successful full tests provide readiness evidence.

## Installed files

| Path | Purpose |
|---|---|
| `AGENTS.md` | Agent rules; the project-local plan is `currentsteps.md` |
| `opencode.jsonc`, `.opencode/commands/` | OpenCode setup and commands |
| `kit/` | Model configurator, execution controller, metrics and dashboard |
| `.opencode/kit-models.json` | Saved model choices, without API keys |
| `.opencode/opencode.jsonc` | Configuration generated by preparation |
| `.metrics/` | Local task journals and interface settings |
| `docs/user/` | User guides, including this one (EN/RU) |
| `docs/kit/` | How the kit works: metrics, review, executors |

System locale selects English/Russian initially; use the language selector to
change it. Your task controls the language of model-generated text. Re-running
the wizard for its existing project reopens settings without upgrading the kit or
replacing application code and model choices.

For Ubuntu/Debian/Mint, open **opencode-kit_0.2.0_all.deb** with your graphical
package manager and click Install. Then launch **OpenCode Kit** from the application
menu. First launch prepares private Python 3.13.16 with Tk; the system Python is preserved. No terminal commands are needed in
the normal setup flow. The **Linux installer** GitHub Actions workflow also produces
the **opencode-kit-linux-deb** artifact. See [Linux setup details](LINUX_INSTALL.ru.md).
On macOS the current entry point remains `python3 install.py`, requiring Python and Tk.
