"""Remove cube/proxy scenes from active storage, retaining a recovery archive."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from benchforge_core.pipelines.scene_policy import classify, planned_geometry, load_policy


def write(path, value):
    pending=path.with_suffix('.pending.json')
    pending.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    pending.replace(path)


def remove(workspace, artifacts, apply=False):
    workspace,artifacts=Path(workspace).resolve(),Path(artifacts).resolve()
    library=workspace/'scene-library'
    catalog=json.loads((library/'catalog.json').read_text(encoding='utf-8'))
    removed,kept=[],[]
    for row in catalog['items']:
        source=Path(row['source_directory']).resolve()
        if not source.is_relative_to(artifacts) or source==artifacts:
            raise ValueError('Scene source is outside the configured artifact root')
        program=source/'program.json'
        if not program.is_file():program=source/'capture/program.json'
        value=json.loads(program.read_text(encoding='utf-8'))
        # Deliberately declared geometry experiments are valid scene designs.
        verdict=classify(value)
        if planned_geometry(value, load_policy(workspace)):
            from benchforge_core.pipelines.scene_policy import classify_planned
            verdict=classify_planned(value, load_policy(workspace))
        if verdict['allowed']:
            stat=program.stat()
            kept.append({**row,'scene_admission':{**verdict,'program_version':[stat.st_size,stat.st_mtime_ns]}})
        else:
            removed.append({**row,'admission':verdict,'scene_id':value.get('scene_id'),'program_path':str(program)})
    summary={'catalog_before':len(catalog['items']),'removed':len(removed),'remaining':len(kept),'apply':apply}
    if not apply:return summary
    stamp=time.strftime('%Y%m%d-%H%M%S')
    archive=library/'deleted'/('cube-scenes-'+stamp)
    archive.mkdir(parents=True,exist_ok=False)
    runtime_archive=artifacts.parent/'deleted-scenes'/('cube-scenes-'+stamp)
    runtime_archive.mkdir(parents=True,exist_ok=False)
    shutil.copy2(library/'catalog.json',archive/'catalog-before.json')
    policy_path=library/'policy.json'
    policy=json.loads(policy_path.read_text(encoding='utf-8')) if policy_path.is_file() else {}
    write(archive/'policy-before.json',policy)
    tasks={row['task_id'] for row in removed}
    # Only task folders wholly belonging to removed scenes are moved. Shared assets stay in place.
    moves=[]
    for row in removed:
        source=Path(row['source_directory']).resolve().parent
        if source.parent!=artifacts or source.name!=row['task_id']:
            raise ValueError('Refusing an unexpected task directory layout')
        target=runtime_archive/source.name
        if target.exists():raise ValueError('Recovery target already exists')
        moves.append((source,target))
    dependent=[]
    if any(str(row.get('scene_id','')).startswith('sf_e103_') or row['name'].startswith('sf_e103_') for row in removed):
        for relative in ['operations/eval100_relvis_20261103','deliverables/eval100_relpos_occlusion_20261103']:
            source=(workspace/relative).resolve()
            if not source.is_relative_to(workspace):raise ValueError('Invalid derived artifact path')
            if source.exists():dependent.append((source,archive/('derived-'+source.name)))
    policy={**policy,'schema':'benchforge.scene-policy/v1','enabled':True,'updated_at':time.time(),
            'reason':'用户要求删除立方体和几何盒替代物场景，禁止重新制造或复用。',
            'enforce_realism':True,'require_scene_brief':True,
            'require_program_before_submission':True,
            'excluded_tasks':sorted(set(policy.get('excluded_tasks',[]))|tasks),
            'excluded_runs':sorted(set(policy.get('excluded_runs',[]))|({row['run_id'] for row in removed}-{row['run_id'] for row in kept})),
            'excluded_scene_groups':sorted(set(policy.get('excluded_scene_groups',[]))|
                {'scene-v1:'+name for row in removed for name in (row.get('scene_id'),row.get('name')) if name}),
            'excluded_paths':sorted(set(policy.get('excluded_paths',[]))|{str(source) for source,_ in [*moves,*dependent]}|{str(archive),str(runtime_archive)}),
            'archive':str(archive)}
    write(archive/'manifest.json',{'summary':summary,'removed':removed,'moves':[{'source':str(a),'archive':str(b)} for a,b in [*moves,*dependent]],'state':'prepared'})
    # Tombstones first: a concurrent catalog refresh must not resurrect removed records.
    write(policy_path,policy)
    write(library/'catalog.json',{**catalog,'items':kept,'updated_at':time.time()})
    selections=0
    selection_backup=archive/'selections';selection_backup.mkdir()
    for path in (library/'selections').glob('session-*.json'):
        saved=json.loads(path.read_text(encoding='utf-8'));selected=[row for row in saved['selected'] if row['id'] not in tasks]
        if selected!=saved['selected']:
            shutil.copy2(path,selection_backup/path.name)
            write(path,{**saved,'selected':selected,'version':saved['version']+1,'updated_at':time.time(),
                        'notice':'立方体场景已按要求删除，请选择合格场景。'})
            selections+=1
    moved=[]
    try:
        for source,target in [*moves,*dependent]:
            if source.exists():source.rename(target);moved.append((source,target))
    except Exception:
        # Keep exclusions active while restoring source bytes for operator recovery.
        for source,target in reversed(moved):target.rename(source)
        write(archive/'failure.json',{'moved_back':True,'policy_remains_active':True})
        raise
    summary.update(archive=str(archive),runtime_archive=str(runtime_archive),selections_updated=selections,
                   task_directories_moved=len(moves),derived_directories_moved=len(dependent),state='removed_from_active_storage')
    write(archive/'receipt.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--artifacts',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(remove(args.workspace,args.artifacts,args.apply),ensure_ascii=False))
