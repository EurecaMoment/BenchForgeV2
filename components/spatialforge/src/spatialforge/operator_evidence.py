"""Bounded access to task evidence, including failed revisions, without authority GT."""
import json
from pathlib import Path
import re
import shutil

PUBLIC_RELEASE_FILES = {'release/'+name for name in (
    'complete.json', 'collection_report.json', 'data_selection.json', 'item_reviews.json',
    'model_bundle.json', 'model_bundle.zip', 'scene_bundle.zip', 'interaction_bundle.zip')}


def _allowed(name):
    return (name in {'program.json','submitted_program.json','program_handoff.json','proposal.json','repair_seed.json','scene_review.json','progress.json','geometry_preview.json','repair_context.json','repair_changes.json','data_selection.json','generation_stage.json',
                     'layout_reference.png','layout_reference.json','generation/reference.png','generation/input_mask.png','generation/asset_ref.json','generation/asset_request.json','capture/program.json','capture/report.json','capture/evidence.json','layout/reference.png','layout/receipt.json'}
            or bool(re.fullmatch(r'capture/view_\d+(?:\.png|\.json|_(?:depth|semantic|instance)\.npy)',name))
            or bool(re.fullmatch(r'capture/interaction_\d+_(?:before\.png|after\.png|trajectory\.json)',name))
            or bool(re.fullmatch(r'capture/interaction_\d+(?:\.mp4|_recording\.json|_frames\.zip)',name))
            or name in PUBLIC_RELEASE_FILES
            or bool(re.fullmatch(r'release/images/[^/]+\.png',name))
            or bool(re.fullmatch(r'model_calls/scene_plan_\d+/(?:validation_error|response|parse_error)\.json',name))
            or bool(re.fullmatch(r'(?:generation|generation_stage)/[a-zA-Z0-9_./-]+\.(?:png|jpg|jpeg|json|npy|npz|glb|gltf|ply|obj)',name))
            or bool(re.fullmatch(r'generation/[a-zA-Z0-9_-]+/(?:reference\.png|input_mask\.png)',name)))


