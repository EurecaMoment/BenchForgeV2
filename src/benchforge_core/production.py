"""Reusable compilation, pilot screening and synthesis using migrated algorithms."""
from __future__ import annotations
import importlib.util
import json
import shutil
from collections import Counter
from pathlib import Path
from .artifacts import BUILD, COMPILER, read, rows, write, jsonl, run


def algorithm(name):
    matches=list(BUILD.rglob(name))
    if len(matches)!=1:
        raise RuntimeError(f'Bundled algorithm unavailable: {name}')
    return matches[0]


def kinship(args, directory, config):
    source=Path(args['input']).resolve()
    if not source.is_file():
        raise ValueError('Provide the normalized evidence JSONL, not an unbounded directory scan.')
    bundle=Path(args.get('bundle',directory/'bundle')).resolve()
    out=directory/'gt_kinship'
    run(algorithm('generate_gt_kinship.py'), ['--workspace-root',directory,'--bundle-dir',bundle,
        '--output-dir',out,'--input-root',source,'--max-records-per-file',args.get('max_records',5000),
        '--max-kinship-pairs',args.get('max_pairs',5000)],directory,config=config)
    return {'kinship':str(out),'graph':str(out/'gt_kinship_graph.json'),
            'note':'Graph proximity and difficulty support are diagnostics; neither proves answerability nor supplies new GT.'}


def images(args,directory,config):
    bundle=Path(args['bundle']).resolve()
    out=bundle/'image_processing'
    argv=['--bundle',bundle,'--evidence-index',args.get('input',bundle/'evidence_index.jsonl'),'--out',out]
    if args.get('requests'):argv+=['--image-requests',args['requests']]
    run(algorithm('process_answer_images.py'),argv,directory,config=config)
    # The compiler consumes this exact manifest, not an unconnected inspection copy.
    destination=bundle/'image_processing'
    manifest=rows(destination/'image_manifest.jsonl')
    return {'manifest':str(destination/'image_manifest.jsonl'),'images':len(manifest),'report':str(out/'image_processing_report.json')}


