/** Local control for the same AgentSession that the native Pi interface uses. */
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { randomBytes, timingSafeEqual } from 'node:crypto';

export function postLocalJson(port, token, body) {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(body));
    const request = http.request({ hostname: '127.0.0.1', port, path: '/call', method: 'POST',
      agent: false, headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json', 'Content-Length': data.length } }, response => {
      let text = '';
      response.setEncoding('utf8');
      response.on('data', piece => { text += piece; if (text.length > 64 * 1024 * 1024) request.destroy(new Error('Control response is too large')); });
      response.on('end', () => {
        try {
          const result = JSON.parse(text);
          if (response.statusCode !== 200) throw new Error(result.error || 'Kit operation was not confirmed');
          resolve(result);
        } catch (error) { reject(error); }
      });
    });
    request.setTimeout(45000, () => request.destroy(new Error('Kit control timed out')));
    request.on('error', reject);
    request.end(data);
  });
}

export async function callBroker(projectRoot, operation, parameters = {}, data = {}) {
  const connection = JSON.parse(await readFile(join(projectRoot, '.pi/kit-service/connection.json'), 'utf8'));
  if (connection.project !== projectRoot || !Number.isInteger(connection.port) || typeof connection.token !== 'string') {
    throw new Error('Invalid project service identity');
  }
  const response = await postLocalJson(connection.port, connection.token, { operation, params: parameters, data });
  return response.result;
}

export async function createNativeControlServer(state) {
  const token = randomBytes(32).toString('hex');
  const server = http.createServer(async (request, response) => {
    const authorization = Buffer.from(request.headers.authorization || '');
    const expected = Buffer.from('Bearer ' + token);
    if (request.method !== 'POST' || request.url !== '/call' || authorization.length !== expected.length
        || !timingSafeEqual(authorization, expected)) {
      response.writeHead(403).end();
      return;
    }
    try {
      let text = '';
      for await (const piece of request) {
        text += piece;
        if (text.length > 1024 * 1024) throw new Error('Control request is too large');
      }
      const command = JSON.parse(text);
      if (command.session !== state.identifier || !state.session) throw new Error('Native conversation changed');
      const session = state.session;
      let data;
      switch (command.operation) {
        case 'get_state':
          data = { isStreaming: !session.isIdle, isCompacting: session.isCompacting,
            pendingMessageCount: session.pendingMessageCount, settled: state.settled && session.isIdle,
            sessionFile: session.sessionFile, model: session.model ? { provider: session.model.provider, id: session.model.id } : null };
          break;
        case 'get_entries': data = { entries: session.sessionManager.getEntries() }; break;
        case 'clear_queue': data = session.clearQueue(); break;
        case 'abort':
          session.clearQueue();
          await session.abort();
          state.settled = true;
          data = null;
          break;
        case 'prompt':
          if (!session.isIdle || session.pendingMessageCount) throw new Error('Native session is not idle');
          state.settled = false;
          void session.prompt(command.message).catch(() => { state.settled = true; });
          data = { disposition: 'started' };
          break;
        case 'set_model': {
          const model = session.modelRuntime.getModel(command.provider, command.modelId);
          if (!model) throw new Error('The selected model is unavailable');
          await session.setModel(model);
          data = { provider: session.model.provider, id: session.model.id };
          break;
        }
        case 'set_auto_retry': session.setAutoRetryEnabled(command.enabled); data = null; break;
        case 'reload_models': await session.modelRuntime.refresh(); data = { prepared: true }; break;
        case 'shutdown':
          state.removing = true;
          data = null;
          setTimeout(() => state.context?.shutdown(), 20);
          break;
        default: throw new Error('Unsupported native control operation');
      }
      response.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ success: true, data }));
    } catch {
      response.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ success: false }));
    }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  return { server, token, port: server.address().port };
}
