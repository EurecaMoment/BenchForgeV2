"""Typed simulator adapters. The common scheduler owns every capture and annotation."""
import json
import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import Field,model_validator

from .domain import Bundle,Contract,DataFile,HarnessError,HealthResult,Resources,SourceRecord,WorkResult,WorkUnit
from .plugins import Plugin
from .sources import ImportParameters,add_image
from .store import safe_path


class CaptureParameters(Contract):
    interpreter:str
    scene:str=''
    dataset:str=''
    suite:str='libero_10'
    task_id:int=Field(default=0,ge=0)
    demo:str='demo_0'
    frames:int=Field(default=50,ge=1,le=10000)
    width:int=Field(default=320,ge=64,le=1920)
    height:int=Field(default=240,ge=64,le=1920)
    gpu:int=Field(default=5,ge=0)
    seed:int=42
    host:Literal['127.0.0.1','localhost']='127.0.0.1'
    port:int=Field(default=5200,ge=1024,le=65535)
    tm_port:int=Field(default=5802,ge=1024,le=65535)
    map_name:str=''
    cameras:list[Literal['front','side_left','side_right','rear','top']]=Field(default_factory=lambda:['front','side_left','side_right','rear','top'],min_length=1)
    autopilot:bool=True
    save_every:int=Field(default=1,ge=1,le=100)
    min_save_distance:float=Field(default=0,ge=0,le=100)
    max_ticks:int=Field(default=3000,ge=50,le=100000)
    license_id:str='unverified'
    split:Literal['train','validation','test']='test'
    annotation_indices:list[int]=Field(default_factory=lambda:[0])
    annotation:dict

    @model_validator(mode='after')
    def selection(self):
        if not Path(self.interpreter).is_absolute():raise ValueError('An explicit simulator interpreter is required')
        if len(set(self.annotation_indices))!=len(self.annotation_indices) or any(i<0 or i>=self.frames for i in self.annotation_indices):
            raise ValueError('Annotation frame indices must be distinct and inside the requested capture')
        if not self.annotation_indices:raise ValueError('Question production requires explicitly selected annotation frames')
        return self


class CaptureSource(Plugin):
    mode=''
    description='Real capture with RGB and privileged data, followed by independent frame annotation tasks'

    def describe(self):
        return super().describe().model_copy(update={'resources':Resources(cpu=1,gpu=1,memory_gb=4)})

    def validate_parameters(self,parameters):
        p=CaptureParameters.model_validate(parameters)
        if self.mode=='habitat' and not p.scene:raise HarnessError('CAPTURE_SCENE','Habitat scene is required')
        if self.mode=='libero_hdf5' and not p.dataset:raise HarnessError('CAPTURE_DATASET','HDF5 dataset is required')

    def healthcheck(self,parameters):
        p=CaptureParameters.model_validate(parameters)
        paths=[p.interpreter]+([p.scene] if self.mode=='habitat' else [p.dataset] if self.mode=='libero_hdf5' else [])
        return HealthResult(ready=all(Path(x).is_file() for x in paths),code='CAPTURE_DEPENDENCY')

    def plan(self,unit):
        self.validate_parameters(unit.parameters);p=CaptureParameters.model_validate(unit.parameters)
        units=[unit.model_copy(update={'operation':'capture'})]
        for index in p.annotation_indices:
            units.append(WorkUnit(task_id=unit.task_id+f'_annotate_{index:06}',stage=3,plugin_id='annotator.capture',
                depends_on=[unit.task_id],parameters={'capture_task':unit.task_id,'frame':index,'annotation':p.annotation},
                resources=Resources(cpu=1,gpu=1,memory_gb=4),retry=unit.retry))
        return units

    def execute(self,ctx,unit):
        p=CaptureParameters.model_validate(unit.parameters)
        config=ctx.output_dir/'capture_request.json';config.write_text(json.dumps(p.model_dump()))
        output=ctx.output_dir/'capture';output.mkdir()
        env={**os.environ,'CUDA_VISIBLE_DEVICES':str(p.gpu),'MUJOCO_GL':'egl','PYOPENGL_PLATFORM':'egl','MUJOCO_EGL_DEVICE_ID':str(p.gpu)}
        with (ctx.output_dir/'capture.log').open('w') as log:
            proc=subprocess.run([p.interpreter,str(Path(__file__).with_name('capture_worker.py')),self.mode,str(config),str(output)],
                env=env,stdout=log,stderr=log,timeout=unit.retry.timeout_seconds-2)
        if proc.returncode:
            raise HarnessError('CAPTURE_EXIT',(ctx.output_dir/'capture.log').read_text(errors='replace')[-1800:])
        if (ctx.output_dir/'capture.log').stat().st_size==0:(ctx.output_dir/'capture.log').unlink()
        raw=json.loads(safe_path(output,'collection.json',True).read_text())
        if len(raw['frames'])!=p.frames:raise HarnessError('CAPTURE_COUNT','Capture did not deliver the requested timepoints')
        assets=[];contexts=[];records=[];files=[]
        params=ImportParameters(path=str(output),source_uri=raw['source_uri'],license_id=p.license_id,split=p.split)
        for index,frame in enumerate(raw['frames']):
            rid=unit.task_id+f'_frame_{index:06}';refs=[]
            for camera,relative in frame['images'].items():
                asset,context=add_image(ctx.output_dir,safe_path(output,relative,True),rid+'_'+camera,unit.task_id,params)
                asset=asset.model_copy(update={'episode_id':unit.task_id,'frame_id':str(index)})
                assets.append(asset);contexts.append(context);refs.append(asset.asset_id)
            file_refs=[]
            for entry in frame.get('files',[]):
                path=safe_path(output,entry['uri'],True);fid=rid+f'_data_{len(file_refs):02}'
                files.append(DataFile(file_id=fid,uri=path.relative_to(ctx.output_dir).as_posix(),kind=entry['kind'],byte_size=path.stat().st_size,source_uri=raw['source_uri']))
                file_refs.append(fid)
            records.append(SourceRecord(record_id=rid,format='capture',asset_refs=refs,source_uri=raw['source_uri'],review_status='accepted',
                data={'frame_index':index,'capture_mode':self.mode,'file_refs':file_refs,'camera_order':list(frame['images']),
                      'ground_truth':frame['gt'],'seed':p.seed}))
        return WorkResult(status='succeeded',bundle=Bundle(assets=assets,contexts=contexts,records=records,files=files),metrics={'captured_timepoints':len(records),'captured_rgb':len(assets)})


