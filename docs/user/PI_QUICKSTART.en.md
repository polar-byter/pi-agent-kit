# Pi Agent Kit quick start

Keep the checkout in its own directory on a drive with enough free space, such as
`D:\Projects\ActiveProjects\AIProjects\pi-agent-kit`. Run `install.cmd`.
Choose a separate target project directory in the installer. It installs Pi 1.3.0
beside the template, copies the kit to the target and opens its model configurator.
Choose the role connections, save and prepare Pi, then run `start.cmd` in the
target project.

Node.js 22 or newer must be available to the installer. Pi packages and the npm
cache stay in the template’s `.tools` directory; global npm packages are not changed. Python is launched
through `kit\python.cmd`, without modifying system Python. The Windows launchers
default `PI_KIT_RUNTIME_HOME` to their local `.tools\python-runtime`, so keeping
both template and target on D also keeps newly prepared Python files on D.
You can set this variable to a shared directory on D before running setup.

The configurator retains custom API connections, OpenRouter browsing, loaded
LM Studio instances and execution budgets. API keys are stored separately from
project JSON; JSON references environment variable names. An OpenCode model choice
requires an explicit Pi connection. A successful model-list request does not prove
that a model can use all required coding tools.

For a built-in Pi provider, connect it from your target project first:

```powershell
.\start.cmd --authenticate
```

On Linux use `sh start.sh --authenticate`. In the Pi window enter `/login`,
choose a provider, complete its sign-in or enter its key, then leave with `/quit`
or press `Ctrl+C` twice. Run `start.cmd --configure`, refresh the native Pi model
catalog, select the role models, save and prepare the settings.

This command sets `PI_CODING_AGENT_DIR` to the project's `.pi/agent`.
An existing global Pi login is not used. Credentials are stored in
`.pi/agent/auth.json`, excluded from Git and kept on D when the project is on D.
Keep that directory out of published archives. Authentication mode creates no
kit session and disables tools, extensions, MCP, skills, prompt templates and
themes. Use it for `/login`, then return to regular `start.cmd` for tasks.
Custom API connections still use the configurator's address, model and
environment-key fields; this native login step is for the `pi` source.

For one prompt:

```powershell
.\start.cmd --prompt "Read TASK.md and start following the kit rules"
```

This sends a real model request and may consume paid tokens. Installation and
`start.cmd --prepare-only` do not send a task to a model.

| Command | Purpose |
| --- | --- |
| `/sessions` | List project sessions |
| `/pause` | Pause the whole task |
| `/resume` | Resume the current task |
| `/cancel` | Stop the task without accepting its result |
| `/quit` | Close the console while leaving the service available |
| `start.cmd --configure` | Open model settings |
| `start.cmd --authenticate` | Connect a built-in Pi provider in this project |
| `start.cmd --stop-service` | Safely close the project service |

Closing the dashboard browser does not stop the agents. Wait for confirmed pause
before changing role models, save and prepare the new settings, then resume.
Restarting a saved session restores its conversation, not an interrupted network
request. The console belongs to the kit and uses its Pi RPC service; a separately
started Pi TUI does not manage these sessions automatically.

Plain `start.cmd` starts a new task. To reopen an existing conversation, pass
`--session` with the exact ID shown by the earlier `Session:` line or `/sessions`.
Then use `/resume` for a paused task. While the console waits for a response,
use `Ctrl+C` or the dashboard to pause.

Settings are kept under `.pi`, task records and working copies under `.metrics`.
Installed projects reference the template’s `.tools/pi` through `.pi/installation.json`;
keep that template directory. Keep these local files out of source publication. Restart
the service after changing environment keys if it still sees the old environment.

See [validation status](../kit/PI_VALIDATION.ru.md) for checks actually performed.
