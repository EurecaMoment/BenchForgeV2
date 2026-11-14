import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {createWorkbenchHandler} from '../../host/workbench/stage_products.js';

test('Markdown download serves the saved public report only to its conversation', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-report-download-'));
  try {
    const run = path.join(directory, 'formal-run');
    await fs.mkdir(run);
    const markdown = '# 生产与质检报告\n\n100 道题已正式入库。\n';
    const report = path.join(run, 'delivery_report.json');
    await fs.writeFile(report, JSON.stringify({body_markdown: markdown, accepted: 100,
      answer: 'PRIVATE_ANSWER', scene_previews: []}));
    await fs.writeFile(path.join(run, 'state.json'), JSON.stringify({state: 'completed',
      context: {session_ids: ['session-report-owner']},
      steps: {package: {state: 'completed', result: {report}}}}));
    const id = Buffer.from(JSON.stringify(['report-workspace', 'formal-run'])).toString('base64url');
    const handler = createWorkbenchHandler({}, () => [{id: 'report-workspace', path: directory}]);
    const request = (session) => handler(new Request('http://dsh.test/api/benchforge/workbench?' +
      new URLSearchParams({workspace_path: directory, session_id: session, view: 'run_product',
        product: 'report', step: 'package', run: id, format: 'markdown'})));
    const response = await request('session-report-owner');
    assert.equal(response.status, 200);
    assert.match(response.headers.get('content-type'), /text\/markdown/);
    assert.match(response.headers.get('content-disposition'), /attachment; filename="delivery_report.md"/);
    assert.equal(await response.text(), markdown);
    assert.equal((await request('session-another-owner')).status, 403);
    await fs.writeFile(report, JSON.stringify({accepted: 100, answer: 'PRIVATE_ANSWER'}));
    assert.equal((await request('session-report-owner')).status, 404);
  } finally {
    await fs.rm(directory, {recursive: true, force: true});
  }
});
