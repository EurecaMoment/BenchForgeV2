import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createDeliveryReview } from './delivery_review.mjs';
import { createDeliveryFileReview } from './delivery_files.mjs';
import { createDeliveryVisuals } from './delivery_visuals.mjs';
export const name='spatialforge-tools';
// Delivery visual feedback resolves the active model route and stores image
// attachments while the turn-stopping hook is running. Declare both services
// so the hook remains valid after a normal final response/present boundary.
export const inject=['tools','llm','attachments'];
export async function apply(ctx, config) {
  const { defineTool } = await import(pathToFileURL(path.join(config.dshRoot, 'packages/core/tools/lib/index.js')));
  const { createUserMessage } = await import(pathToFileURL(path.join(config.dshRoot, 'packages/llm/llm/lib/index.js')));
  const cfg = JSON.parse(fs.readFileSync(config.serviceConfig, 'utf8'));
  const tokenName = cfg.operator_token_env || 'SPATIALFORGE_OPERATOR_TOKEN';
  const token = process.env[tokenName];
  if (!token) throw new Error(`Set ${tokenName} before starting the SpatialForge mode`);
  const serviceUrl = cfg.service_url.replace(/\/$/, '');
const output={schema:{type:'object',additionalProperties:true,properties:{}},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]};
async function api(path,args,signal){
  const response=await fetch(serviceUrl+path,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(args),signal});
  // Isaac camera matrices contain -0.0; DSH's JSON transport rejects signed zero.
  const data=JSON.parse(await response.text(),(_key,value)=>Object.is(value,-0)?0:value);if(!response.ok)throw new Error(JSON.stringify(data));return data;
}
async function observation(path,args,signal){
  const {cursor:ignored,...request}=args;
  const {cursor,...value}=await api(path,request,signal);
  return value;
}
async function submit(path,args,exec){
  const request_key=args.request_key??`dsh:${exec.agent.session.id}:${exec.callId}`;
  return api(path,{...args,request_key},exec.signal);
}
const requestKey={type:'string',description:'Optional key to reuse the same request across separate tool calls. Omit to use this session and tool-call identity.'};
const layoutInput={type:'object',additionalProperties:false,properties:{mode:{type:'string',enum:['generate','edit','reference'],required:true},prompt:{type:'string',description:'Visual description for generate/edit.'},source_image:{type:'string'},source_view:{type:'integer'},seed:{type:'integer'},design_task_id:{type:'string',description:'For mode=reference only: completed spatialforge_layout task ID. Preserves diffusion provenance and avoids regeneration; no other source fields.'}}};
const programInput={type:'string',description:'Complete SceneProgram JSON in the task workspace, written with standard file tools or task_code; the initial pass uses this snapshot directly.'};
  const visuals=createDeliveryVisuals({api,images:async(paths,agent,signal)=>{
    const routed=agent.session.requestHeader()?.config;
    const info=await ctx.llm.resolveModelInfo(routed?.provider??agent.options.provider,routed?.model??agent.options.model,signal);
    if(!info.inputModalities?.includes('image'))return [];
    const attachments=ctx.get('attachments');
    return Promise.all(paths.map(async imagePath=>({type:'image',attachment:await attachments.saveImage({
      data:await fs.promises.readFile(imagePath,{signal}),mediaType:'image/png',name:imagePath.split('/').at(-1),
    })})));
  }});
  ctx.on('agent/turn-stopping',createDeliveryReview({api,createMessage:createUserMessage,visuals}));
  ctx.on('agent/turn-stopping',createDeliveryFileReview({createMessage:createUserMessage}));
  const stage=(name,path,description,parameters)=>ctx.tools.register(defineTool({name,description,parameters:{request_key:requestKey,...parameters},output,execute:(args,exec)=>submit(path,args,exec)}));
  stage('spatialforge_diffusion','/diffusion','Generate or edit an image with FLUX. Takes your prompt directly. Returns a task; status exposes image source_path and evidence can display it. No segmentation, reconstruction or scene generation is started.',{
    prompt:{type:'string',required:true},source_image:{type:'string',description:'Optional input image source_path for editing.'},width:{type:'integer'},height:{type:'integer'},steps:{type:'integer'},seed:{type:'integer'}});
  stage('spatialforge_sam3','/sam3','Segment an image with SAM3. Returns every candidate mask, box and score for you to inspect and select. Prompts use text; instances use pixel xyxy boxes. Does not choose a mask or reconstruct a mesh.',{
    source_image:{type:'string',required:true},prompts:{type:'array',items:{type:'string'}},instances:{type:'array',items:{type:'object',additionalProperties:true,properties:{id:{type:'integer'},label:{type:'string'},box:{type:'array',items:{type:'number'}},segmentation_prompt:{type:'string'}}}},confidence:{type:'number'}});
  stage('spatialforge_sam3d','/sam3d','Reconstruct paired Gaussian appearance and mesh physics from an image and selected masks. Each object returns mesh source_path, gaussian_source_path and predicted pose/scale. Does not register or place meshes; use mesh_import when ready.',{
    source_image:{type:'string',required:true},objects:{type:'array',required:true,items:{type:'object',additionalProperties:false,properties:{object_id:{type:'string',required:true},source_mask:{type:'string',required:true},seed:{type:'integer'}}}},seed:{type:'integer'},texture_baking:{type:'boolean',description:'Optional SAM3D Gaussian multiview texture baking with UVs. Slower than the default vertex-color mesh; keeps predicted camera-frame pose. No measured PBR or detail guarantee.'}});
  stage('spatialforge_depth','/depth','Estimate relative inverse depth with Depth Anything V2 Small on CPU. Returns a depth array and visualization at the input image dimensions. Larger values mean nearer surfaces; scale is uncalibrated. Use as a layout aid, not meter coordinates or simulator GT.',{
    source_image:{type:'string',required:true},input_size:{type:'integer',description:'Inference resolution, default 518. Output matches the input image dimensions.'}});
  stage('spatialforge_mesh_import','/mesh-import','Convert and register an existing mesh for SceneProgram use without model inference or visual review. Returns asset_id and bounds. For SAM3D output use source_frame=sam3d_camera; its paired Gaussian sidecar is imported automatically. source_gaussian can supply an explicit paired NPZ.',{
    source_mesh:{type:'string',required:true},source_gaussian:{type:'string',description:'Paired activated Gaussian NPZ; coordinates match source_mesh or include local_to_source.'},label:{type:'string',required:true},source_up_axis:{type:'string',enum:['Y','Z']},source_frame:{type:'string',enum:['sam3d_camera','y_up','z_up']},size_hint_m:{type:'array',items:{type:'number'}}});
  stage('spatialforge_capture','/capture','Render and simulate your complete SceneProgram on the desktop Isaac queue. Returns actual images, geometry and declared action traces. Does not plan or automatically revise the scene, run model review or export a dataset. Inspect the captures and decide the next step.',{
    scene_program_path:{type:'string',required:true},name:{type:'string'},layout:layoutInput});
  ctx.tools.register(defineTool({name:'spatialforge_preview',description:'Compute placement bounds, support gaps and geometry advice from your SceneProgram without starting Isaac or a model. Use capture for actual images and physics.',parameters:{scene_program_path:{type:'string',required:true}},output,execute:(args,exec)=>api('/preview',args,exec.signal)}));
  ctx.tools.register(defineTool({name:'spatialforge_layout',description:"Generate, edit or reuse a diffusion design reference. Optional standalone tool; run can prepare the reference internally. Read layout/reference.png with evidence, and reuse via layout={mode:\"reference\",design_task_id}. This produces a design image, not a simulated scene.",parameters:{request_key:requestKey,name:{type:'string',required:true},description:{type:'string',required:true},layout:layoutInput},output,execute:(args,exec)=>submit('/layout',args,exec)}));
  ctx.tools.register(defineTool({name:'spatialforge_evidence',description:"Read actual JSON, images and action traces from current or earlier revisions, including failed attempts. Omit file to list evidence. Use workspace_id to copy a file for task-code processing. Production evidence is read-only; authority GT is excluded.",parameters:{task_id:{type:'string',required:true},revision:{type:'integer'},file:{type:'string'},workspace_id:{type:'string'}},output:{...output,render:(_args,value)=>[{type:'text',text:JSON.stringify({...value,image:undefined})},...(value.image?[{type:'image',attachment:value.image}]:[])]},execute:async(args,exec)=>{
    const value=await api('/evidence',args,exec.signal);
    if(value.image_path){
      const attachments=ctx.get('attachments');const llm=ctx.get('llm');
      const routed=exec.agent?.session.requestHeader()?.config;
      const provider=routed?.provider??exec.agent?.options.provider;const model=routed?.model??exec.agent?.options.model;
      if(!attachments||!llm||provider===undefined||model===undefined)throw Error('Image evidence needs the attachment service and a resolved vision route; copy to workspace_id for file processing.');
      const info=await llm.resolveModelInfo(provider,model,exec.signal);
      if(!info.inputModalities?.includes('image'))throw Error('Current model route does not declare image input; use JSON evidence or copy the image to workspace_id.');
      const data=await fs.promises.readFile(value.image_path);
      value.image=await attachments.saveImage({data,mediaType:/\.jpe?g$/i.test(value.image_path)?'image/jpeg':'image/png',name:args.file.split('/').at(-1)});
      delete value.image_path;
    }
    return value;
  }}));
  ctx.tools.register(defineTool({name:'spatialforge_catalog',description:"Discover tool capabilities, SceneProgram format and assets. Choose a section; query filters, item_id selects detail, next_offset continues. workspace_id copies all matches for task-code inspection. scene_schema fragments concatenate into the complete format.",parameters:{section:{type:'string',enum:['overview','contracts','scene_schema','native_assets','generated_assets','generation_tools','materials','environments','dataset_sources','dataset_templates','dataset_recipes','dataset_processing','dataset_guidance','knowledge']},query:{type:'string'},item_id:{type:'string'},offset:{type:'integer'},limit:{type:'integer'},workspace_id:{type:'string'}},output,execute:(args,exec)=>api('/catalog',args,exec.signal)}));
  ctx.tools.register(defineTool({name:'spatialforge_run',description:"Produce a scene and dataset from natural-language requirements or scene_program_path. The pipeline prepares a diffusion reference unless one is supplied, then builds, captures, reviews and exports through desktop Isaac. Returns a durable run ID.",parameters:{request_key:requestKey,intents:{type:'array',required:true,items:{type:'object',additionalProperties:false,properties:{name:{type:'string',required:true},description:{type:'string',required:true},split:{type:'string',enum:['train','dev'],required:true},target_items:{type:'integer',description:'Number of dataset questions to export; this is not the scene entity count.'},layout:layoutInput,scene_program_path:programInput}}}},output,execute:(args,exec)=>submit('/start',args,exec)}));
  ctx.tools.register(defineTool({name:'spatialforge_asset',description:"Generate with diffusion/SAM3/SAM3D, reconstruct source_image, import source_mesh, or reuse catalog asset_id. Optional texture_baking gives reconstructed meshes UV color textures. Inputs use registered source paths; returns a durable run ID.",parameters:{request_key:requestKey,intent:{type:'object',required:true,additionalProperties:false,properties:{name:{type:'string',required:true},description:{type:'string',required:true},label:{type:'string',description:'Semantic subject for SAM3 segmentation and asset registration; defaults to name.'},source_image:{type:'string'},source_mask:{type:'string'},source_mesh:{type:'string'},source_gaussian:{type:'string'},asset_id:{type:'string'},seed:{type:'integer'},source_up_axis:{type:'string',enum:['Y','Z']},size_hint_m:{type:'array',items:{type:'number'}},subject_box:{type:'array',items:{type:'number'},description:'Pixel xyxy box selecting the subject.'},edit_reference:{type:'boolean'},texture_baking:{type:'boolean',description:'Optional SAM3D UV color baking during reconstruction; slower, with possible inferred-surface artifacts. Omitted/false keeps vertex colors. Reusing or importing a mesh retains its existing appearance.'}}}},output,execute:(args,exec)=>submit('/asset',args,exec)}));
  ctx.tools.register(defineTool({name:'spatialforge_extend',description:"Add objects to a captured scene while retaining its existing entities and train/dev family. Use refine when existing objects also need changes.",parameters:{request_key:requestKey,parent_task_id:{type:'string',required:true},name:{type:'string',required:true},description:{type:'string',required:true},target_items:{type:'integer',description:'Number of dataset questions to export; this is not the scene entity count.'},layout:layoutInput},output,execute:(args,exec)=>submit('/extend',args,exec)}));
  ctx.tools.register(defineTool({name:'spatialforge_dataset',description:"Produce data from registered sources and recipes, or a complete DatasetSpec. Supports overrides and train/dev split; preserves source GT.",parameters:{request_key:requestKey,intent:{type:'object',required:true,additionalProperties:true,properties:{recipe:{type:'string'},spec:{type:'object',additionalProperties:true},overrides:{type:'object',additionalProperties:true},review:{type:'boolean'},split:{type:'string',enum:['train','dev']}}}},output,execute:(args,exec)=>submit('/dataset',args,exec)}));
  ctx.tools.register(defineTool({name:'spatialforge_retry',description:"Resume a failed task with optional repair feedback. Reuses completed stages and retains prior artifacts.",parameters:{task_id:{type:'string',required:true},feedback:{type:'string',description:'Optional concrete scene repair guidance for a failed planning stage, up to 12000 characters.'}},output,execute:(args,exec)=>api('/retry',args,exec.signal)}));
  ctx.tools.register(defineTool({name:'spatialforge_status',description:"Read current progress, available evidence, assessed quality and exports. run_id excludes .sceneN. detail=true includes full task reports. Lifecycle completion and scene quality are separate fields.",parameters:{run_id:{type:'string',required:true},detail:{type:'boolean'}},output,execute:(args,exec)=>observation(args.detail?'/inspect':'/observe',args,exec.signal)}));
  ctx.tools.register(defineTool({name:'spatialforge_wait',description:"Wait for a state, stage or error change, or completion. Defaults to 60 seconds; upload percentages do not end the wait. Needs only run_id, with optional timeout_seconds. Returns current progress without retrying or changing the task.",parameters:{run_id:{type:'string',required:true},timeout_seconds:{type:'integer',description:'Wait duration in seconds, 1..60; omit for 60.'}},output,execute:(args,exec)=>observation('/wait',args,exec.signal)}));
  ctx.tools.register(defineTool({name:'spatialforge_task_code',description:"Run Python task code in a persistent writable /workspace. Read-only modules are under /harness and reusable assets under /assets. Use it for calculations, image/mesh processing, diagnostics and complete SceneProgram JSON. Submit returned source_path through production tools. Timeout 1..300 seconds, default 60; code up to 1 MiB.",parameters:{workspace_id:{type:'string',required:true},code:{type:'string',required:true},timeout_seconds:{type:'integer'}},output,execute:(args,exec)=>api('/task-code',args,exec.signal)}));
  ctx.tools.register(defineTool({name:'spatialforge_refine',description:"Revise a captured scene from feedback or a complete SceneProgram. Can change layout, objects, materials, lights, cameras and actions. A capture-only parent stays capture-only unless target_items is explicitly supplied; otherwise the parent data target is inherited. source_revision optionally selects an earlier capture; preserves the source and train/dev family.",parameters:{request_key:requestKey,parent_task_id:{type:'string',required:true},source_revision:{type:'integer',description:'Optional captured revision to refine; use evidence to choose an earlier capture when the latest planning attempt failed.'},name:{type:'string',required:true},description:{type:'string',required:true},target_items:{type:'integer',description:'Number of dataset questions to export; this is not the scene entity count.'},layout:layoutInput,scene_program_path:programInput},output,execute:(args,exec)=>submit('/refine',args,exec)}));
  ctx.tools.register(defineTool({name:'spatialforge_cancel',description:"Cancel this run, preserving its artifacts and shared services.",parameters:{run_id:{type:'string',required:true}},output,execute:(args,exec)=>api('/cancel',args,exec.signal)}));
}
