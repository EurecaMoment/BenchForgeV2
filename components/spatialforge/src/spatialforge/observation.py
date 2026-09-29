"""Small production observations and bounded waits without model polling spam."""
import json
import time

TERMINAL={'SUCCEEDED','FAILED_FINAL','CANCELED'}


def progress_marker(progress):
    """Wake on a new stage or error; byte progress remains display data."""
    return {k:progress[k] for k in ('stage','error','errors','interrupted') if k in progress}


def quality_outcome(folder, complete):
    review_path=folder/'scene_review.json'
    review=json.loads(review_path.read_text(encoding='utf8')) if review_path.is_file() else {}
    if not review and not complete:return None
    passed=review.get('passed',complete.get('scene_quality_passed'))
    realism=review.get('visual_realism',complete.get('visual_realism',{}))
    interaction_passed=review.get('interaction_passed',complete.get('interaction_validated'))
    not_requested=(review.get('interaction_requested') is False or
                   review.get('interaction',{}).get('reason')=='no executable interaction requested')
    if not_requested:interaction_passed=None
    result={'scene_quality_passed':passed,
            'visual_realism':realism.get('status','not_assessed'),
            'interaction_passed':interaction_passed,
            'interaction_status':'not_requested' if not_requested else {True:'passed',False:'failed',None:'not_assessed'}[interaction_passed],
            'publication_status':complete.get('publication_status',review.get('publication_status','not_released')),
            'data_export_complete':bool(complete),
            'data_target_reached':complete.get('target_reached',False),
            'collection_acceptance':(complete.get('collection_diagnostics') or {}).get('collection_acceptance','not_assessed'),
            'human_approved':complete.get('human_approved',False),
            'benchmark_approved':complete.get('benchmark_approved',False)}
    if review:
        result['feedback']={'file':'scene_review.json',
                            'issues':review.get('issues',[]),
                            'repair_suggestions':review.get('repair_suggestions',[])}
    return result


def capture_result(folder, result):
    """Expose capture facts without repeating the full asset/material inventory."""
    report=result['report']
    summary={key:report[key] for key in ('status','frames','renderable','errors','render_settings') if key in report}
    summary['source_path']=str(folder/'capture/report.json')
    views=[]
    for path in sorted((folder/'capture').glob('view_*.json')):
        frame=json.loads(path.read_text(encoding='utf8'))
        camera=frame.get('camera',{})
        objects=frame.get('objects',[])
        views.append({'frame_id':frame['frame_id'],'source_path':str(path.with_suffix('.png')),
                      'metadata_path':str(path),'rgb_std':frame.get('rgb_std'),
                      'camera':{key:camera[key] for key in ('position','target') if key in camera},
                      'visible_objects':len(objects),
                      'largest_visible_objects':[{'object_id':obj['object_id'],'area_px':obj['mask']['area_px']}
                          for obj in sorted(objects,key=lambda obj:obj['mask']['area_px'],reverse=True)[:3]]})
    return {**result,'report':summary,'views':views}


