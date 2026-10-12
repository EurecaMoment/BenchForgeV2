"""Transfer explicitly requested background work to its own process owner."""
import os
from pathlib import Path
import subprocess
import uuid


def start_background(command, *, cwd, log, env=None):
    """Keep background jobs outside a managed tool's cancellation scope.

    Ordinary CLI use keeps the existing detached-process behavior. Inside DSH,
    a user service owns the new job before the short-lived CLI returns.
    """
    cwd = str(Path(cwd).resolve())
    log = Path(log).resolve()
    environment = {**os.environ, **(env or {})}
    managed = environment.pop('BENCHFORGE_MANAGED_SUBPROCESS', None) == '1'
    if managed and os.name != 'nt':
        service = 'benchforge-job-' + uuid.uuid4().hex[:12] + '.service'
        request = ['systemd-run', '--user', '--collect', '--quiet', '--unit=' + service,
                   '--property=Type=exec', '--working-directory=' + cwd,
                   '--property=StandardInput=null', '--property=StandardOutput=append:' + str(log),
                   '--property=StandardError=append:' + str(log)]
        request.extend('--setenv=' + key + '=' + value for key, value in environment.items())
        launch = subprocess.run([*request, '--', *command], capture_output=True, text=True)
        if launch.returncode:
            raise RuntimeError('Background service could not start: ' + launch.stderr.strip())
        pid = int(subprocess.check_output(['systemctl', '--user', 'show', service,
                                          '--property=MainPID', '--value'], text=True).strip())
        return {'pid': pid, 'service': service, 'owner': 'systemd-user'}
    kwargs = {'start_new_session': True} if os.name != 'nt' else {
        'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    with log.open('ab') as output:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, **kwargs)
    return {'pid': process.pid, 'owner': 'detached-process'}
