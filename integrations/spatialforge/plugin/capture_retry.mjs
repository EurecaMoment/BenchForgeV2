import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

export function createCaptureRetry({api, serviceConfig, policyPython}) {
  return async (args, signal) => {
    signal?.throwIfAborted();
    try {return await api('/retry', args, signal);}
    catch (error) {
      const detail = error.response?.detail || '';
      if (error.status !== 400 || error.response?.error !== 'ValueError' ||
          !(detail.startsWith('Unreviewed scene retries require an admitted native capture') ||
            detail.startsWith('Only review transport failures can reuse a frozen capture') ||
            detail.startsWith('Only review transport or capture execution/transport failures can retry'))) throw error;
    }
    signal?.throwIfAborted();
    return new Promise((resolve, reject) => {
      const child = spawn(policyPython, ['-B', fileURLToPath(new URL('../capture_retry.py', import.meta.url)),
        '--config', serviceConfig], {stdio: ['pipe','pipe','pipe'], signal, windowsHide: true});
      let output = '', errors = '', timedOut = false;
      const timer = setTimeout(() => {timedOut = true;child.kill();}, 20000);
      child.stdout.on('data', value => output += value);
      child.stderr.on('data', value => errors += value);
      child.stdin.on('error', () => {});
      child.once('error', error => {clearTimeout(timer);reject(error);});
      child.once('close', (code, termination) => {
        clearTimeout(timer);
        try {
          signal?.throwIfAborted();
          if (code !== 0) throw new Error('Native capture recovery rejected (' + (timedOut ? 'timeout' : termination || code) + '): ' + errors.slice(-700));
          resolve(JSON.parse(output));
        } catch (error) {reject(error);}
      });
      child.stdin.end(JSON.stringify(args));
    });
  };
}
