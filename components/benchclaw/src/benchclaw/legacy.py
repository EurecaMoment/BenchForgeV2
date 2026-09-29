"""Strict adapters for existing annotation services; services are never auto-started."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from pydantic import Field,model_validator

from .domain import Contract, HarnessError, HealthResult, Nonempty, Resources
from .plugins import EntitySource, EntitySourceParameters
from .store import safe_path


class AnnotationParameters(EntitySourceParameters):
    interpreter: str
    vlm_model: Nonempty
    max_vlm_terms: int = Field(default=24,ge=2,le=100)
    da3_process_res: int = Field(default=1024,ge=256,le=2048)
    vlm_base_url: str = 'http://127.0.0.1:9001'
    vlm_generation: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_vlm(self):
        from .local_agent import LocalModel
        allowed={'max_tokens','timeout_seconds','enable_thinking','preserve_thinking','reasoning_effort',
                 'thinking_token_budget','temperature','top_p','top_k','min_p','presence_penalty','repetition_penalty','stream'}
        if set(self.vlm_generation)-allowed:raise ValueError('Unsupported annotation model generation setting')
        LocalModel(model_id=self.vlm_model,endpoint=self.vlm_base_url+'/v1/chat/completions',**self.vlm_generation)
        return self


def get_json(url):
    with build_opener(ProxyHandler({})).open(url,timeout=3) as response:
        return json.load(response)


def annotation_readiness(vlm_model,vlm_base_url='http://127.0.0.1:9001'):
    checks=[('sam3','http://127.0.0.1:8765/health',lambda p:p.get('ok') is True and p.get('image_runtime_loaded') is True),
            ('yoloe','http://127.0.0.1:8766/health',lambda p:p.get('ok') is True and p.get('mobileclip_ready') is True and Path(p.get('default_checkpoint','/nonexistent')).is_file()),
            ('depthanything3','http://127.0.0.1:8008/status',lambda p:p.get('model_loaded') is True),
            ('vlm',vlm_base_url+'/v1/models',lambda p:vlm_model in [x.get('id') for x in p.get('data',[])])]
    for name,url,check in checks:
        try:
            payload=get_json(url)
            if not check(payload):
                return HealthResult(ready=False,code='SERVICE_NOT_READY',message=f'{name} did not confirm model readiness')
        except Exception as exc:
            return HealthResult(ready=False,code='SERVICE_UNAVAILABLE',message=f'{name}: {type(exc).__name__}')
    return HealthResult(ready=True,message='SAM3 loaded; YOLOE assets present; DA3 loaded; VLM model listed. Functional inference runs inside the task.')


class DefaultAnnotationSource(EntitySource):
    plugin_id='source.default_annotation'
    description='Existing VLM + YOLOE + SAM3 + DA3 pipeline, controlled output directory, strict readiness and no service autostart'

    def describe(self):
        return super().describe().model_copy(update={'resources':Resources(cpu=1,gpu=1,memory_gb=4)})

    def validate_parameters(self,parameters):
        p=AnnotationParameters.model_validate(parameters)
        if not Path(p.interpreter).is_absolute():
            raise HarnessError('INTERPRETER_PATH','Use an explicit annotation Python executable')
        if p.producer_type!='model' or p.review_status!='needs_human_review':
            raise HarnessError('ANNOTATION_REVIEW','New model annotations require review; do not self-approve')

    def healthcheck(self,parameters):
        p=AnnotationParameters.model_validate(parameters)
        if not Path(p.interpreter).is_file():
            return HealthResult(ready=False,code='INTERPRETER_MISSING',message='Annotation interpreter unavailable')
        try:
            safe_path(Path(p.path),p.image,True)
        except HarnessError as exc:
            return HealthResult(ready=False,code=exc.failure.code,message=str(exc))
        return annotation_readiness(p.vlm_model,p.vlm_base_url)

    def execute(self,ctx,unit):
        p=AnnotationParameters.model_validate(unit.parameters)
        root=Path(__file__).resolve().parents[2]
        script=root/'BenchClaw/annotation-tool/default-annotation/run_image_to_semantic_depth.py'
        output=ctx.output_dir/'annotation'
        image=safe_path(Path(p.path),p.image,True)
        env={**os.environ,'BENCHCLAW_NO_AUTOSTART':'1','BENCHCLAW_ROOT':str(root/'BenchClaw'),
             'LLM_MODEL_ID':p.vlm_model,'LLM_BASE_URL':p.vlm_base_url,'BENCHCLAW_DISABLE_THINKING':'1',
             'SAM3_HOST':'127.0.0.1','SAM3_PORT':'8765','YOLOE_SERVICE_HOST':'127.0.0.1','YOLOE_SERVICE_PORT':'8766',
             'DEPTHANYTHING3_HOST':'127.0.0.1','DEPTHANYTHING3_PORT':'8008'}
        if p.vlm_generation:
            from .chat_transport import generation_payload
            payload=generation_payload({'model_id':p.vlm_model,'max_tokens':32000,**p.vlm_generation})
            env['BENCHCLAW_VLM_GENERATION']=json.dumps(payload)
            env['BENCHCLAW_VLM_TIMEOUT']=str(p.vlm_generation.get('timeout_seconds',600))
        for key,relative in [('SAM3_CLIENT','sam3/sam3_client.py'),('YOLOE_CLIENT','yoloe/yoloe_client.py'),
                             ('DA3_CLIENT','depthanything3/depthanything3_client.py'),('LLM_CLIENT','llm-local/llm_local_client.py')]:
            env[key]=str(root/'BenchClaw/annotation-tool'/relative)
        with (ctx.output_dir/'annotation.log').open('w') as log:
            result=subprocess.run([p.interpreter,str(script),'--image',str(image),'--out-dir',str(output),
                                   '--max-vlm-terms',str(p.max_vlm_terms),'--da3-process-res',str(p.da3_process_res),
                                   '--min-question-confidence','0.5'],
                                  cwd=ctx.output_dir,env=env,stdout=log,stderr=log,timeout=unit.retry.timeout_seconds-1)
        if result.returncode:
            raise HarnessError('ANNOTATION_EXIT',f'Annotation process exited {result.returncode}')
        # Validate outputs, not just the child process exit code.
        import numpy as np
        from PIL import Image
        result_json=json.loads(safe_path(output,'result.json',True).read_text())
        from .store import write_json
        usage=result_json.get('vision_llm',{}).get('usage')
        write_json(output/'model_usage.json',{'model_id':p.vlm_model,'phase':'annotation','requests':1,
            'usage':usage,'usage_complete':usage is not None,'note':'A stream stopped after enough candidates may have no final token usage; unknown is not zero.'})
        if result_json['depth_anything_3']['depth_available'] is not True:
            raise HarnessError('DEPTH_MISSING','Annotation pipeline produced no depth')
        entities=json.loads(safe_path(output,'entity_annotations.json',True).read_text())
        width,height=entities['image_size']['width'],entities['image_size']['height']
        depth=np.load(safe_path(output,'depth.npy',True),allow_pickle=False)
        if depth.shape!=(height,width) or not np.isfinite(depth).all() or not np.any(depth>0):
            raise HarnessError('DEPTH_INVALID','Depth must match RGB dimensions and contain finite, positive estimates')
        if not entities['objects']:
            raise HarnessError('ANNOTATION_EMPTY','No entities produced')
        for obj in entities['objects']:
            raw=obj['mask']['path']
            path=Path(raw)
            if path.is_absolute():
                try:
                    raw=path.relative_to(output).as_posix()
                except ValueError:
                    raise HarnessError('MASK_PATH_ESCAPE',obj['object_id'])
            with Image.open(safe_path(output,raw,True)) as mask:
                mask.load()
                if mask.size!=(width,height) or not np.any(np.asarray(mask)):
                    raise HarnessError('MASK_INVALID','Empty or misaligned mask')
        # Explicit migration to 2D contracts. Approximate DA3 intrinsics/depth are retained
        # as private legacy artifacts and are never promoted to metric 3D ground truth.
        import shutil
        copy=safe_path(output,p.image)
        copy.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(image,copy)
        parameters={k:v for k,v in p.model_dump().items() if k not in {'interpreter','vlm_model','max_vlm_terms','da3_process_res','vlm_base_url','vlm_generation'}}
        parameters.update(path=str(output),annotations='entity_annotations.json')
        migrated=EntitySourceParameters.model_validate(parameters)
        migrated_result=EntitySource.execute(self,ctx,unit.model_copy(update={'parameters':migrated.model_dump(mode='json')}))
        records=[r.model_copy(update={'data':{**r.data,'depth_validated':True}}) for r in migrated_result.bundle.records]
        migrated_result=migrated_result.model_copy(update={'bundle':migrated_result.bundle.model_copy(update={'records':records})})
        # Legacy output embeds absolute attempt paths. Make private sidecars portable
        # before the atomic directory rename, retaining external source provenance.
        def relative_paths(value):
            if isinstance(value,dict):
                return {k:relative_paths(v) for k,v in value.items()}
            if isinstance(value,list):
                return [relative_paths(v) for v in value]
            if isinstance(value,str) and value.startswith(str(ctx.output_dir)+'/'):
                return Path(value).relative_to(ctx.output_dir).as_posix()
            return value
        for sidecar in output.rglob('*.json'):
            content=json.loads(sidecar.read_text())
            sidecar.write_text(json.dumps(relative_paths(content),ensure_ascii=False,indent=2))
        from .domain import DataFile
        files=[]
        for index,path in enumerate(sorted(output.rglob('*'))):
            if not path.is_file() or not path.stat().st_size:continue
            kind='usage' if path.name=='model_usage.json' else 'depth' if path.suffix=='.npy' else 'pointcloud' if path.suffix in {'.glb','.ply'} else 'mask' if 'mask' in path.name else 'metadata'
            files.append(DataFile(file_id=unit.task_id+f'_file_{index:05}',uri=path.relative_to(ctx.output_dir).as_posix(),
                                  kind=kind,byte_size=path.stat().st_size,source_uri=p.source_uri))
        records=[r.model_copy(update={'data':{**relative_paths(r.data),'file_refs':[f.file_id for f in files]}}) for r in records]
        return migrated_result.model_copy(update={'bundle':migrated_result.bundle.model_copy(update={'records':records,'files':files})})
