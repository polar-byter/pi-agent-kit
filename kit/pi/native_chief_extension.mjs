/** Journal admission and lifecycle rules around the native Pi editor. */
import { callBroker } from './native_chief_control.mjs';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

export function createChiefExtension(projectRoot, state, options) {
  return pi => {
    const parameters = () => ({ sessionID: state.identifier });
    async function checkWork(context) {
      try {
        await callBroker(projectRoot, 'task.workAllowed', parameters());
        const configuration = JSON.parse(await readFile(join(projectRoot, '.pi/kit-runtime.json'), 'utf8'));
        const approved = configuration.roles.build;
        if (state.session.model?.provider !== approved.provider || state.session.model?.id !== approved.model) {
          throw new Error('Модель Чифа отличается от подготовленных настроек. Приостанови задачу, сохрани и подготовь выбор в конфигураторе.');
        }
        return true;
      } catch (error) {
        context.ui.notify(String(error.message), 'warning');
        return false;
      }
    }
    pi.on('session_start', async (_event, context) => {
      state.context = context;
      context.ui.setStatus('pi-kit', 'Pi Kit · ' + state.task);
      await callBroker(projectRoot, 'task.dashboard', parameters(), { open_browser: !options.noBrowser });
    });
    pi.on('input', async (_event, context) => {
      if (!await checkWork(context)) return { action: 'handled' };
      return { action: 'continue' };
    });
    pi.on('before_agent_start', async (event, context) => {
      if (!await checkWork(context)) { context.abort(); return; }
      const taskContext = `Managed Pi kit task: ${state.task}. Exact Chief session: ${state.identifier}. `
        + 'The journal already exists with tracked delegations. Never start a second journal for this task. '
        + 'For a development request, follow AGENTS.md and the saved plan through controlled delegation, '
        + 'inspection, tests, review and integration. Record finish only after the complete accepted workflow. '
        + 'For an ordinary question, answer the question directly; that answer does not finish a development task.';
      return { systemPrompt: event.systemPrompt + '\n\n' + taskContext };
    });
    pi.on('tool_call', async (_event, context) => {
      if (!await checkWork(context)) return { block: true, reason: 'The kit has blocked work on this task' };
    });
    pi.on('agent_start', () => { state.settled = false; });
    pi.on('agent_settled', () => {
      state.settled = true;
      void callBroker(projectRoot, 'task.status', parameters()).then(status => {
        if (!status.finished) state.context?.ui.notify('Ход Чифа завершён. Задача ещё не принята: записи finish нет.', 'warning');
      }).catch(() => state.context?.ui.notify('The kit could not read the final task status. Inspect its dashboard.', 'warning'));
    });
    async function allowSessionChange(_event, context) {
      try { await callBroker(projectRoot, 'task.canSwitch', parameters()); }
      catch (error) { context.ui.notify(error.message, 'warning'); return { cancel: true }; }
    }
    pi.on('session_before_switch', allowSessionChange);
    pi.on('session_before_fork', allowSessionChange);
    pi.on('session_before_tree', allowSessionChange);
    pi.on('session_shutdown', async event => {
      if (state.removing) return;
      if (event.reason === 'quit') {
        try {
          const status = await callBroker(projectRoot, 'task.status', parameters());
          const current = await callBroker(projectRoot, 'task.controlState', parameters());
          if (!status.finished && !['paused', 'cancelled'].includes(current.status)) {
            await callBroker(projectRoot, 'task.control', parameters(), { action: 'pause' });
            let pauseConfirmed = false;
            for (let count = 0; count < 200; count += 1) {
              const controls = await callBroker(projectRoot, 'task.controlState', parameters());
              if (controls.status === 'paused') { pauseConfirmed = true; break; }
              if (controls.status === 'error') throw new Error('Pause was not confirmed');
              await new Promise(resolve => setTimeout(resolve, 100));
            }
            if (!pauseConfirmed) throw new Error('Task pause is still unconfirmed');
          }
        } catch { return; }
      }
      await callBroker(projectRoot, 'session.detachInteractive', parameters());
    });
    for (const [name, action] of [['kit-pause', 'pause'], ['kit-resume', 'resume'], ['kit-cancel', 'cancel']]) {
      pi.registerCommand(name, { description: action + ' the whole kit task', handler: async (_text, context) => {
        try { await callBroker(projectRoot, 'task.control', parameters(), { action }); }
        catch (error) { context.ui.notify(error.message, 'error'); }
      } });
    }
    pi.registerCommand('kit-status', { description: 'Show the kit task and conversation identifiers', handler: async (_text, context) => {
      const status = await callBroker(projectRoot, 'task.status', parameters());
      context.ui.notify(`Задача: ${state.task}\nСессия: ${state.identifier}\nЗавершена: ${status.finished ? 'да' : 'нет'}`, 'info');
    } });
    pi.registerCommand('kit-dashboard', { description: 'Open this task dashboard', handler: async () => {
      await callBroker(projectRoot, 'task.dashboard', parameters(), { open_browser: true });
    } });
  };
}
