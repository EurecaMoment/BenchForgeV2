"""Run against a NEW isolated PostgreSQL configuration, with no desktop worker.

Uses the real HTTP server, task sandbox and persistent queue. Does not simulate
capture success or call any model. Leaves a canceled task and its receipts.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    root = Path(__file__).resolve().parents[3]
    program = json.loads((root / 'examples/push_box_scene.json').read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    log = (args.output / 'service.log').open('a')
    process = None
    run_id = None

    def api(route, payload, token=None):
        request = Request(f'http://127.0.0.1:{config["port"]}{route}',
                          data=json.dumps(payload).encode(),
                          headers={'Authorization':'Bearer ' + (token or config['operator_token']),
                                   'Content-Type':'application/json'})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def start():
        proc = subprocess.Popen([sys.executable, '-m', 'spatialforge.service', '--config', str(args.config)],
                                stdout=log, stderr=log)
        for _ in range(60):
            if proc.poll() is not None:
                raise RuntimeError('Service exited; see service.log')
            try:
                api('/catalog', {})
                return proc
            except URLError:
                time.sleep(.5)
        proc.terminate()
        proc.wait(timeout=15)
        raise RuntimeError('Service failed to bind the configured port')

    try:
        process = start()
        try:
            api('/catalog', {}, 'incorrect-token')
            raise AssertionError('Unauthenticated catalog allowed')
        except HTTPError as error:
            assert error.code in (401,403)
        templates = api('/catalog', {'section':'dataset_templates'})
        code = 'import json\nfrom pathlib import Path\nPath("scene.json").write_text(' + repr(json.dumps(program)) + ')\nprint("created scene.json")'
        authored = api('/task-code', {'workspace_id':'install-roundtrip','code':code})
        assert authored['returncode'] == 0, authored
        scene = next(row['source_path'] for row in authored['artifacts'] if row['file']=='scene.json')
        request = {'request_key':'install-roundtrip','scene_program_path':scene}
        submitted = api('/capture', request)
        run_id = submitted['run_id']
        assert api('/capture', request)['run_id'] == run_id
        process.terminate()
        process.wait(timeout=15)
        process = start()
        recovered = api('/observe', {'run_id':run_id})
        assert recovered['run_id'] == run_id and recovered['state'] != 'SUCCEEDED'
        canceled = api('/cancel', {'run_id':run_id})
        after = api('/observe', {'run_id':run_id})
        assert after['state'] == 'CANCELED', after
        receipt = {'postgresql_http_sandbox_roundtrip':'passed', 'run_id':run_id,
                   'auth_rejection':True,'sandbox_returncode':authored['returncode'],
                   'idempotent_submission':True,'restart_retained_request':True,
                   'final_state':after['state'],'dataset_templates_returned':bool(templates),
                   'model_api_calls':0,'isaac_starts':0,'scene_quality_accepted':False}
        (args.output / 'roundtrip.json').write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt))
    finally:
        if process and process.poll() is None:
            if run_id:
                api('/cancel', {'run_id':run_id})
            process.terminate()
            process.wait(timeout=15)
        log.close()


if __name__ == '__main__':
    main()