def observe(store, run_id):
    snap=store.snapshot(run_id);rows=[]
    device=store.desktop_state() if hasattr(store,'desktop_state') else {}
    for task in snap['tasks']:
        unit=task['unit'];folder=store.root/task['id']/('revision_'+str(unit['revision']))
        path=folder/'progress.json'
        progress=json.loads(path.read_text()) if path.is_file() else {}
        # JS consumers cannot exactly represent nanosecond integers above 2**53.
        if 'updated_ns' in progress:
            progress['age_seconds']=round(max(0,time.time()-int(progress['updated_ns'])/1e9),1)
            progress['updated_ns']=str(progress['updated_ns'])
        failure=task.get('failure')
        if failure and progress.get('stage') not in {'failed','complete'}:progress={**progress,'interrupted':True}
        receipt=folder/'release'/'complete.json'
        complete=json.loads(receipt.read_text()) if receipt.is_file() else {}
        row={'id':task['id'],'state':task['state'],'phase':unit['phase'],'revision':unit['revision'],
             'progress':progress,'failure':failure,
             'next_action':('retry_with_feedback' if unit['phase']=='plan' else 'retry_failed_stage') if task['state']=='FAILED_FINAL' else ('inspect_products' if task['state']=='SUCCEEDED' else 'wait')}
        captured=[]
        for prior in sorted(folder.parent.glob('revision_*'),key=lambda p:int(p.name.split('_')[-1])):
            views=len(list((prior/'capture').glob('view_*.png')))
            if views:captured.append({'revision':int(prior.name.split('_')[-1]),'views':views,'action_traces':len(list((prior/'capture').glob('interaction_*_trajectory.json')))})
        row['evidence']={'tool':'spatialforge_evidence','captured_revisions':captured,'release_required_for_read':False}
        if unit.get('workflow')=='asset' and task.get('result'):
            asset=task['result'];asset_folder=store.root/'generated_assets'/asset['asset_id']
            row.update(workflow='asset',result=asset,next_action='inspect_asset',
                asset_files=[{'file':name,'source_path':str(asset_folder/name),
                              'workspace_path':'/assets/'+asset['asset_id']+'/'+name}
                             for name in ('reference.png','mask.png','asset.glb','mesh.json','gaussian.npz')
                             if (asset_folder/name).is_file()])
        if unit.get('workflow')=='generation':
            row['workflow']='generation'
            row['tool']=unit['intent']['tool']
            if task.get('result'):
                row['result']=task['result']
                row['next_action']='inspect_outputs'
        if unit.get('intent',{}).get('capture_only') and task.get('result'):
            row['result']=capture_result(folder,task['result'])
            row['next_action']='inspect_capture_issues' if row['result']['report'].get('renderable') is False else 'inspect_captures'
        if unit.get('workflow')=='layout':
            row['workflow']='layout'
            row['design_reference_ready']=task['state']=='SUCCEEDED' and (folder/'layout_reference.png').is_file()
            if row['design_reference_ready']:
                row['next_action']='inspect_reference_then_write_scene_program'
                row['design']={k:v for k,v in (task.get('result') or {}).items() if k!='receipt'}
        if unit.get('workflow','scene')=='scene':
            quality=quality_outcome(folder,complete)
            if quality:
                row['quality']=quality
                if task['state']=='SUCCEEDED' and (quality['scene_quality_passed'] is False or
                                                  quality['visual_realism']=='needs_improvement'):
                    row['next_action']='inspect_quality_gaps'
        if task['state']=='READY' and unit['phase']=='capture' and device.get('active'):
            row['queue']={'reason':'desktop_device_in_use','blocking_task_id':device.get('task_id')}
        if snap['state']=='CANCELED':
            row['next_action']='wait_worker_ack' if task.get('lease_owner') else 'inspect_evidence'
        if complete:
            row['summary']={k:complete[k] for k in ('accepted','target_items','frames','split','shortfall','publication_status','scene_quality_passed','interaction_validated','scene_self_contained') if k in complete}
            row['downloads']=[p.relative_to(folder).as_posix() for p in (folder/'release').glob('*.zip')]
        rows.append(row)
    # An opaque equality cursor, not a hash or an artifact-integrity check.
    cursor=json.dumps({'v':3,'state':snap['state'],'tasks':[[r['id'],r['state'],r['phase'],r['revision'],progress_marker(r['progress']),r['failure']] for r in rows]},sort_keys=True,separators=(',',':'))
    return {'run_id':run_id,'state':snap['state'],'terminal':snap['state'] in TERMINAL,
            'tasks':rows,'cursor':cursor,'next_poll_seconds':0 if snap['state'] in TERMINAL else 60}


def wait_for_change(store,run_id,cursor=None,timeout_seconds=60,stop=None):
    if type(timeout_seconds) is not int or not 1<=timeout_seconds<=60:raise ValueError('timeout_seconds must be 1..60')
    started=time.monotonic();value=observe(store,run_id)
    baseline=cursor if cursor is not None else value['cursor']
    while not value['terminal'] and value['cursor']==baseline and time.monotonic()-started<timeout_seconds:
        delay=min(2,timeout_seconds-(time.monotonic()-started))
        if stop is not None:
            if stop.wait(delay):break
        else:time.sleep(delay)
        value=observe(store,run_id)
    return {**value,'changed':value['cursor']!=baseline,'waited_seconds':round(time.monotonic()-started,2)}