class HabitatSource(CaptureSource):
    plugin_id='simulator.habitat';mode='habitat'


class LiberoSource(CaptureSource):
    plugin_id='simulator.libero';mode='libero'


class CarlaSource(CaptureSource):
    plugin_id='simulator.carla';mode='carla'


class LiberoHDF5Source(CaptureSource):
    plugin_id='source.libero_hdf5';mode='libero_hdf5'


class FrameParameters(Contract):
    capture_task:str
    frame:int=Field(ge=0)
    annotation:dict


class CaptureAnnotator(Plugin):
    plugin_id='annotator.capture';kind='annotator'
    description='Annotate one declared real capture frame using the existing local vision services'

    def validate_parameters(self,p):FrameParameters.model_validate(p)

    def healthcheck(self,p):
        from .legacy import annotation_readiness
        return annotation_readiness(p['annotation']['vlm_model'],p['annotation'].get('vlm_base_url','http://127.0.0.1:9001'))

    def execute(self,ctx,unit):
        from .legacy import DefaultAnnotationSource,AnnotationParameters
        p=FrameParameters.model_validate(unit.parameters)
        bundle,directory=ctx.inputs[p.capture_task]
        record=next(r for r in bundle.records if r.data['frame_index']==p.frame)
        asset=next(a for a in bundle.assets if a.asset_id==record.asset_refs[0]);path=safe_path(directory,asset.uri,True)
        params=AnnotationParameters.model_validate({**p.annotation,'path':str(path.parent),'image':path.name,
            'source_uri':record.source_uri+f'#frame={p.frame}','scene_id':asset.scene_id,'split':asset.split,'license_id':asset.license_id})
        result=DefaultAnnotationSource().execute(ctx,unit.model_copy(update={'parameters':params.model_dump(mode='json')}))
        gt=record.data['ground_truth']
        depths=[f for f in bundle.files if f.file_id in record.data['file_refs'] and f.kind=='depth']
        if depths and gt.get('camera_intrinsics'):
            import numpy as np
            from PIL import Image
            depth=np.load(safe_path(directory,depths[0].uri,True),allow_pickle=False)
            k=np.array(gt['camera_intrinsics']);records=[]
            for derived in result.bundle.records:
                entities=derived.data['entities']
                for obj in entities['objects']:
                    with Image.open(safe_path(ctx.output_dir,obj['mask']['path'],True)) as image:
                        mask=np.asarray(image)>0
                    if mask.ndim==3:mask=mask.any(axis=2)
                    if mask.shape!=depth.shape:raise HarnessError('GT_ALIGNMENT','Simulator depth and segmentation shape differ')
                    y,x=np.where(mask & np.isfinite(depth) & (depth>0));z=depth[y,x]
                    if not len(z):
                        obj['depth_median']=None;obj['range_median_m']=None;obj['centroid_3d']={};obj['rough_3d_bbox']={}
                        continue
                    xyz=np.column_stack(((x-k[0,2])*z/k[0,0],(y-k[1,2])*z/k[1,1],z))
                    obj['depth_median']=float(np.median(z));obj['centroid_3d']={'xyz':np.median(xyz,axis=0).tolist()}
                    obj['range_median_m']=float(np.median(np.linalg.norm(xyz,axis=1)))
                    obj['rough_3d_bbox']={'size_xyz':(xyz.max(axis=0)-xyz.min(axis=0)).tolist()}
                records.append(derived.model_copy(update={'data':{**derived.data,'entities':entities,'metric_3d_verified':True,
                    'range_verified':True,'geometry_origin':'simulator_metric_depth_with_model_masks','capture_record_ref':record.record_id}}))
            result=result.model_copy(update={'bundle':result.bundle.model_copy(update={'records':records})})
        return result
