import {readFile} from 'node:fs/promises';

async function readResource(name) {
  const contents = await readFile(new URL('./resources/' + name, import.meta.url), 'utf8');
  return JSON.parse(contents);
}

export async function readTaskTemplates() {
  return readResource('task_templates.json');
}

export async function readAssessmentTemplate() {
  return readResource('assessment_template.json');
}
