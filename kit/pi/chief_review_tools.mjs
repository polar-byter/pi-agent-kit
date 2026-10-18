/** Give the Chief a real browser and read-only access to the completed report. */
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

export function registerChiefReviewTools(pi, projectRoot, state, options) {
  if (!pi.registerTool) return;
  const emptyParameters = { type: 'object', properties: {}, additionalProperties: false };
  async function runModule(module, arguments_, signal) {
    if (!options.pythonExecutable) throw new Error('Restart this project with its updated start.cmd');
    const result = await pi.exec(options.pythonExecutable,
      ['-B', '-m', module, '--root', projectRoot, '--task', state.task, ...arguments_],
      { cwd: projectRoot, timeout: 690000, signal });
    if (result.code !== 0) throw new Error((result.stdout + '\n' + result.stderr).slice(-3000));
    return result.stdout;
  }
  pi.registerTool({
    name: 'kit_task_report', label: 'Task report',
    description: 'Read the frozen final task report, tokens and known costs after finish. Never starts work or recollects usage.',
    parameters: emptyParameters,
    async execute(_id, _parameters, signal) {
      const text = await runModule('kit.task_report', [], signal);
      return { content: [{ type: 'text', text }], details: { task: state.task } };
    },
  });
  pi.registerTool({
    name: 'kit_browser', label: 'Browser review',
    description: 'Control a real isolated browser for this task. open/goto use the local application URL; snapshot gives element refs; click/fill/press act on the page. screenshot returns a PNG and browser_evidence receipt for ux-review. HTTP requests or mocked DOM do not replace this review. If image input is unavailable, report the visual review as skipped.',
    parameters: { type: 'object', properties: {
      action: { type: 'string', enum: ['open', 'goto', 'click', 'fill', 'type', 'press', 'keydown', 'keyup', 'snapshot', 'screenshot', 'resize', 'console', 'eval', 'close'] },
      arguments: { type: 'array', items: { type: 'string' } },
    }, required: ['action'], additionalProperties: false },
    async execute(_id, parameters, signal, _update, context) {
      const text = await runModule('kit.browser_review', [parameters.action, ...(parameters.arguments || [])], signal);
      const result = JSON.parse(text);
      const content = [{ type: 'text', text }];
      if (result.screenshot && context.model?.input?.includes('image')) {
        content.push({ type: 'image', mimeType: 'image/png', data: (await readFile(join(projectRoot, result.screenshot))).toString('base64') });
      } else if (result.screenshot) {
        content.push({ type: 'text', text: 'This model does not advertise image input. The browser ran, but a pixel review is not confirmed. Record visual UX as skipped unless a human or an explicitly selected vision model inspects the screenshot.' });
      }
      return { content, details: result };
    },
  });
}
