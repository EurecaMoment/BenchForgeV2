import {copyFile, mkdir} from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const dist = new URL('./dist/', import.meta.url);
const pipelines = 'src/benchforge_core/pipelines';
const backend = 'components/benchforge/src/benchforge_backend';
const files = [
  [`${pipelines}/assessment_template.json`, 'resources/assessment_template.json'],
  [`${pipelines}/task_templates.json`, 'resources/task_templates.json'],
  [`${backend}/dispatcher_control.py`, 'dispatcher/capture_finish.py'],
  [`${backend}/workbench_queries.py`, 'workbench/workbench_queries.py'],
];

for (const [source, destination] of files) {
  const target = new URL(destination, dist);
  await mkdir(new URL('.', target), {recursive: true});
  await copyFile(new URL(source, root), target);
}