def compile_bundle(args,directory,config):
    source=Path(args['input']).resolve()
    evidence=rows(source)
    if not evidence:raise ValueError('No evidence to compile')
    for row in evidence:
        origin=row.get('provenance',{}).get('kind',row.get('source_type',''))
        if origin not in ('official','simulation','human','program'):
            raise ValueError('Compilation requires original/human/simulator/program evidence. Annotation predictions need independent authority; do not relabel them.')
    bundle=directory/'bundle'
    run(algorithm('build_parent_runtime_bundle.py'),['--input',source,'--bundle',bundle],directory,config=config)
    shutil.copyfile(bundle/'evidence_index.jsonl',bundle/'input_evidence.jsonl')
    shutil.copyfile(Path(__file__).with_name('replay.py'),bundle/'scripts/replay_native_depth.py')
    if args.get('adapter'):
        # An explicit dataset adapter is retained as reviewable code in the portable bundle.
        adapter=Path(args['adapter']).resolve()
        shutil.copyfile(adapter,bundle/'scripts/dataset_adapter.py')
        run(bundle/'scripts/dataset_adapter.py',['--input',bundle/'evidence_index.jsonl','--out',bundle/'adapted.jsonl'],directory,config=config)
        shutil.copyfile(bundle/'adapted.jsonl',bundle/'evidence_index.jsonl')
        evidence=rows(bundle/'evidence_index.jsonl')
    kinship({'input':str(bundle/'evidence_index.jsonl'),'bundle':str(bundle)},directory,config)
    image_result=images({'bundle':str(bundle), **({'requests':args['image_requests']} if args.get('image_requests') else {})},directory,config)
    manifest=rows(bundle/'template_manifest.jsonl')
    if args.get('templates'):
        selected=rows(args['templates']) if isinstance(args['templates'],str) else args['templates']
        available={t['template_id']:t for t in manifest}
        if all(isinstance(t,str) for t in selected):
            unknown=set(selected)-set(available)
            if unknown:raise ValueError(f'Unknown templates: {sorted(unknown)}')
            manifest=[{**t,'status':'enabled' if t['template_id'] in selected else 'disabled',
                       'disable_reason':'' if t['template_id'] in selected else 'not_requested'} for t in manifest]
        else:
            manifest=selected
    if args.get('recipes'):
        manifest=rows(args['recipes']) if isinstance(args['recipes'],str) else args['recipes']
        for template in manifest:
            template['implementation_hint']='declarative_answer_program'
            template['gt_rule']=json.dumps(template['answer_program'],ensure_ascii=False)
            template.setdefault('status','enabled')
        shutil.copyfile(Path(__file__).with_name('recipes.py'),bundle/'scripts/generate_items.py')
    enabled=[t for t in manifest if t.get('status','enabled')=='enabled']
    if not enabled:raise ValueError('At least one executable template is required')
    required=('template_id','difficulty_level','answer_type','metric_id','gt_rule','implementation_hint')
    for t in enabled:
        if t.get('requires_overlay'):
            t.setdefault('required_visible_transform','bbox_label_overlay')
            t.setdefault('visible_anchor_source','bbox_label_overlay')
        missing=[key for key in required if not t.get(key)]
        if missing:raise ValueError(f'Template contract missing {missing}')
        if 'depth' in ' '.join(t.get('required_evidence_fields',[])).lower():
            if not all(row.get('depth_semantics')=='euclidean_range' for row in evidence):
                t['status']='disabled';t['disable_reason']='camera range semantics/calibration missing; convert native Z before depth templates'
    jsonl(bundle/'template_manifest.jsonl',manifest)
    if args.get('spec'):
        from .research import design
        validated=design({'spec':args['spec']},directory/'design',config)
        spec=read(validated['spec'])
        bindings={t['id']:t for t in spec['templates']}
        for template in manifest:
            if template.get('status')!='enabled':continue
            binding=bindings.get(template['template_id'])
            if not binding or binding['metric']!=template['metric_id']:
                raise ValueError('Compiled templates must bind to the supplied design and metric IDs')
            template['capability_tags']=binding['capabilities']
        jsonl(bundle/'template_manifest.jsonl',manifest)
        shutil.copytree(directory/'design',bundle/'design',dirs_exist_ok=True)
    write(bundle/'contrib/template_registry/template_registry.json',{'templates':manifest})
    metrics=[{'template_id':t['template_id'],'answer_type':t['answer_type'],'metric_id':t['metric_id'],
              'primary_metric':True,'deterministic':True} for t in manifest if t.get('status')=='enabled']
    jsonl(bundle/'metric_manifest.jsonl',metrics)
    write(bundle/'contrib/metric_registry/metric_registry.json',{'metrics':metrics,'scorer_cli':'scripts/score_predictions.py'})
    if args.get('generator'):
        shutil.copyfile(Path(args['generator']).resolve(),bundle/'scripts/generate_items.py')
    # Use the same declared metrics for both installed and standalone evaluation.
    for src,dest in [('evaluation.py','score_predictions.py'),('artifacts.py','artifacts.py')]:
        shutil.copyfile(Path(__file__).with_name(src),bundle/'scripts'/dest)
    # Policy is a requested design property, not a claim of measured human difficulty.
    policy=args.get('difficulty',{'minimum_ratios':{},'unknown_difficulty_allowed':False})
    write(bundle/'difficulty_mix_contract.json',policy)
    write(bundle/'collection_contract.json',args.get('collection',{}))
    write(bundle/'compiler_contract.json',{'input':str(source),'templates':'template_manifest.jsonl',
        'metrics':'metric_manifest.jsonl','images':'image_processing/image_manifest.jsonl',
        'kinship':'gt_kinship/gt_kinship_graph.json','source_kind_counts':dict(Counter(r.get('provenance',{}).get('kind',r.get('source_type')) for r in evidence)),
        'generated_by_model':bool(args.get('generator')),'status':'compiled_requires_pilot'})
    # Put the real kinship output under the contributor path consumed by the bundle.
    shutil.copytree(directory/'gt_kinship',bundle/'gt_kinship',dirs_exist_ok=True)
    return {'bundle':str(bundle),'enabled':[t['template_id'] for t in manifest if t.get('status')=='enabled'],
            'disabled':[{'id':t['template_id'],'reason':t.get('disable_reason')} for t in manifest if t.get('status')!='enabled'],
            'images':image_result,'next':'Run synthesize in pilot mode, inspect actual images, then scale accepted templates.'}


def screen(args,directory,config):
    run(algorithm('screen_invalid_items.py'),['--items',args['items'],'--out-dir',directory,
        '--workspace-root',args.get('bundle',Path(args['items']).resolve().parent)],directory,config=config,accepted=(0,1))
    report=read(directory/'screening_report.json')
    return {'valid_items':str(directory/'valid_items.jsonl'),'invalid_items':str(directory/'invalid_items.jsonl'),'report':report}


