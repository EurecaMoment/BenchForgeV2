import fs from 'node:fs/promises';
import path from 'node:path';

function rejectDuplicateObjectKeys(source) {
  let index = 0;
  const whitespace = () => { while (/\s/.test(source[index] || '') && index < source.length) index += 1; };
  const readString = () => {
    const start = index++;
    while (index < source.length) {
      if (source[index] === '\\') { index += 2; continue; }
      if (source[index++] === '"') return JSON.parse(source.slice(start, index));
    }
    return '';
  };
  const readValue = () => {
    whitespace();
    if (source[index] === '{') {
      index += 1;
      whitespace();
      const keys = new Set();
      if (source[index] === '}') { index += 1; return; }
      while (index < source.length) {
        whitespace();
        const key = readString();
        if (keys.has(key)) throw new Error(`Duplicate JSON key: ${key}`);
        keys.add(key);
        whitespace();
        index += 1;
        readValue();
        whitespace();
        if (source[index] === '}') { index += 1; return; }
        index += 1;
      }
      return;
    }
    if (source[index] === '[') {
      index += 1;
      whitespace();
      if (source[index] === ']') { index += 1; return; }
      while (index < source.length) {
        readValue();
        whitespace();
        if (source[index] === ']') { index += 1; return; }
        index += 1;
      }
      return;
    }
    if (source[index] === '"') { readString(); return; }
    while (index < source.length && !/[\s,\]}]/.test(source[index])) index += 1;
  };
  readValue();
}

export function parseStrictJson(source) {
  rejectDuplicateObjectKeys(source);
  return JSON.parse(source);
}

async function environmentValue(getEnvironmentValue, name) {
  if (!getEnvironmentValue) return process.env[name];
  const result = await getEnvironmentValue(name);
  return result && typeof result === 'object' && 'value' in result ? result.value : result;
}

async function expandEnvironment(value, getEnvironmentValue) {
  if (typeof value !== 'string') throw new Error('Configuration path/value must be a string');
  const reference = /\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)|%([A-Za-z_][A-Za-z0-9_]*)%/g;
  const matches = [...value.matchAll(reference)];
  let result = value;
  for (const match of matches) {
    const name = match[1] || match[2] || match[3];
    const replacement = await environmentValue(getEnvironmentValue, name);
    if (replacement === undefined || replacement === null || replacement === '')
      throw new Error(`Configuration references unset environment variable ${name}`);
    result = result.replace(match[0], String(replacement));
  }
  return result;
}

export async function resolveConfigPath(value, configPath, getEnvironmentValue) {
  const expanded = await expandEnvironment(value, getEnvironmentValue);
  const resolved = path.resolve(path.dirname(configPath), expanded);
  return resolved;
}

async function isFile(file) {
  try { return (await fs.stat(file)).isFile(); } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return false;
    throw error;
  }
}

export async function loadServiceConfig(configFile, {getEnvironmentValue} = {}) {
  let configPath = path.resolve(await expandEnvironment(configFile, getEnvironmentValue));
  const source = await fs.readFile(configPath, 'utf8');
  let config = parseStrictJson(source);
  if (!config || typeof config !== 'object' || Array.isArray(config))
    throw new Error('BenchForgeV2 service configuration must be a JSON object');
  if (config.service_config) {
    const basePath = await resolveConfigPath(config.service_config, configPath, getEnvironmentValue);
    const base = parseStrictJson(await fs.readFile(basePath, 'utf8'));
    if (!base || typeof base !== 'object' || Array.isArray(base))
      throw new Error('Referenced BenchForgeV2 service configuration must be a JSON object');
    const {service_config: ignored, ...overrides} = config;
    for (const field of ['port', 'service_url', 'execution_mode', 'scene_policy_path']) {
      if (field in overrides && field in base && overrides[field] !== base[field])
        throw new Error(`${field} in ${path.basename(configPath)} conflicts with referenced service configuration`);
    }
    config = {...base, ...overrides};
    configPath = basePath;
  }

  const configuredMode = config.execution_mode || 'production';
  const environmentMode = await environmentValue(getEnvironmentValue, 'SPATIALFORGE_EXECUTION_MODE');
  if (config.execution_mode !== undefined && environmentMode && environmentMode !== config.execution_mode)
    throw new Error('SPATIALFORGE_EXECUTION_MODE conflicts with configured execution_mode');
  const executionMode = config.execution_mode !== undefined ? config.execution_mode : environmentMode || configuredMode;
  if (!['production', 'exploration'].includes(executionMode))
    throw new Error('execution_mode must be production or exploration');
  config.execution_mode = executionMode;

  const pathFields = [
    ['artifacts', 'SPATIALFORGE_ARTIFACTS'],
    ['harness', 'SPATIALFORGE_HARNESS'],
    ['models_config', 'SPATIALFORGE_MODELS_CONFIG'],
    ['task_root', 'SPATIALFORGE_TASK_ROOT'],
    ['scene_policy_path', 'SPATIALFORGE_SCENE_POLICY'],
  ];
  for (const [field, envName] of pathFields) {
    const override = await environmentValue(getEnvironmentValue, envName);
    const value = override || config[field];
    if (value) config[field] = await resolveConfigPath(String(value), configPath, getEnvironmentValue);
  }

  const urlOverride = await environmentValue(getEnvironmentValue, 'SPATIALFORGE_SERVICE_URL');
  const urlValue = urlOverride || config.service_url;
  if (urlValue) {
    config.service_url = (await expandEnvironment(String(urlValue), getEnvironmentValue)).replace(/\/$/, '');
  } else {
    const port = Number(config.port ?? 3841);
    if (!Number.isInteger(port) || port < 1 || port > 65535)
      throw new Error('port must be between 1 and 65535');
    const host = await expandEnvironment(String(config.service_host || '127.0.0.1'), getEnvironmentValue);
    config.service_url = `http://${host}:${port}`;
  }

  const envName = config.operator_token_env || 'SPATIALFORGE_OPERATOR_TOKEN';
  const configuredToken = await environmentValue(getEnvironmentValue, envName);
  const token = config.operator_token_env ? configuredToken : config.operator_token || configuredToken;
  if (!token) throw new Error(`Configure operator_token or set ${envName}`);
  config.operator_token = token;

  let policyPath = config.scene_policy_path || '';
  if (!policyPath) {
    const candidates = [
      config.task_root && path.join(config.task_root, 'scene-library', 'policy.json'),
      path.join(path.dirname(configPath), 'scene-library', 'policy.json'),
      path.join(path.dirname(path.dirname(configPath)), 'scene-library', 'policy.json'),
    ].filter(Boolean);
    for (const candidate of candidates) {
      if (await isFile(candidate)) { policyPath = candidate; break; }
    }
  }
  if (policyPath && !(await isFile(policyPath)))
    throw new Error(`scene policy file does not exist: ${policyPath}`);
  if (executionMode === 'production' && !policyPath)
    throw new Error('execution_mode=production requires scene_policy_path pointing to an existing policy.json');
  config.scene_policy_path = policyPath || '';

  return {config, configPath, serviceUrl: config.service_url, operatorToken: token,
    executionMode, scenePolicyPath: policyPath || null};
}
