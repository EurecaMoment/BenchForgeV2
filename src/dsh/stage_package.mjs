import {copyFile, mkdir} from 'node:fs/promises';

const sourceRoot = new URL('..', import.meta.url);
const packageRoot = new URL('.', import.meta.url);
const files = [
  ['capabilities/benchmark_design/resources/assessment_template.json', 'dist/resources/assessment_template.json'],
  ['capabilities/task_catalog/resources/benchmark_templates.json', 'dist/resources/task_templates.json'],
];

for (const [source, destination] of files) {
  const target = new URL(destination, packageRoot);
  await mkdir(new URL('.', target), {recursive: true});
  await copyFile(new URL(source, sourceRoot), target);
}
