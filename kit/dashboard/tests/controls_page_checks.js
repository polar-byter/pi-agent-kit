// Exercise the actual page handlers with deterministic responses and task switches.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const elements = new Map(input.ids.map(id => [id, {
  textContent: '', hidden: false, disabled: false, value: '', className: '',
  replaceChildren() {}, add() {}, addEventListener() {}, querySelectorAll() { return []; }
}]));
const context = {
  document: {getElementById: id => {assert(elements.has(id), id); return elements.get(id);}},
  window: {location: {search:'?task=first'}, history: {replaceState() {}}, confirm: () => true},
  URLSearchParams, Option: function() {}, setInterval() {}, console,
  KitLocalization: require('../static/localization.js'),
  refreshCount: 0, requests: []
};
vm.createContext(context);
vm.runInContext(input.source.replace(/\s*main\(\);\s*$/, ''), context);
const run = code => vm.runInContext(code, context);
(async () => {
  run(`renderControls({task:'first',session:'ses_root',status:'paused'});`);
  assert.equal(elements.get('resume-task').disabled, false);
  assert.equal(elements.get('pause-task').disabled, true);
  run(`renderControls({task:'first',session:'ses_root',status:'running'});`);
  assert.equal(elements.get('pause-task').disabled, false);
  run(`renderControls({task:'first',session:'ses_root',status:'pausing'});`);
  for (const action of ['pause','resume','cancel','delete']) assert(elements.get(action+'-task').disabled);
  run(`renderControls({task:'first',status:'running'});`);
  assert(elements.get('pause-task').disabled);
  context.fetch = async (url, options) => {
    context.requests.push({url, options});
    return {ok:true,json:async()=>url==='/api/ui'?{token:'ui-token'}:{status:'pausing'}};
  };
  const refresh = run('refreshTask');
  run(`refreshTask=async()=>{refreshCount++};renderControls({task:'first',session:'ses_root',status:'running'});`);
  await run(`controlTask('pause')`);
  const posted = context.requests.find(request=>request.options?.method==='POST');
  assert.equal(posted.url,'/api/task/control');
  assert.deepEqual(JSON.parse(posted.options.body),{task:'first',action:'pause'});
  assert.equal(posted.options.headers['X-Dashboard-UI-Token'],'ui-token');
  context.requests=[];context.window.confirm=()=>false;
  await run(`controlTask('delete')`);
  assert.equal(context.requests.length,0);
  context.window.confirm=()=>true;
  context.fetch=async url=>({ok:url==='/api/ui',statusText:'Failed',json:async()=>url==='/api/ui'?{token:'ui-token'}:{error:'Not confirmed'}});
  await run(`controlTask('cancel')`);
  assert.equal(elements.get('control-message').textContent,'Not confirmed');
  run('renderControls(selectedData)');
  assert.equal(elements.get('control-message').textContent,'Not confirmed');
  let release;
  context.fetch=async url=>url==='/api/ui'?{ok:true,json:async()=>({token:'ui-token'})}:
    new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({status:'cancelled'})});});
  const pending=run(`controlTask('cancel')`);
  await new Promise(resolve=>setImmediate(resolve));
  run(`activeTask='second';controlFailure='';renderControls({task:'second',session:'ses_second',status:'running'});`);
  release();await pending;
  assert.equal(run('selectedData.task'),'second');
  assert.equal(elements.get('control-message').textContent,'');
  context.fetch=async url=>({ok:true,json:async()=>url==='/api/health'?{project:{id:'project',name:'test'}}:
    url==='/api/tasks'?[]:{status:'deleted',message:'Deleted'}});
  context.originalRefresh=refresh;
  run(`refreshTask=originalRefresh;activeTask='first';controlFailure='';`);
  elements.get('models').textContent='old model';elements.get('architecture').hidden=false;
  await run('refreshTask()');
  assert.equal(run('activeTask'),'');
  assert.equal(elements.get('models').textContent,'');
  assert(elements.get('architecture').hidden);
  assert.equal(elements.get('title').textContent,'No tasks yet');
  context.document.documentElement = {};
  context.document.querySelectorAll = () => [];
  elements.get('task-select').options = [{value:'first',textContent:'old label'}];
  elements.get('connection').className = 'badge online';
  run(`selectedData=null;latestTasks=[{task:'first',status:'finished',title:'Не переводить'}, {task:'second',status:'running',title:'Other'}];
    localization=KitLocalization.create({'Finished':'Завершена','Connected':'На связи'},'ru');applyLanguage();`);
  assert.equal(elements.get('task-select').options[0].textContent, 'Завершена · Не переводить');
  assert.equal(elements.get('connection').textContent, 'На связи');
  run(`localization.set('en');applyLanguage();`);
  assert.equal(elements.get('task-select').options[0].textContent, 'Finished · Не переводить');
  assert.equal(elements.get('connection').textContent, 'Connected');
  assert.equal(elements.get('ongoing-tasks').textContent, 'In progress: 1');
  const node = () => ({dataset:{}, append() {}, querySelectorAll() {return [];}});
  context.document.createElement = node;
  for (const element of elements.values()) element.append = () => {};
  context.roleCatalog = JSON.parse(fs.readFileSync(require('path').join(__dirname, '../../locales/ru.json'), 'utf8'));
  const now = Date.now() / 1000;
  context.roleData = {task:'first',status:'running',started_at:now-20,work:{
    items:[{id:'db',state:'executor',model:'provider/same-model',attempts:[{at:now-10,state:'executor',role:'bug_fixer',session:'ses_fixer'}]}],
    sessions:{available:true,updated_at:now,current:[
      {role:'executor',session:'ses_fixer',at:now-1,model:'provider/same-model',kind:'thinking'},
      {role:'executor',session:'ses_other',at:now,model:'wrong/concurrent-worker',kind:'thinking'}],
      feed:[{role:'executor',session:'ses_fixer',at:now-1,kind:'text',text:'Own message'},
            {role:'executor',session:'ses_other',at:now,kind:'text',text:'Another worker message'}]}}};
  for (const language of ['en','ru']) {
    run(`localization=KitLocalization.create(roleCatalog, '${language}');`);
    const children = [];
    elements.get('live-tokens').append = child => children.push(child);
    context.roleData.tokens = {available:true, totals:{input:null,output:10}, known:{input:42},
      known_messages:{input:67}, missing_counts:{input:2}, missing_usage:2};
    run('renderWork(roleData)');
    assert.equal(elements.get('live-tokens').textContent, '≥ 42 / 10');
    assert.equal(children.at(-1).textContent, language === 'ru'
      ? 'Неполные данные: сообщений без счётчиков — 2' : 'Incomplete data: messages without counters: 2');
    assert.equal(run("tokenCount({totals:{input:null},known:{input:0},known_messages:{input:0}},'input')"), language === 'ru' ? 'Нет данных' : 'No data');
    assert.equal(run("tokenCount({totals:{input:0}},'input')"), '0');
    assert.equal(run("tokenCount({totals:{input:null},known:{input:0},known_messages:{input:1}},'input')"), '≥ 0');
    for (const role of ['bug_fixer','executor']) {
      for (const state of ['executor','review','accepted','rework','failed']) {
        context.roleData.work.items[0].state = state;
        context.roleData.work.items[0].attempts[0].state = state;
        context.roleData.work.items[0].attempts[0].role = role;
        run('renderWork(roleData)');
        const stage = elements.get('live-stage').textContent;
        assert.equal(stage.includes('Bug Fixer'), role === 'bug_fixer', [language, role, state, stage].join(' '));
        if (state === 'executor') {
          assert(elements.get('live-actor').textContent.startsWith(role === 'bug_fixer' ? 'Bug Fixer:' : language === 'ru' ? 'Исполнитель:' : 'Executor:'));
          assert(!elements.get('live-actor').textContent.includes('wrong/concurrent-worker'));
          assert.equal(elements.get('live-last-message').textContent, (language === 'ru' ? 'Последнее сообщение: ' : 'Last message: ') + 'Own message');
        }
      }
    }
  }
  context.roleData.session = 'ses_root';
  context.roleData.work.items[0].state = 'review';
  context.roleData.work.sessions.models = {master_chief:['old/provider-model','openrouter/new-model']};
  context.roleData.work.sessions.session_models = {ses_root:'openrouter/new-model'};
  run('renderWork(roleData)');
  assert(elements.get('live-actor').textContent.includes('openrouter/new-model'));
  assert(!elements.get('live-actor').textContent.includes('old/provider-model'));
  assert(!elements.get('models').textContent.includes('old/provider-model'));
  assert.equal(context.roleData.work.sessions.models.master_chief.length, 2);
  run("controlPending=false;controlFailure='';renderControls({status:'finished',session:'ses_root',control:{message:'Continuation admitted'}})");
  assert.equal(elements.get('control-message').textContent, '');
  run("renderControls({status:'finished',session:'ses_root',control:{error:'Deletion could not be confirmed'}})");
  assert.equal(elements.get('control-message').textContent, 'Deletion could not be confirmed');
  console.log('Page controls: requests, confirmation, failures, stale replies, empty state OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