def synthesize(args,directory,config):
    bundle=Path(args['bundle']).resolve()
    input_path=Path(args.get('input',bundle/'evidence_index.jsonl')).resolve()
    output=directory/'generated_items.jsonl'
    argv=['--bundle',bundle,'--evidence-index',input_path,'--out',output,'--limit',args.get('limit',32),
          '--seed',args.get('seed',42),'--filtered-output',directory/'filtered_items.jsonl']
    if args.get('template_id'):argv+=['--template-id',args['template_id']]
    run(bundle/'scripts/generate_items.py',argv,directory,config=config,timeout=args.get('timeout_seconds',600))
    from .replay import replay
    replayed=replay(bundle)
    write(directory/'native_replay.json',replayed)
    if replayed['errors']:raise ValueError('Native depth oracle replay failed; source measurements may have drifted')
    screened=screen({'items':str(output),'bundle':str(bundle)},directory/'screening',config)
    valid=rows(screened['valid_items'])
    if not valid:raise ValueError(f'All generated items were rejected; see {directory}/screening')
    from .collection import assess
    policy_path=bundle/'collection_contract.json'
    quality=assess(valid,read(policy_path) if policy_path.exists() else {})
    write(directory/'collection_quality.json',quality)
    if quality['failures'] and args.get('mode','pilot')=='full':
        raise ValueError(f'Collection policy failed: {quality["failures"]}')
    distribution=Counter(r.get('difficulty_level','unknown') for r in valid)
    requirements=read(bundle/'difficulty_mix_contract.json').get('minimum_ratios',{})
    unmet={k:v for k,v in requirements.items() if distribution[k]/len(valid)<v}
    write(directory/'difficulty_mix_report.json',{'counts':dict(distribution),'minimum_ratios':requirements,'unmet':unmet,'status':'fail' if unmet else 'pass','interpretation':'declared template complexity, not fitted item difficulty'})
    if unmet and args.get('mode','pilot')=='full':raise ValueError(f'Requested difficulty allocation not met: {unmet}')
    # Validate the supplied scorer with positive, negative and missing-prediction controls.
    from .evaluation import score_predictions
    perfect=[{'id':r.get('item_id',r.get('id')),'answer':r['answer']} for r in valid]
    negative=[{'id':p['id'],'answer':'__invalid_answer__'} for p in perfect]
    selftests={name:score_predictions(valid,pred) for name,pred in [('perfect',perfect),('negative',negative),('missing',[])]}
    write(directory/'scorer_controls.json',selftests)
    if selftests['perfect']['overall']['score']!=1 or selftests['negative']['overall']['score']>=1:
        raise ValueError('Deterministic scorer controls failed')
    # Check the actual generated scorer as well as the core scorer; mismatched contracts fail.
    for name,pred in [('perfect',perfect),('negative',negative)]:
        prediction_file=directory/(name+'.jsonl');jsonl(prediction_file,pred)
        run(bundle/'scripts/score_predictions.py',['--items',screened['valid_items'],'--predictions',prediction_file,
            '--out',directory/(name+'-generated-score.json')],directory,config=config,name=name+'-generated-scorer')
        actual=read(directory/(name+'-generated-score.json'))['overall']['score']
        if actual!=selftests[name]['overall']['score']:
            raise ValueError('Packaged scorer does not match installed scorer')
    result={'items':screened['valid_items'],'count':len(valid),'rejected':len(rows(screened['invalid_items'])),
            'collection':quality,
            'difficulty':dict(distribution),'mode':args.get('mode','pilot'),'scorer_controls':str(directory/'scorer_controls.json'),
            'templates':dict(Counter(r.get('template_id') for r in valid))}
    if args.get('package',True):
        from .evaluation import package
        result.update(package({'items':screened['valid_items'],'bundle':str(bundle)},directory/'release',config))
    return result


def diagnose(args,directory,config):
    paths=args['scores'] if isinstance(args['scores'],list) else [args['scores']]
    argv=['--out-dir',directory]
    for path in paths:argv+=['--scores',Path(path).resolve()]
    if args.get('items'):argv+=['--items',Path(args['items']).resolve()]
    run(algorithm('cdm_irt_analysis.py'),argv,directory,config=config)
    return {'summary':read(directory/'cdm_irt_summary.json'),'directory':str(directory),
            'interpretation':'Migrated Rasch-style proxy / capability diagnostics, not a full statistical IRT fit. Small matrices remain explicitly limited.'}
