"""One installed Isaac process, serving sequential captures from a local mailbox."""
import argparse
import json
import os
from pathlib import Path
import time
import traceback

from isaac_capture import application_config, run_capture, RENDER_SETTING_KEYS


def write_json(path, value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    temporary.replace(path)


def serve(state, idle_seconds):
    state.mkdir(parents=True,exist_ok=True)
    app=None;profile=None;defaults=None;completed=0
    last_used=time.monotonic()
    status={'pid':os.getpid(),'state':'starting','token':None}
    write_json(state/'status.json',status)
    try:
        while True:
            command_path=state/'command.json'
            if not command_path.exists():
                if time.monotonic()-last_used>=idle_seconds:break
                if app is not None:app.update()
                time.sleep(.2)
                continue
            command=json.loads(command_path.read_text(encoding='utf8'))
            command_path.replace(state/'active.json')
            if command['action']=='shutdown':break
            request=Path(command['request']);output=Path(command['output'])
            output.mkdir(parents=True,exist_ok=True)
            result_path=output.parent/'resident_result.json'
            job=json.loads(request.read_text(encoding='utf8'))
            status.update(state='capture',token=job['token'])
            write_json(state/'status.json',status)
            try:
                requested=application_config(job)
                if app is not None and requested!=profile:
                    write_json(result_path,{'token':job['token'],'state':'restart_required','pid':os.getpid()})
                    break
                boot_seconds=0.
                if app is None:
                    from isaacsim import SimulationApp
                    started=time.perf_counter()
                    app=SimulationApp(requested)
                    boot_seconds=time.perf_counter()-started
                    import carb
                    defaults={key:carb.settings.get_settings().get(key) for key in RENDER_SETTING_KEYS}
                    profile=requested
                code=run_capture(job,output,app,renderer_defaults=defaults,
                                 app_reused=completed>0,boot_seconds=boot_seconds)
                result={'token':job['token'],'state':'complete','exit_code':code,
                        'pid':os.getpid(),'app_reused':completed>0,'finished_at':time.time()}
            except Exception as exc:
                traceback.print_exc()
                result={'token':job['token'],'state':'failed','exit_code':1,
                        'pid':os.getpid(),'error':repr(exc),'finished_at':time.time()}
                write_json(result_path,result)
                break
            completed+=1;last_used=time.monotonic()
            status.update(state='idle',token=None,profile=profile,completed=completed)
            write_json(state/'status.json',status)
            # Completion becomes visible only after all task state has been cleared.
            write_json(result_path,result)
            (state/'active.json').unlink()
    finally:
        status.update(state='stopping',token=None)
        write_json(state/'status.json',status)
        if app is not None:app.close()
        status.update(state='stopped',token=None)
        write_json(state/'status.json',status)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--idle-seconds',type=float,default=300.)
    args=parser.parse_args()
    serve(args.state,args.idle_seconds)


if __name__=='__main__':main()