def evidence(store,task_id,revision=None,file=None,workspace_id=None):
    snapshot=store.snapshot(task_id.split('.')[0])
    task=next((t for t in snapshot['tasks'] if t['id']==task_id),None)
    if task is None:raise ValueError('task not found in run')
    base=(store.root/task_id).resolve()
    if not base.is_relative_to(store.root.resolve()):raise ValueError('invalid task path')
    if revision is not None and (type(revision) is not int or revision<0):raise ValueError('revision must be a nonnegative integer')
    revision=task['unit']['revision'] if revision is None else revision
    folder=base/f'revision_{revision}'
    if not folder.is_dir():raise ValueError('revision evidence is unavailable')
    stage_path=folder/'generation_stage.json'
    stage=json.loads(stage_path.read_text()) if stage_path.is_file() else {}
    stage_files={row['file'] for row in stage.get('files',[])}
    result={'task_id':task_id,'state':task['state'],'revision':revision,'latest_revision':task['unit']['revision'],
            'scope':'production evidence and public exports; export availability is separate from quality acceptance; authority answers are excluded'}
    if file is None:
        if workspace_id is not None:raise ValueError('workspace_id requires a file to copy')
        rows=[]
        for rev in sorted(base.glob('revision_*'),key=lambda p:int(p.name.split('_')[-1])):
            files=[]
            candidates=[*rev.glob('*.json'),*rev.glob('capture/*'),*(rev/'generation').rglob('*'),*(rev/'generation_stage').rglob('*'),*(rev/'release').rglob('*'),*rev.glob('model_calls/scene_plan_*/*.json')]
            for path in candidates:
                name=path.relative_to(rev).as_posix()
                if _allowed(name) and path.is_file() and not path.is_symlink():files.append({'file':name,'bytes':path.stat().st_size})
            summary={'revision':int(rev.name.split('_')[-1]),'files':files,'captured_views':sum(bool(re.fullmatch(r'capture/view_\d+\.png',x['file'])) for x in files),
                     'released':(rev/'release/complete.json').is_file()}
            report=rev/'capture/report.json'
            if report.is_file():
                data=json.loads(report.read_text(encoding='utf8'));interaction=data.get('interaction',{})
                summary['interaction']={'validated':interaction.get('validated'),
                    'actions':[{k:a.get(k) for k in ('id','status','success','checks','translation_m','trajectory_file','before_image','after_image')} for a in interaction.get('action_results',[])]}
            rows.append(summary)
        result['revisions']=rows
        if stage:result['generation']=stage
        result['layout_files']=[{'file':'layout/'+p.name,'bytes':p.stat().st_size} for p in (base/'layout').glob('*') if _allowed('layout/'+p.name) and p.is_file()]
        return result
    if isinstance(file,str) and re.fullmatch(r'(?:capture|release|generation|generation_stage|layout)(?:/[a-zA-Z0-9_-]+)*',file):
        directory=(base/file if file=='layout' or file.startswith('layout/') else folder/file).resolve()
        if not directory.is_relative_to(base):raise ValueError('invalid evidence directory')
        result.update(directory=file,files=[{'file':file+'/'+p.relative_to(directory).as_posix(),'bytes':p.stat().st_size}
            for p in sorted(directory.rglob('*')) if p.is_file() and not p.is_symlink()
            and _allowed(file+'/'+p.relative_to(directory).as_posix())],
            copy_scope='directory listing only; request a listed file with workspace_id to copy it')
        return result
    if not isinstance(file,str) or not (_allowed(file) or file in stage_files):raise ValueError('only listed evidence and public export files may be read; authority answers, training answers and code are excluded')
    source=(base/file if file.startswith('layout/') else folder/file).resolve()
    if not source.is_relative_to(base) or not source.is_file():
        available=[int(p.name.split('_')[-1]) for p in base.glob('revision_*') if (p/file).is_file()]
        raise ValueError(f'{file} is absent in revision {revision}; available_revisions={sorted(available)}. Supply revision explicitly to read an earlier result.')
    result.update(file=file,bytes=source.stat().st_size,source_path=str(source))
    if re.fullmatch(r'capture/view_\d+\.png',file) and source.with_suffix('.json').is_file():
        frame=json.loads(source.with_suffix('.json').read_text(encoding='utf8'))
        result['image_context']={
            'metadata_file':str(Path(file).with_suffix('.json').as_posix()),
            'image_size':frame['image_size'],'camera':frame['camera'],
            'visible_object_columns':['object_id','label','bbox_xyxy','visible_pixels'],
            'visible_objects':[[obj['object_id'],obj['label'],obj['bbox_2d']['xyxy'],obj['mask']['area_px']]
                               for obj in frame['objects']]}
    if workspace_id is not None:
        if not isinstance(workspace_id,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}',workspace_id):raise ValueError('invalid workspace_id')
        workspaces=store.root/'operator_workspaces';workspaces.mkdir(exist_ok=True)
        workspace=workspaces/workspace_id;workspace.mkdir(exist_ok=True)
        if workspace.is_symlink() or workspace.resolve().parent!=workspaces.resolve():raise ValueError('invalid workspace path')
        # Unique copy names keep earlier evidence snapshots and generated task files intact.
        import uuid
        target=workspace/('evidence_'+uuid.uuid4().hex[:8]+'_'+source.name)
        shutil.copyfile(source,target)
        result.update(workspace_file='/workspace/'+target.name,source_path=str(target),copy_scope='task copy; original production evidence remains unchanged')
    elif source.suffix=='.json':
        if source.stat().st_size>512*1024:raise ValueError('large JSON: provide workspace_id and inspect the task copy')
        result['data']=json.loads(source.read_text(encoding='utf8'))
    elif source.suffix.lower() in {'.png','.jpg','.jpeg'}:
        result['image_path']=str(source)
    else:
        result.update(source_path=str(source),format=source.suffix.lstrip('.'))
    return result
