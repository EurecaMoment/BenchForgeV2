"""Run the chosen collector inside its configured simulator environment."""
import os
from pathlib import Path
import signal
import subprocess

from service_access.processes import terminate_process_tree


def collect(tool, args, directory, config, workspace):
    cfg = config.get('collectors', {}).get(tool)
    if not cfg:
        raise ValueError(f'Configure collectors.{tool}.command with the installed simulator Python environment')
    output = directory / 'capture'
    output.mkdir()
    script = Path(cfg['script']) if cfg.get('script') else Path(__file__).with_name('collectors') / (tool + '.py')
    command = list(cfg['command']) + [str(script), *args.get('argv', []), '--output-dir', str(output)]
    cfg_env = cfg.get('env', {})
    env = {**os.environ, **cfg_env}
    with (directory / "stdout.log").open("w", encoding="utf-8") as stdout, (directory / "stderr.log").open("w", encoding="utf-8") as stderr:
        options = {'start_new_session': True} if os.name != 'nt' else {
            'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        }
        completed = subprocess.Popen(
            command, cwd=workspace, env=env, stdout=stdout, stderr=stderr, **options
        )
        try:
            completed.wait(timeout=args.get('timeout_seconds',3600))
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                terminate_process_tree(completed)
            else:
                try:
                    os.killpg(completed.pid, signal.SIGTERM)
                except ProcessLookupError:
                    completed.terminate()
                try:
                    completed.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(completed.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        completed.kill()
                    completed.wait()
            raise
        finally:
            # Only the collector's own process group, including any explicitly
            # launched test server; attached shared servers are outside it.
            if os.name!='nt':
                try:os.killpg(completed.pid,signal.SIGTERM)
                except ProcessLookupError:pass
            elif completed.poll() is None:terminate_process_tree(completed)
    if completed.returncode:
        detail = (directory / 'stderr.log').read_text(encoding='utf-8')[-6000:]
        raise RuntimeError(f"{tool} exited {completed.returncode}: {detail}; full log: {directory / 'stderr.log'}")
    if any(flag in args.get('argv', []) for flag in ('--help', '-h')):
        return {'help': (directory / 'stdout.log').read_text(encoding='utf-8'),
                'capture_started': False, 'collector': tool}
    files = [str(p.relative_to(output)) for p in output.rglob("*") if p.is_file()]
    if not files:
        raise RuntimeError(f"{tool} returned without capture artifacts; stdout: {directory / 'stdout.log'}")
    return {"output_dir": str(output), "files": files, "execution_complete": True,
            "quality": "not_assessed", "next": "Inspect real images and raw state before building benchmark evidence."}
