# Project instructions

This project uses Pi Agent Kit. Read the task, the project source and currentsteps.md before choosing the next step. The kit keeps the journal, tests, review evidence and execution controls. Pi runs the Chief and the workers.

## Task intake

Accept requirements from the user's message or an existing TASK.md. The current explicit message takes precedence. Read the documents yourself and keep the accepted scope and work plan in currentsteps.md in this project root. A task already described in chat does not require TASK.md.

The native Pi integration supplies the exact task ID and Chief session ID in system context. Its journal already exists. Keep those identities and never call start a second time. If a session was started outside the managed launcher, explain that dashboard control requires the managed entry point rather than attaching a second writer to its history.

## Chief and workers

The Chief plans the architecture, fixes the interfaces, writes skeletons and tests, and reviews returned work. An executor implements the bodies of one cohesive source file. The Bug Fixer continues rejected implementation within its recorded budget.

Before implementation:

1. Read the chosen models and execution limits. Never replace a model because another one seems more convenient.
2. Write the applicable shared contracts and the dependencies between work items.
3. Create signatures, imports, detailed spec comments and placeholder bodies.
4. Write requirement and edge-case tests against the skeleton.
5. Publish ARCHITECTURE.md and the function registry with kit.dashboard.tracking.
6. Save a JSON list of requirements in .metrics/<task>/<item>-requirements.json.

Run independent ready work items through the controller. It creates one private copy and one restricted Pi session for each attempt. The default has two slots; the user's saved value takes precedence.

```text
kit\python.cmd -m kit.execution_controller --task <task> launch --work-item <item> --file <source> --requirements .metrics/<task>/<item>-requirements.json --contracts <shared-contract>
```

Add --dependencies for already accepted and integrated prerequisites. A work item with no dependencies can run alone. Every overlapping attempt must name its applicable shared contracts. Do not run a separate worker for an attempt already launched by the controller.

Workers may read their own copy and edit only the assigned source and progress file. They may not run a shell, change tests, signatures or imports, or create nested agents. Missing imports and incorrect tests go back to the Chief as concrete findings.

Do not edit contracts, tests or the plan while dependent workers are running. The controller and its watcher own stopping and timeout classification. A worker's claimed completion is provisional.

## Review and integration

Before inspecting, require attempt_end with stopped=true for the exact attempt. An unconfirmed stop blocks both inspection and replacement.

Immediately after return, inspect before any reviewer edit or test:

```text
kit\python.cmd kit/task_metrics.py inspect --task <task> --work-item <item>
```

Read the complete returned source. Check every recorded requirement against code and tests. Write a JSON list with requirement, code, test and verified=true for each requirement. An accepted result needs unchanged file boundaries and a green test for that exact attempt and scope:

```text
kit\python.cmd kit/task_metrics.py test --task <task> --attempt <attempt> --scope <item> -- <test command>
kit\python.cmd kit/task_metrics.py review --task <task> --work-item <item> --result accepted --checks .metrics/<task>/<item>-checks.json
kit\python.cmd -m kit.execution_controller --task <task> integrate --attempt <attempt>
```

On a code defect, record rework and launch the Bug Fixer with --role bug_fixer --previous <attempt>. Keep the same requirements and contracts. Further corrections stay with the fixer. Never reset budgets or return to the original executor to evade a limit.

API errors, rate limits, configuration errors, pause and cancellation are infrastructure outcomes. After confirmed interruption they preserve partial code as blocked and do not spend the code-repair budget. Continue the same role with --previous only after the cause has been addressed.

The integration command checks that the original file, contracts and reviewed copy are unchanged. A conflict requires a fresh reviewed attempt. Never overwrite user changes to make an integration succeed.

## Tests and protective stops

Before implementation check that the project's test output is readable with task_metrics.py check. Use unittest output or JUnit XML. A test scope labels the run; the test command itself must select the intended tests.

Test exit codes:

- 0: selected tests passed.
- 1: tests ran and failed; read the failures.
- 2: invalid command or journal; correct the cause.
- 3: protective stop; wait for the user's decision.
- 4: no readable test result, failed build, missing tool or timeout; diagnose the environment.

One initial baseline per scope can record expected red tests before implementation. It does not count as green. Finish requires an unfiltered full run on the integrated project.

A protective stop remains active until the user decides and the Chief records task_metrics.py resume --reason with that decision. A dashboard pause is a different control. Continuing a paused task preserves its protective limits.

## Dashboard controls and model changes

The native Pi integration opens the task dashboard automatically. Use /kit-status to show its task and session IDs; /kit-pause, /kit-resume and /kit-cancel control the whole task. Pi /resume selects a conversation and is distinct from task continuation. The dashboard can pause, continue, cancel and delete the selected task. It addresses the Chief and every worker through the project Pi service.

Pause blocks new admissions and confirms that linked execution stopped. Continue uses the same task and conversation: read the plan and inspect interrupted changes before proceeding. Cancellation is not successful completion. Delete removes confirmed stopped sessions and metrics while preserving application files.

If a control operation is unconfirmed, leave execution blocked. Never create another task ID or start a second process against the same session file to bypass it.

The configurator supports independent Chief, executor and fixer models, own APIs, loaded LM Studio instances, and the OpenRouter catalog. It writes .pi/kit-models.json without raw keys. Settings can be saved as a draft during work. Applying revised models requires a confirmed pause. Preparation records a revision; continuation checks that exact revision and preserves previous attempts as history.

Never load or unload an LM Studio model automatically. Use the exact already loaded instance chosen by the user. A model list or accepted key is not proof that generation or tool use works.

## Completion

Resolve all attempts, integrate accepted files, perform the final UI review where a UI exists, then repeat the full tests after any interface correction.

Before finishing, write .metrics/<task>/progress/result.json with a launcher field
containing the project-relative path to the application's actual launch script.
The dashboard uses this record for its result link. The root start.cmd and
start.sh open the native Pi interface and must never be registered as the application.

```text
kit\python.cmd kit/task_metrics.py ux-review --task <task> --checks .metrics/<task>/ux-checks.json
kit\python.cmd kit/task_metrics.py test --task <task> --scope full -- <full project test command>
kit\python.cmd kit/task_metrics.py finish --task <task>
```

Use --not-applicable for a project with no UI, or --skipped with a concrete reason when interactive review is unavailable. Report the actual outcome. Provide a real launch script and include the recorded final statistics. Unknown tokens and cost remain unknown.

## Source layout and readable code

kit contains the common rules, adapters and their tests. Application source and tests belong in their own project folders. The dashboard uses plain HTML and JavaScript. Runtime adapters must not duplicate acceptance, budget or STOP rules.

Use complete informative function and variable names. Keep intermediate values when they explain a step. Write small functions with a clear responsibility. Comments and docstrings are ordinary English sentences explaining the operation and its reason. User documentation may be Russian.

Generated directories .git, .metrics, .tools, .pi, __pycache__, .venv, node_modules, target, build, dist, bin and obj are outside source snapshots. Put no application source there. Logs, evidence and generated test reports belong in .metrics. Keep source extensions in kit/pi rather than the generated .pi directory.

Use kit\python.cmd on Windows and sh kit/python.sh on Linux. The launcher selects the pinned private Python runtime. Do not install packages into system Python or alter the shared runtime. Application dependencies belong in a separate project virtual environment.
