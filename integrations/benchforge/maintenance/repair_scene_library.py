"""Evidence-led repair of existing real scenes, with durable briefs and retries.

Uses the configured scene authoring model and the existing Isaac queue. Model
opinions never create physics evidence or change the original requirements.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import base64
import urllib.request
import urllib.error


def author_completion(prompt, directory, images, max_tokens=14000):
    """Bounded authoring request; does not alter the model or its service."""
    import os
    from benchforge_backend.model import _json_text, model_request_headers
    directory.mkdir(parents=True, exist_ok=True)
    saved = directory / 'response.json'
    if saved.is_file():return _json_text(json.loads(saved.read_text())['content'])
    content=[{'type':'text','text':prompt}]
    for file in images:
        content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(file.read_bytes()).decode()}})
    body={'model':os.environ['BENCHFORGE_MODEL_ID'],'messages':[{'role':'user','content':content}],
          'max_tokens':max_tokens,'temperature':.2,'stream':False,
          'chat_template_kwargs':{'enable_thinking':False},'reasoning_effort':'none'}
    save(directory/'request.json', {**body,'messages':[{'role':'user','content':prompt}],'image_files':[str(p) for p in images]})
    base=os.environ['BENCHFORGE_MODEL_URL'].rstrip('/')
    url = base if base.endswith('/chat/completions') else base + '/chat/completions'
    request=urllib.request.Request(url,data=json.dumps(body).encode(),headers=model_request_headers())
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=420) as response:result=json.load(response)
    message=result['choices'][0];save(saved,{'content':message['message']['content'],'finish_reason':message['finish_reason'],'usage':result.get('usage')})
    if message['finish_reason']!='stop':raise ValueError('Scene authoring response incomplete; preserve it and retry a compact revision')
    return _json_text(message['message']['content'])


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.pending.json')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def raise_service_error(route, error):
    detail=error.read().decode()[:2500]
    try:kind=json.loads(detail).get('error')
    except (ValueError,AttributeError):kind=None
    if kind in {'TimeoutError','URLError','ConnectionError','OSError'}:
        raise OSError(route+': '+detail) from error
    raise ValueError(route+': '+detail) from error


def repair_baseline(row, folder, attempt=0, feedback=None):
    """Use the captured predecessor rather than an obsolete authoring draft."""
    source=Path(row['source_directory'])
    context=Path(feedback['directory']) if feedback and feedback.get('directory') else source
    previous=folder/('attempt_'+str(attempt-1))/'program.json'
    program_path=context/'program.json' if feedback and (context/'program.json').is_file() else previous if attempt and previous.is_file() else source/'program.json'
    brief_path=context/'scene_brief.json'
    frozen=json.loads(brief_path.read_text()) if brief_path.is_file() else {}
    return program_path,context,frozen


def revise(config, row, folder, attempt=0, feedback=None):
    from benchforge_backend.engine import apply_scene_replacements
    from benchforge_backend.contracts import ASSETS, SCENE_SCHEMA_DESCRIPTION, validate_program
    from benchforge_backend.scene_acceptance import admit_program
    from benchforge_backend.scene_design import validate_scene_brief
    source = Path(row['source_directory'])
    program_path,context,frozen=repair_baseline(row,folder,attempt,feedback)
    program = json.loads(program_path.read_text())
    work = folder / ('attempt_' + str(attempt));work.mkdir(parents=True, exist_ok=True)
    baseline_file = folder / 'original_requirements.json'
    if not baseline_file.exists():
        frozen_file=source/'scene_brief.json'
        frozen=json.loads(frozen_file.read_text()) if frozen_file.is_file() else {}
        requirements=list(dict.fromkeys([*frozen.get('hard_requirements',[]),
            '保留本场景原有的真实用途、主要家具或工具及整体风格，使用真实可辨识的资产。',
            '修复悬空、倾倒、支撑和穿插错误，保证合理比例、取用空间、通行空间和物体使用关系。',
            '不得将场景降级为方块替代物；不能通过改写摘要免除原始要求，所有变更保留依据。']))
        save(baseline_file, {'source_task': row['id'], 'source_name': row['name'], 'requirements': requirements})
    original = json.loads(baseline_file.read_text())
    protected=list(dict.fromkeys([*original['requirements'],*frozen.get('hard_requirements',[])]))
    images = sorted((context / 'capture').glob('view_*.png'))
    if len(images) > 4:images = [images[i * (len(images) - 1) // 3] for i in range(4)]
    try:admit_program(config['artifacts'], program);diagnostic = 'admission passed; inspect spatial relationships in actual images'
    except (ValueError, OSError) as error:diagnostic = str(error)
    prompt = '''你是场景制作与空间布局修复者。使用所附实际场景图片、原始完整程序、物理/几何反馈，修复真实场景中不合生活常识或物理逻辑的关系，同时保留用途、主要物体和风格。不要泛泛而谈，不准改服务或降低验收标准。
返回严格 JSON：{"brief":{"name":"中文标题","summary":"200到400字的完整场景段落，描述用途、空间、主要物体、朝向、支撑、照明、动线及取用关系","hard_requirements":[原始硬要求逐字保留],"object_roles":[{"object_id":"真实id","role":"用途与位置关系"}],"relations":[{"source":"id","type":"supported_by|mounted_to|clearance|near|facing|inside","target":"id或ground","description":"明确关系及理由"}],"physical_assumptions":["仿真材质、质量和安装方式的假设及验证范围"]},"changes":["引用实际视角或物理回执，说明发现及如何修改"],"unresolved":["尚未解决、需要补充机位或等待后续验证的问题；没有则返回空数组"],"evidence_refs":[{"path":"capture/view_0.png","observation":"该真实视角中的具体发现"},{"path":"capture/evidence.json","observation":"原生物理或验收回执中的具体发现"}],"replacements":[{"path":"/objects/0","value":完整物体记录}]}
replacements 使用 JSON Pointer；新增字段可以直接添加，删除物体时替换完整 /objects 列表。不可只改摘要而不改错误程序；若上一轮发现摘要遗漏，可补充或修订软设计，但保留原始硬要求，写清观察依据。不要重复已失败的方案。
默认真实资产。允许具有可辨认形态的多部件家具/工具，但单个几何包络替代家具不合格；不要把床/沙发/椅子/柜子替换成粗方块。尽可能复用现有真实 mesh，比例与朝向根据实际图像和资产尺寸判断，不要盲猜。需要时使用已注册 native 资产并采用其自然尺寸比例。没有资产时报告缺口，不虚构 asset_id。
support 引用整个父物体顶部，不是内部层板；内部层板用准确负 base_z 和真实层板几何计算。多部件整体 envelope 可能大于实际零件高度，须按实际接触面设偏移。桌面物品和书架摆件应清楚支撑，不能穿进桌面或漂浮。不要把桌上物体放在座椅/柜体内部。
地面和墙体保留实际厚度和合理位置。悬挂/壁挂静态物应在 metadata.spatial_attachment 显式写 {target:实际墙或顶棚id,method:"static_mount",axis:0|1|2,object_face:"min"|"max",target_face:相反面}，并真正贴合相应表面（不能只写metadata）；这仅代表静态固定安装，不能冒充动态物理实测。放置地面的物体实际底部贴地。
家具面向用途：沙发/椅子朝向桌面或活动区，窗与墙洞一致，柜门、座椅使用空间、走道不得被遮挡；不必要的重复残次小装饰可在changes说明后整理，不能删掉主要物体以绕过修复。不要引入不可用的外部依赖。
动态物体显式 physics:{static_friction:0.6,dynamic_friction:0.5,restitution:0.05,mass_source:"synthetic_prior"}。保留静态建筑/家具及固定安装，不需要把所有物体改为动态。
实际图中物体已翻倒时修正资产姿态或换正确资产；检查椅背、桌腿、抽屉、工具头部等身份特征。仅依据AABB不能声称精确接触或mesh穿插。
'''
    prompt += '\n原始及已冻结硬要求：' + json.dumps(protected, ensure_ascii=False)
    prompt += '\n前次反馈：' + json.dumps(feedback, ensure_ascii=False)
    prompt += '\n入队诊断：' + diagnostic
    prompt += '\n可用 native 资产：' + json.dumps({k: {'size': v['size']} for k, v in ASSETS.items()})
    prompt += '\n原始完整程序：' + json.dumps(program, ensure_ascii=False)
    prompt += '\n执行合同：保留未修改字段；新增字段只能使用上述支持的字段，物体 id 唯一，尺寸为米，base_z 相对于所选支撑面顶部。输出要紧凑，只返回必要字段修改。'
    last_error = None
    for trial in range(3):
        result = author_completion(prompt + ('\n上次候选不符合合同：' + str(last_error) if last_error else ''),
                            work / ('bounded_author_' + str(trial)), images)
        try:
            # Models sometimes cite the right object but an obsolete list index.
            # Bind whole-object replacements to its exact existing identity.
            for replacement in result.get('replacements', []):
                path = replacement.get('path', '')
                value = replacement.get('value')
                if path.startswith('/objects/') and path.count('/') == 2 and isinstance(value, dict) and value.get('id'):
                    indices = [i for i, obj in enumerate(program['objects']) if obj['id'] == value['id']]
                    if len(indices) == 1:replacement['path'] = '/objects/' + str(indices[0])
            candidate = apply_scene_replacements(program, result)
            available_assets = {obj.get('asset_id') for obj in program['objects'] if obj.get('asset_id')}
            for obj in candidate['objects']:
                if obj.get('kind') == 'mesh' and obj.get('asset_id') not in available_assets:
                    raise ValueError('Use an existing source asset or registered native asset; unknown mesh requested: ' + str(obj.get('asset_id')))
            brief = result['brief'];brief['id'] = 'repair_design'
            brief['hard_requirements'] = deepcopy(protected)
            validate_scene_brief(brief, {obj['id'] for obj in candidate['objects']})
            prior_history=deepcopy(frozen.get('revision_history',[]))
            previous_plan=folder/('attempt_'+str(attempt-1))/'scene-plan.json'
            if attempt and not prior_history:
                if previous_plan.is_file():prior_history=json.loads(previous_plan.read_text())['assessment']['scenes']['designs'][0].get('revision_history',[])
            if not prior_history and (source/'scene_brief.json').is_file():
                prior_history=json.loads((source/'scene_brief.json').read_text()).get('revision_history',[])
            next_revision=(prior_history[-1].get('revision',0)+1) if prior_history else 1
            brief['revision_history'] = [*prior_history, {'revision': next_revision, 'changes': result.get('changes', []),
                                          'evidence_directory': str(context), 'evidence_refs': result.get('evidence_refs', []),
                                          'unresolved': result.get('unresolved'),
                                          'previous_attempt': attempt or None}]
            if (context/'scene_brief.json').is_file():brief['previous_capture_directory']=str(context)
            plan_file = work / 'scene-plan.json'
            save(plan_file, {'assessment': {'schema': 'benchforge.assessment/v1', 'scenes': {'designs': [brief]}}})
            candidate['title'] = brief['name']
            provenance = candidate.setdefault('provenance', {})
            provenance['sources'] = [r for r in provenance.get('sources', []) if not isinstance(r, dict) or r.get('kind') != 'scene_plan']
            provenance['sources'].append({'kind': 'scene_plan', 'path': str(plan_file), 'scene_design_id': 'repair_design'})
            validate_program(candidate)
            admission = admit_program(config['artifacts'], candidate)
            save(work / 'program.json', candidate)
            record = {'state': 'planned', 'source_id': row['id'], 'name': brief['name'], 'attempt': attempt,
                      'program_path': str(work / 'program.json'), 'plan_path': str(plan_file),
                      'changes': result.get('changes', []), 'admission': admission, 'updated_at': time.time()}
            from benchforge_core.stage_review import review
            record['stage_review'] = review(config['_workspace'], config['_session'], 'open', stage='S1',
                key='scene-repair:' + row['id'] + ':' + str(attempt), artifact=str(plan_file))
            save(folder / 'status.json', record)
            return record
        except (ValueError, KeyError, OSError, TypeError) as error:last_error = str(error)
    raise ValueError('Candidate still fails authoring admission: ' + str(last_error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True);parser.add_argument('--workspace', required=True)
    parser.add_argument('--directory', required=True);parser.add_argument('--action', choices=('plan', 'execute'), required=True)
    parser.add_argument('--session', default='session-967ca06a-3c82-4371-b91a-e2c6fc337707')
    parser.add_argument('--ids', nargs='*');args = parser.parse_args()
    from benchforge_backend.runtime_config import load_service_config
    config = load_service_config(args.config);workspace = Path(args.workspace);root = Path(args.directory)
    config['_workspace'] = str(workspace);config['_session'] = args.session
    root.mkdir(parents=True, exist_ok=True)
    targets_file = root / 'targets.json'
    if targets_file.exists():targets = json.loads(targets_file.read_text())
    else:
        catalog = json.loads((workspace / 'scene-library/catalog.json').read_text())['items']
        targets = [r for r in catalog if (r['id'] in args.ids if args.ids else any(k in r['name'].lower() for k in
                   ('midcentury', 's06_q', 'livingroom', 'home_study', 'plant_care', 'garden_tool_workbench')))]
        save(targets_file, targets)
    if args.action == 'plan':
        def plan_one(row):
            folder = root / row['id']
            existing = folder / 'status.json'
            if existing.is_file() and json.loads(existing.read_text()).get('state') in {'planned','capturing','accepted','needs_repair'}:return
            try:revise(config, row, folder)
            except Exception as error:
                # A slow author request must not overwrite a newer saved plan.
                current=json.loads(existing.read_text()) if existing.is_file() else {}
                if current.get('state') not in {'planned','capturing','accepted','needs_repair'}:
                    save(existing, {'state': 'planning_failed', 'source_id': row['id'], 'error': str(error), 'updated_at': time.time()})
        with ThreadPoolExecutor(max_workers=3) as pool:
            for done in as_completed([pool.submit(plan_one, row) for row in targets]):done.result()
        print(json.dumps({'action': 'plan', 'targets': len(targets)}), flush=True)
        return
    from benchforge_core.service_http import post_service_json
    from benchforge_core.stage_review import review
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ui'))
    from scene_library import sync_catalog

    url = config.get('service_url') or 'http://127.0.0.1:' + str(config.get('port', 3841))
    def post(route, value):
        try:
            return post_service_json(url, route, value, token=config['operator_token'],
                                     timeout=180 if route == '/capture' else 30)
        except urllib.error.HTTPError as error:
            raise_service_error(route, error)
    repair_pool=ThreadPoolExecutor(max_workers=1)
    repairing={}
    while True:
        for source_id,future in list(repairing.items()):
            if not future.done():continue
            try:future.result()
            except Exception as error:
                status_file=root/source_id/'status.json';record=json.loads(status_file.read_text())
                if record.get('state')=='needs_repair':
                    record.update(state='failed_final',repair_error=str(error));save(status_file,record)
            repairing.pop(source_id)
        completed = 0
        outstanding=[row for row in targets if (root/row['id']/'status.json').is_file()
                     and json.loads((root/row['id']/'status.json').read_text()).get('state')=='capturing']
        # Always finish existing captures before admitting another project.
        ordered=outstanding+[row for row in targets if row not in outstanding]
        for row in ordered:
            folder = root / row['id'];status_file = folder / 'status.json'
            if not status_file.is_file():continue
            record = json.loads(status_file.read_text())
            if record['state'] in {'accepted', 'failed_final', 'planning_failed'}:
                completed += 1;continue
            if record['state']=='needs_review_recovery':
                try:
                    existing=post('/inspect',{'run_id':record['run_id']})['tasks'][0]
                    if existing['state'] in {'RUNNING','READY','PENDING','SUCCEEDED'}:
                        record['state']='capturing';save(status_file,record);continue
                    post('/retry',{'task_id':record['task_id']})
                    record['state']='capturing';record['review_transport_retries']=record.get('review_transport_retries',0)+1
                    save(status_file,record)
                except (OSError,ValueError) as error:
                    record['review_recovery_error']=str(error)
                    if 'budget exhausted' in str(error):record['state']='failed_final'
                    save(status_file,record)
                continue
            if record['state'] == 'planned':
                window = record.get('stage_review') or review(workspace, args.session, 'open', stage='S1',
                    key='scene-repair:' + row['id'] + ':' + str(record['attempt']), artifact=record['plan_path'])
                record['stage_review'] = window
                state = review(workspace, args.session, 'status', review_id=window['review_id'])
                if not state['can_continue']:
                    save(status_file, record);continue
                try:
                    # Service admission rechecks the exact saved brief before queueing.
                    recovery='-transport-'+str(record['transport_generation']) if record.get('transport_generation') else ''
                    result = post('/capture', {'request_key': 'dsh:' + args.session + ':real-scene-repair-20261104-' + row['id'] + '-' + str(record['attempt'])+recovery,
                        'scene_program_path': record['program_path'], 'name': record['name']})
                    record.update(state='capturing', run_id=result['run_id'], task_id=result['task_id'], queued_at=time.time())
                    save(status_file, record)
                except (TimeoutError,OSError) as error:
                    # Submission might have committed before transport failed.
                    # Retry the same key; never spend a scene-repair attempt.
                    record['submission_transport_error']=str(error);save(status_file,record)
                    break
                except Exception as error:
                    record.update(state='needs_repair', failure={'issues':[str(error)]})
                    save(status_file, record)
            if record['state'] == 'capturing':
                # One outstanding capture at a time: this loop owns this repair queue.
                try:snapshot = post('/inspect', {'run_id': record['run_id']})
                except (OSError, ValueError) as error:
                    save(root/'progress.json',{'state':'waiting_service','current':record['name'],
                         'error':str(error),'updated_at':time.time()});break
                task = snapshot['tasks'][0]
                if task['state'] not in {'SUCCEEDED', 'FAILED_FINAL', 'CANCELED'}:
                    save(root/'progress.json', {'state':'capturing','current':record['name'],'run_id':record['run_id'],
                         'phase':task.get('unit',{}).get('phase'),'finished':completed,'targets':len(targets),'updated_at':time.time()})
                    # Review uses the model pool, not the Isaac capture worker.
                    # Permit the next single capture while a previous one reviews.
                    if task.get('unit',{}).get('phase')=='review':continue
                    break
                directory = Path(config['artifacts']) / task['id'] / ('revision_' + str(task['unit']['revision']))
                if task['state'] == 'SUCCEEDED':
                    from benchforge_backend.scene_acceptance import require_accepted
                    require_accepted(config['artifacts'], directory)
                    from scene_preview_video import persist_preview
                    persist_preview(task['id'],task['unit']['revision'],sorted((directory/'capture').glob('view_*.png')))
                    record.update(state='accepted', repaired_directory=str(directory), completed_at=time.time())
                    record['scene_review_window'] = review(workspace, args.session, 'open', stage='S2',
                        key='scene-repair:' + row['id'], artifact=str(directory/'scene_acceptance.json'))
                    save(status_file, record)
                    repaired_file = workspace / 'scene-library/repairs.json'
                    repaired = json.loads(repaired_file.read_text()) if repaired_file.is_file() else {}
                    for original_id in [row['id'], *row.get('superseded_sources', [])]:
                        repaired[original_id] = {'task_id':task['id'], 'name':record['name'], 'evidence':str(directory),
                                                'accepted_at':time.time(), 'original_retained':True}
                    save(repaired_file, repaired)
                    # Only validated repairs supersede the preview of the flawed source.
                    sync_catalog(config, workspace/'scene-library')
                else:
                    failure = json.loads((directory/'scene_acceptance.json').read_text()) if (directory/'scene_acceptance.json').is_file() else task.get('failure')
                    transport_only=(isinstance(failure,dict) and failure.get('stage')=='capture_transport')
                    execution_failure=task.get('failure') or {}
                    review_transport=(task.get('unit',{}).get('phase')=='review' and execution_failure.get('error') in {'TimeoutError','URLError','ConnectionError','OSError','RemoteDisconnected','ConnectionResetError','ConnectionAbortedError'})
                    if review_transport:failure=execution_failure
                    record.update(state='needs_transport_recovery' if transport_only else 'needs_review_recovery' if review_transport else 'needs_repair', failure={'directory':str(directory),'issues':failure,
                        'visual_review':json.loads((directory/'scene_review.json').read_text()) if (directory/'scene_review.json').is_file() else {}})
                    save(status_file, record)
            if record['state'] == 'needs_repair':
                if record['attempt'] >= 2:
                    record['state']='failed_final';save(status_file,record);continue
                if row['id'] not in repairing:
                    repairing[row['id']]=repair_pool.submit(revise,config,row,folder,record['attempt']+1,record['failure'])
        if completed == len(targets):
            save(root/'progress.json', {'state':'finished','targets':len(targets),'updated_at':time.time()})
            break
        time.sleep(10)


if __name__ == '__main__':main()
