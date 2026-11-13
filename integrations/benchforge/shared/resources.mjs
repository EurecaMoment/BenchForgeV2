import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

const resource = (name) => new URL(`../../resources/${name}`, import.meta.url);

export async function readTaskTemplates() {
  return JSON.parse(await fs.readFile(fileURLToPath(resource('task_templates.json')), 'utf8'));
}

export async function readAssessmentTemplate() {
  return JSON.parse(await fs.readFile(fileURLToPath(resource('assessment_template.json')), 'utf8'));
}
