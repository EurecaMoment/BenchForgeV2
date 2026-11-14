export function createPrimitives({React, PLAN_FIELDS, PLAN_SECTIONS}) {
  const h = React.createElement;
  function status(value, t) { return h('span', {className: 'bfw-pill ' + (value || 'unknown')}, t(value || 'unknown')); }
  function button(label, onClick, props = {}) { return h('button', {type: 'button', className: 'bfw-button', onClick, ...props}, label); }
  function card(title, children) { return h('section', {className: 'bfw-card'}, h('h2', null, title), h('div', {className: 'bfw-body'}, children)); }
  function empty(text) { return h('div', {className: 'bfw-empty'}, text); }
  function json(value) { return h('pre', {className: 'bfw-json'}, JSON.stringify(value, null, 2)); }
  const PLAN_TECHNICAL=new Set(['id','objective_id','task_id','run_id','scene_id','scene_design_id','object_ids','object_id','source','target','evidence_directory','previous_attempt','selection_path','source_directory','program_path','path','artifact','revision','evidence']);
  function sceneName(name,index=0) {
    const label=String(name || '');
    if(/[\u4e00-\u9fff]/.test(label))return label;
    const rooms={living_room:'客厅',living:'客厅',dining:'餐厅',storage:'储物间',corridor:'走廊',study:'书房',kitchen:'餐厨',office:'办公室',garden:'花园',yard:'庭院',plaza:'广场',warehouse:'仓库'};
    const matched=Object.keys(rooms).find(key=>new RegExp('(?:^|_)'+key+'(?:_|$)').test(label));
    if(!matched)return /^(?:sf_|[a-f0-9]{12,})/.test(label) ? '场景 '+(index+1) : label.replace(/_/g,' ');
    const version=label.match(/(?:^|_)v(\d+)(?:_|$)/);
    return rooms[matched]+(/probe/.test(label) ? ' · 校准版' : /archive/.test(label) ? ' · 归档版' : '')+(version ? ' · 版本 '+version[1] : '');
  }
  function questionText(text) {
    return String(text || '').replace(/场景「([^」]+)」/g,(match,name)=>{
      const label=sceneName(name);return label.startsWith('场景 ') ? match : '场景「'+label+'」';});
  }
  function planValue(value, edit, path = [], labels = {}) {
    const key = path[path.length - 1];
    if(key==='template_id') return labels[value] || '题型';
    if(key==='stage') return {S1:'计划',S2:'场景',S3:'标注',S4:'题目',S5:'报告'}[value] || value;
    const fixed = ['schema','id','objective_id','template_id','stage','selection_path','selected_scenes','allow_new_scenes'].includes(key);
    const next = fixed ? null : edit;
    if (next && (typeof value === 'number' || (value === null && ['count','seed','target_items','target_scene_count'].includes(key)))) {
      return h('input', {className:'bfw-input bfw-plan-number', type:'number', step:1, min:key === 'seed' ? undefined : 1,
        'aria-label':path.join('.'), 'data-plan-field':path.join('.'), value:value ?? '',
        onChange:(event)=>next(path,event.target.value === '' ? null : Number(event.target.value))});
    }
    if (next && typeof value === 'string') return h('span', {className:'bfw-plan-editable', contentEditable:true,
      suppressContentEditableWarning:true, role:'textbox', 'aria-multiline':true, 'aria-label':path.join('.'),
      'data-plan-field':path.join('.'), onInput:(event)=>next(path,event.currentTarget.textContent)}, value);
    if (value === null || value === undefined || value === '') return h('span', {className: 'bfw-muted'}, '—');
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (Array.isArray(value)) {
      if (!value.length) return h('span', {className: 'bfw-muted'}, '无');
      if (value.every((row) => row && typeof row === 'object' && !Array.isArray(row))) {
        const keys = [...new Set(value.flatMap((row) => Object.keys(row)))].filter((key)=>!PLAN_TECHNICAL.has(key));
        if (keys.length <= 7 && key!=='designs') return table(keys.map((key) => PLAN_FIELDS[key] || key), value.map((row,index) => keys.map((key) => planValue(row[key],next,[...path,index,key],labels))));
        return h('div', {className: 'bfw-plan-records'}, value.map((row, index) => h('div', {key: index}, planValue(row,next,[...path,index],labels))));
      }
      return h('ul', null, value.map((row, index) => h('li', {key: index}, planValue(row,next,[...path,index],labels))));
    }
    if (typeof value === 'object') return h('dl', {className: 'bfw-plan-fields'}, Object.entries(value).filter(([key])=>!PLAN_TECHNICAL.has(key)).map(([key, child]) =>
      h('div', {key}, h('dt', null, PLAN_FIELDS[key] || key), h('dd', null, planValue(child,next,[...path,key],labels)))));
    if(key==='name')return sceneName(value);
    return String(value).replace(/\b(?:C\d{2}|P\d{3})-T\d{2}\b/g,(id)=>labels[id] || id);
  }
  function planMarkdown(plan) {
    const format = (value, depth = 0) => Array.isArray(value) ? value.map((row, index) => '- ' + (typeof row === 'object' ? '\n' : '') + format(row, depth + 1)).join('\n')
      : value && typeof value === 'object' ? Object.entries(value).map(([key, child]) => '  '.repeat(depth) + (PLAN_FIELDS[key] || key) + ': ' +
        (typeof child === 'object' && child !== null ? '\n' + format(child, depth + 1) : child === true ? '是' : child === false ? '否' : child ?? '—')).join('\n') : String(value ?? '—');
    const document = plan.assessment;
    if (typeof plan.user_markdown === 'string') return plan.user_markdown;
    if (!document) return '# ' + (plan.objective || '评测计划') + '\n\n执行摘要\n\n```json\n' + JSON.stringify(plan, null, 2) + '\n```\n';
    return '# ' + document.title + '\n\n' + document.summary + '\n\n' + PLAN_SECTIONS.filter(([key]) => document[key]).map(([key, title]) =>
      '## ' + title + '\n\n' + format(document[key])).join('\n\n') + '\n';
  }
  function planMarkdownView(markdown) {
    const inline = (value) => value.split(/(!?\[[^\]]*\]\([^\s)]+\)|`[^`]+`|\*\*[^*]+\*\*)/g).map((part,index) => {
      const link = part.match(/^(!?)\[([^\]]*)\]\(([^\s)]+)\)$/);
      if (link && /^(?:https?:\/\/|\/[^/]|\.\.?\/)/i.test(link[3])) return link[1]
        ? h('img',{key:index,src:link[3],alt:link[2],loading:'lazy',style:{maxWidth:'100%'}})
        : h('a',{key:index,href:link[3],target:'_blank',rel:'noreferrer'},link[2]);
      if (part.startsWith('`') && part.endsWith('`')) return h('code',{key:index},part.slice(1,-1));
      if (part.startsWith('**') && part.endsWith('**')) return h('strong',{key:index},part.slice(2,-2));
      return part;
    });
    const rows = String(markdown).replace(/\r\n?/g,'\n').split('\n'), blocks=[];
    let index=0;
    const isBlock = (line) => /^(?:#{1,6}\s|```|\s*[-*+]\s|\s*\d+[.)]\s|>\s|\s*$)/.test(line);
    while (index<rows.length) {
      const line=rows[index++];
      if (!line.trim()) continue;
      const heading=line.match(/^(#{1,6})\s+(.+)$/), fence=line.match(/^```([^\s]*)\s*$/);
      if (heading) {blocks.push(h('h'+heading[1].length,{key:blocks.length},inline(heading[2])));continue;}
      if (fence) {
        const code=[];while(index<rows.length && !/^```\s*$/.test(rows[index]))code.push(rows[index++]);index++;
        const content=h('pre',{style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}},h('code',null,code.join('\n')));
        blocks.push(fence[1]==='assessment-yaml' ? h('details',{key:blocks.length},h('summary',null,'可执行计划数据'),content)
          : h('div',{key:blocks.length},content));continue;
      }
      const list=line.match(/^\s*([-*+]|\d+[.)])\s+(.+)$/);
      if (list) {
        const ordered=/^\d/.test(list[1]),items=[list[2]];
        while(index<rows.length) {const next=rows[index].match(/^\s*([-*+]|\d+[.)])\s+(.+)$/);
          if(!next || /^\d/.test(next[1])!==ordered)break;items.push(next[2]);index++;}
        blocks.push(h(ordered?'ol':'ul',{key:blocks.length},items.map((value,item)=>h('li',{key:item},inline(value)))));continue;
      }
      if (/^>\s/.test(line)) {blocks.push(h('blockquote',{key:blocks.length},inline(line.replace(/^>\s/,''))));continue;}
      if (/^\s*(?:---+|\*\*\*+)\s*$/.test(line)) {blocks.push(h('hr',{key:blocks.length}));continue;}
      if (line.includes('|') && index<rows.length && /^\s*\|?\s*:?-{3,}/.test(rows[index])) {
        const cells=(value)=>value.trim().replace(/^\||\|$/g,'').split('|').map(cell=>inline(cell.trim()));
        const headers=cells(line),body=[];index++;
        while(index<rows.length && rows[index].includes('|') && rows[index].trim())body.push(cells(rows[index++]));
        blocks.push(h('div',{key:blocks.length},table(headers,body)));continue;
      }
      const paragraph=[line];while(index<rows.length && !isBlock(rows[index]))paragraph.push(rows[index++]);
      blocks.push(h('p',{key:blocks.length,style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}},inline(paragraph.join('\n'))));
    }
    return h('div',{className:'bfw-plan-markdown-view','data-plan-markdown-view':true},blocks);
  }
  function planEditInstruction(path) {
    return '用户已编辑计划 Markdown，已保存的新版本：'+path+
      '\n必须读取该 Markdown 正文与 edit_revision.base_plan 指向的原计划，逐项落实改动。edit_revision.markdown_normalization=false 时，结构数据已经随显式 YAML 修改保存：保留该版本的 assessment、selections、inputs 和完整 user_markdown，不要求重新生成 markdown_resolution。只有 markdown_normalization=true 时，才将正文改动同步到结构数据并提供 markdown_resolution，格式为 {path, before, after, instruction}；path 为 assessment 相对点路径，before/after 为准确旧新值，instruction 逐字引用正文中新改的原句或已删除的旧句。split 与场景选择保持锁定。'+
      '\n把可执行应用请求保存为 JSON 文件，applies_edit="'+path+'"，使用 pipeline_plan(request_path=文件路径)。旧会话按预设中的计划应用方式提交，重复应用不重开阶段窗口。不要重新输出整份大文档。制作规则的实质修改必须落实到任务代码、执行步骤或证据输入；应用后使用新的 run，并复用仍符合合同的产物和已提交采集。';
  }
  function table(headers, rows) {
    return h('div', {className: 'bfw-scroll'}, h('table', {className: 'bfw-table'},
      h('thead', null, h('tr', null, headers.map((text, i) => h('th', {key: i}, text)))),
      h('tbody', null, rows.map((cells, i) => h('tr', {key: i}, cells.map((cell, j) => h('td', {key: j}, cell)))))));
  }
  function select(label, value, onChange, options) {
    return h('label', {className: 'bfw-label'}, label, h('select', {className: 'bfw-select', 'aria-label': label, value, onChange: (e) => onChange(e.target.value)},
      options.map(([id, text]) => h('option', {key: id, value: id}, text))));
  }
  return {status, button, card, empty, json, sceneName, questionText, planValue, planMarkdown,
    planMarkdownView, planEditInstruction, table, select};
}
