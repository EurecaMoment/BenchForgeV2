import {readFile} from 'node:fs/promises';

const source = new URL('../../benchforge_core/pipelines/', import.meta.url);
const packaged = new URL('../dist/resources/', import.meta.url);

async function readResource(name) {
  let contents;
  try {
    // Checkouts always read the Python package's source files, even after npm pack.
    contents = await readFile(new URL(name, source), 'utf8');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    contents = await readFile(new URL(name, packaged), 'utf8');
  }
  return JSON.parse(contents);
}

export async function readTaskTemplates() {
  return readResource('task_templates.json');
}

export async function readAssessmentTemplate() {
  return readResource('assessment_template.json');
}
