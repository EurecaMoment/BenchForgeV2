import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const observationSources = ['../../../backend/benchforge_backend/observation.py', '../../dist/workbench/observation.py']
  .map(source => fileURLToPath(new URL(source, import.meta.url)));
// Reuse the saved native projection without constructing Store, querying a
// database or sending operator credentials to a child process.
const projection = String.raw`
import importlib.util
import json
from pathlib import Path
import sys
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
snapshot = json.load(sys.stdin)
source = next((path for path in sys.argv[1:3] if Path(path).is_file()), None)
if source:
    spec = importlib.util.spec_from_file_location('plugin_native_observation', source)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
else:
    try:
        native = importlib.import_module('benchforge_backend.observation')
    except ImportError as error:
        raise RuntimeError('Native observation projection unavailable: repository source is missing and benchforge_backend.observation is not importable') from error
class SnapshotStore:
    root = Path(sys.argv[3])
    def snapshot(self, requested):
        return snapshot
value = native.observe(SnapshotStore(), sys.argv[4])
value.pop('cursor', None)
json.dump(value, sys.stdout, ensure_ascii=False)
`;

export function projectObservationSnapshot(snapshot, {runId, artifacts, policyPython = 'python3', signal}) {
  signal?.throwIfAborted();
  if (typeof artifacts !== 'string' || !artifacts) throw new Error('Native observation projection requires the service artifacts path');
  const input = JSON.stringify(snapshot);
  return new Promise((resolve, reject) => {
    const child = spawn(policyPython, ['-B', '-c', projection, ...observationSources, artifacts, runId],
      {stdio: ['pipe', 'pipe', 'pipe'], signal, windowsHide: true});
    let output = '', errors = '', timedOut = false;
    const timer = setTimeout(() => {timedOut = true; child.kill();}, 10000);
    child.stdout.on('data', value => output += value);
    child.stderr.on('data', value => errors += value);
    child.stdin.on('error', () => {});
    child.once('error', error => {
      clearTimeout(timer);
      reject(signal?.aborted ? signal.reason : error);
    });
    child.once('close', (code, termination) => {
      clearTimeout(timer);
      try {
        signal?.throwIfAborted();
        if (timedOut) throw new Error('Native observation projection timed out');
        if (code !== 0) throw new Error('Native observation projection failed (' + (termination || code) + '): ' + errors.slice(-600));
        // Keep the same signed-zero normalization as the service API transport.
        resolve(JSON.parse(output, (_key, value) => Object.is(value, -0) ? 0 : value));
      } catch (error) {reject(error);}
    });
    child.stdin.end(input);
  });
}

export function createObservationBridge({api, artifacts, policyPython, project = projectObservationSnapshot}) {
  return async (route, args, signal) => {
    signal?.throwIfAborted();
    try {
      const value = await api(route, args, signal);
      signal?.throwIfAborted();
      return value;
    } catch (error) {
      if (!['/observe', '/wait'].includes(route) || error.status !== 400 ||
          error.response?.error !== 'KeyError' || error.response?.detail !== "'report'") throw error;
    }
    signal?.throwIfAborted();
    // One fresh read for this known old-service error. Do not poll, retry,
    // mutate tasks or reinterpret failed acceptance as successful production.
    const snapshot = await api('/inspect', {run_id: args.run_id}, signal);
    signal?.throwIfAborted();
    const value = await project(snapshot, {runId: args.run_id, artifacts, policyPython, signal});
    signal?.throwIfAborted();
    return value;
  };
}
