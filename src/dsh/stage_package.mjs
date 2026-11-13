import {copyFile, mkdir} from 'node:fs/promises';

const sourceRoot = new URL('../', import.meta.url);
const packageRoot = new URL('./', import.meta.url);
const pipelines = 'benchforge_core/pipelines';
const backend = 'backend/benchforge_backend';
const files = [
  [`${pipelines}/assessment_template.json`, 'dist/resources/assessment_template.json'],
  [`${pipelines}/task_templates.json`, 'dist/resources/task_templates.json'],
  [`${backend}/dispatcher_control.py`, 'benchforge/capture_finish.py'],
  [`${backend}/workbench_queries.py`, 'dist/workbench/workbench_queries.py'],
  [`${backend}/observation.py`, 'dist/workbench/observation.py'],
];

for (const [source, destination] of files) {
  const target = new URL(destination, packageRoot);
  await mkdir(new URL('.', target), {recursive: true});
  await copyFile(new URL(source, sourceRoot), target);
}
