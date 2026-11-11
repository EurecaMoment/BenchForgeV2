import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const integrations = path.resolve(import.meta.dirname, '..');
const packageName = '@eurecamoment/benchforge-dsh';
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-npm-release-'));

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {encoding: 'utf8', ...options});
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} failed (${result.status}): ${result.stderr}`);
  return result.stdout;
}

try {
  const packed = JSON.parse(run(npm, ['pack', '--json', `--pack-destination=${temp}`], {
    cwd: integrations,
    shell: process.platform === 'win32',
  }));
  assert.equal(packed.length, 1, 'npm pack should produce one artifact');
  const files = new Set(packed[0].files.map(file => file.path));
  const required = [
    'package.json',
    'dsh/tools.mjs',
    'dsh/persistent-shell.mjs',
    'dsh/build_presets.py',
    'dsh/build_preset.py',
    'dsh/profile_migration.py',
    'dsh/install_preset.py',
    'cordis.patch.yml',
    'spatialforge/plugin/tools.mjs',
    'spatialforge/preset_definition.py',
    'spatialforge/task_support/README.md',
    'spatialforge/task_support/public_sensor_cache.py',
    'spatialforge/task_support/public_geometry_cache.py',
    'spatialforge/task_support/public_measurements.py',
    'spatialforge/plugin/capture_runtime.mjs',
    'spatialforge/shared/config.mjs',
    'spatialforge/shared/resources.mjs',
    'spatialforge/scene_policy_gate.py',
    'spatialforge/capture_retry.py',
    'spatialforge/capture_finish.py',
    'spatialforge/native_asset_facing.py',
    'spatialforge/native_asset_facing.json',
    'spatialforge/ui/index.js',
    'spatialforge/ui/client.js',
    'spatialforge/ui/parallel_sessions.js',
    'spatialforge/ui/preparation_products.js',
    'spatialforge/ui/stage_products.js',
    'spatialforge/ui/synthesis_sessions.js',
    'spatialforge/ui/plan_edit_cli.py',
    'spatialforge/ui/plan_request_cli.py',
    'spatialforge/ui/scene_library.py',
    'spatialforge/ui/scene_preview_video.py',
    'spatialforge/ui/production_observer.py',
    'spatialforge/ui/stage_review_cli.py',
    'spatialforge/ui/workbench/scope.js',
    'spatialforge/ui/workbench/routes.js',
    'spatialforge/ui/workbench/public_artifacts.js',
    'resources/task_templates.json',
    'resources/assessment_template.json',
  ];
  for (const file of required) assert.ok(files.has(file), `npm tarball is missing ${file}`);

  const archive = path.join(temp, packed[0].filename);
  const extracted = path.join(temp, 'extracted');
  await fs.mkdir(extracted);
  run('tar', ['-xzf', archive, '-C', extracted]);
  const packageRoot = path.join(extracted, 'package');
  const manifest = JSON.parse(await fs.readFile(path.join(packageRoot, 'package.json'), 'utf8'));
  for (const target of Object.values(manifest.exports)) {
    const file = typeof target === 'string' ? target : target.import;
    if (file?.startsWith('./')) assert.ok(files.has(file.slice(2)), `package export is absent: ${file}`);
  }

  const consumer = path.join(temp, 'consumer');
  await fs.mkdir(consumer);
  run(npm, ['install', '--prefix', consumer, '--ignore-scripts', '--no-save', '--package-lock=false',
    '--legacy-peer-deps', '--no-audit', '--no-fund', '--offline', archive], {
    cwd: integrations,
    shell: process.platform === 'win32',
  });
  const installedModules = path.join(consumer, 'node_modules');
  const peerScope = path.join(installedModules, '@deepseek-ai');
  await fs.symlink(path.join(integrations, 'node_modules', '@deepseek-ai'), peerScope,
    process.platform === 'win32' ? 'junction' : 'dir');

  const installedRoot = path.join(installedModules, ...packageName.split('/'));
  const modules = [
    packageName,
    `${packageName}/benchforge-tools`,
    `${packageName}/spatialforge-tools`,
    `${packageName}/spatialforge-ui`,
    `${packageName}/persistent-shell`,
  ];
  const consumerRequire = createRequire(path.join(consumer, 'package.json'));
  for (const specifier of modules) await import(pathToFileURL(consumerRequire.resolve(specifier)));
  for (const entry of await fs.readdir(path.join(installedRoot, 'spatialforge', 'plugin'))) {
    if (entry.endsWith('.mjs')) await import(pathToFileURL(path.join(installedRoot, 'spatialforge', 'plugin', entry)));
  }
  await import(pathToFileURL(path.join(installedRoot, 'spatialforge', 'ui', 'index.js')));
  console.log('Packed, installed, and imported the standalone DSH package runtime.');
} finally {
  await fs.rm(temp, {recursive: true, force: true});
}
