import {copyFile, mkdir} from 'node:fs/promises';

const sourceRoot = new URL('..', import.meta.url);
const packageRoot = new URL('.', import.meta.url);
const pipelines = 'benchmark_workflows/resources';
const files = [
  [`${pipelines}/assessment_template.json`, 'dist/resources/assessment_template.json'],
  [`${pipelines}/task_templates.json`, 'dist/resources/task_templates.json'],
];

for (const [source, destination] of files) {
  const target = new URL(destination, packageRoot);
  await mkdir(new URL('.', target), {recursive: true});
  await copyFile(new URL(source, sourceRoot), target);
}
