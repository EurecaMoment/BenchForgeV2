import fs from 'node:fs/promises';
import path from 'node:path';
import {defineTool} from '@deepseek-ai/dsh-tools';
import Schema from '@deepseek-ai/schemastery';
import {launchEnvironmentOf} from '@deepseek-ai/dsh-launch-environment';
import {executeHandoff, handoffParameters} from '../shared/collaboration.mjs';

export const name = 'benchforge-tools';
export const inject = ['tools', 'attachments', 'subprocess'];
export const Config = Schema.object({
  python: Schema.string().default('python3'),
  configPath: Schema.string(),
  dshRoot: Schema.string(),
  includeTools: Schema.array(Schema.string()),
  environment: Schema.dict(Schema.string()).default({}),
  forwardEnvironment: Schema.array(Schema.string()).default([]),
  maxOutputBytes: Schema.number().min(1024).default(16 * 1024 * 1024),
  graceMs: Schema.number().min(1).default(1000),
});

export async function invoke(subprocess, python, workspace, configPath, tool, request, signal, options = {}) {
  signal?.throwIfAborted();
  const cwd = path.resolve(workspace);
  await fs.mkdir(cwd, {recursive:true});
  const env = {...options.environment, PYTHONIOENCODING:'utf-8', BENCHFORGE_MANAGED_SUBPROCESS:'1'};
  const executable = await subprocess.resolveExecutable(python, env, signal);
  signal?.throwIfAborted();
  const argv = [executable, '-m', 'benchforge_core.cli', tool, '--workspace', cwd, '--input', '-'];
  if (configPath) argv.push('--config', path.resolve(configPath));
  const handle = subprocess.spawn({argv, cwd, env, signal, graceMs:options.graceMs ?? 1000,
    stdio:{stdin:{data:JSON.stringify(request)}, stdout:{maxBytes:options.maxOutputBytes ?? 16 * 1024 * 1024}, stderr:{maxBytes:65536}}});
  options.active?.add(handle);
  try {
    const outcome = await handle.done;
    signal?.throwIfAborted();
    const stdout = handle.collected.stdout.readFrom(0);
    const stderr = handle.collected.stderr.readFrom(0);
    if (outcome.exitCode !== 0) throw new Error(stderr.text || `BenchForge exited ${outcome.exitCode ?? outcome.signal}`);
    if (stdout.lossy) throw new Error(`BenchForge JSON exceeds maxOutputBytes (${options.maxOutputBytes ?? 16 * 1024 * 1024}); increase the plugin limit for this result.`);
    return JSON.parse(stdout.text);
  } finally {
    // A CLI result is complete only after all of its owned work has stopped.
    // Explicit background jobs transfer to their own service before returning.
    handle.terminate();
    await handle.waitForExit();
    options.active?.delete(handle);
  }
}

export async function apply(ctx, config) {
  const active = new Set();
  const lifetime = new AbortController();
  ctx.effect(() => async () => {
    lifetime.abort(new DOMException('BenchForge plugin unloaded', 'AbortError'));
    for (const handle of active) handle.terminate();
    await Promise.all([...active].map(handle => handle.waitForExit()));
  });
  const snapshot = launchEnvironmentOf(ctx);
  const environment = Object.fromEntries((config.forwardEnvironment || []).map(key => [key,snapshot.get(key)?.value]).filter(([,value])=>value!==undefined));
  Object.assign(environment,config.environment);
  const output = {schema:{type:'object',properties:{},additionalProperties:true},
    render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]};
  const operationOutput = {...output,schema:{type:'object',properties:{operation_id:{type:'string',required:true},artifact_dir:{type:'string',required:true}},additionalProperties:true}};
  const statusOutput = {...output,schema:{type:'object',properties:{operations:{type:'array',required:true,items:{type:'object',properties:{id:{type:'string',required:true},tool:{type:'string',required:true},state:{type:'string',required:true}},additionalProperties:true}}},additionalProperties:true}};
  const definitions = {
    catalog:'Discover callable production tools and exact request examples. See exact request examples and the V2 task template catalog.',
    status:'Read persisted operation results and artifact paths. Does not retry operations.',
    plan:'Save a benchmark brief. Planning and capability choices belong to you; no fixed stage sequence.',
    llm_local:'Call the configured OpenAI-compatible vision model for semantic annotation suggestions. Responses are predictions that can guide annotation or repair; source labels remain authoritative.',
    habitat:'Capture real Habitat RGB, depth and agent state with the bundled collector in its configured environment.',
    libero:'Collect LIBERO observations and simulator state using demo or zero actions in its configured environment.',
    carla:'Capture CARLA views and actor metadata from a configured running server.',
    evidence:'Import evidence JSONL. provenance.path references one JSON source document; selectors are JSON pointers into it. All relative paths resolve against the input JSONL directory. media contains public images only; assets retains private raw depth, labels and oracle code. Derive JSON oracle outputs from binary simulation inputs in task code.',
    build:'Build model-visible items/media plus separate authority sources and private assets, deriving answers from source JSON and reporting coverage. Keep raw depth and authority labels in the evidence side of the bundle.',
    evaluate:'Score saved predictions with exact match; report missing answers. Does not call model APIs.',
  };
  const object={type:'object',properties:{},additionalProperties:true};
  Object.assign(definitions, {
    pipeline_catalog:'Discover composable production recipes and the user-provided 89 tasks / 267 exact measurement templates. Capability links retrieve candidates; they do not define primary measurement or inherit validation. Read conditions and execution support before selecting.',
    pipeline_plan:'Prefer request_path or assessment_path for durable plans. Use validate_only=true to obtain all issues, patch only the existing file, then submit the same path with false. Never retranscribe a large document after an error. Read pipeline_catalog section=plan_template and supply the complete assessment document alongside the executable selections. Create a persistent production plan for one capability or multiple exact task templates. Interpret user intent and supply selections with template_ids/count/reason; plain text without explicit IDs returns candidates for your semantic decomposition. Compose recipes with shared typed artifacts. A user-edited plan blocks older plans: read edit_revision.base_plan and user_markdown. If exactly one assessment-yaml block is explicitly changed, preserve the saved assessment, allocation and production inputs exactly. If the block is absent or unchanged, resolve changed prose into assessment fields and inputs, then pass markdown_resolution entries with the exact schema [{path,before,after,instruction}]: one per changed assessment leaf, path relative to assessment (dot-separated keys and numeric array indices), before/after exact old/new JSON values, instruction an exact quote outside the YAML block from either newly added or modified prose absent from old prose, or old prose actually deleted from new prose. Unchanged quotes and quotes absent from both versions are rejected; quotes must cover actual prose deletions. Keep protected scene_selection and split. Validate assessment, selections and matching inputs; resolve seed through assessment.dataset.seed. Update executable steps or evidence for non-parameter prose changes. Preserve exact user_markdown; pipeline_plan validates and audits the resolution on the applied plan.',
    pipeline_run:'Execute or resume a frozen pipeline plan. Reuses completed steps, submits to the existing single Isaac queue, and returns waiting/needs_input/needs_evidence when unfinished. For exact document templates supply protocol-bound source evidence when no program generator exists. State completed concerns production, not benchmark approval.',
    pipeline_status:'Read the persisted pipeline step states and artifacts without submitting or retrying work.',
    pipeline_artifacts:'Inspect the typed artifact lineage for a persisted run. This is a read-only manifest of candidates, contracts and parent references; it does not approve a benchmark or retry a step.',
    pipeline_repair_plan:'Create a deterministic, reviewable repair proposal for one failed artifact. It selects the smallest repair scope from the failure code and never changes GT, templates or remote services.',
    pipeline_evaluate:'Score saved answers against the exact imported template protocol: numeric error with units, grouped ordering and IoU/detection sets. Separate per-template metrics; no model API judging or pooled 27-capability claim.',
    spatial_catalog:'Read the 27-node spatial capability graph and executable template specifications. Conditional graph relations guide task selection without imposing prerequisite locks.',
    spatial_generate:'Generate grouped training and evaluation worlds, observations, program answers and feedback episodes from selected spatial templates. Train/dev/test roles remain separate.',
    spatial_evaluate:'Score saved answers or replay actions against program truth and environment states. No model API judging.',
    curriculum:'Update condition-specific mastery from development feedback and allocate a training budget. Compare fixed A, adaptive B and graph-guided C using the same candidate pool.',
    spatial_train:'Train a locally configured small model with windowed SFT, development feedback, curriculum sampling and resumable checkpoints. Specify the model and compute configuration explicitly.',
    training_monitor:'Read live training loss, capability feedback, allocations, checkpoints and guidance from a training run.'
  });
  definitions.spatial_export='Export spatial datasets as portable Parquet with embedded images and separate program authority.';
  definitions.spatial_experiment='Compare fixed A, adaptive B and graph-guided C from the same initial local checkpoint and training budget; report actual token and time costs.';
  definitions.adapt_capture='Convert native Habitat/LIBERO/CARLA capture to compiler evidence. Habitat samples continuous visible surface regions and computes calibrated camera range from raw depth; semantic labels come from the selected source records.';
  definitions.stage_review='After each completed S1-S5 stage, open a durable 300-second user instruction window with its saved artifact and a stable production key. An executable plan opens S1 automatically; a pending user-edit draft does not. Call wait with a default 60-second call budget and repeat until elapsed or continued, then resume existing work; the saved window still lasts 300 seconds. A paused or needs_input window blocks production; apply the saved user instruction before acknowledging. Do not skip waits or report them as capture queue blockage.';
  const schemas={
    stage_review:{action:{type:'string',enum:['open','status','wait','continue','pause','instruction','acknowledge']},stage:{type:'string',enum:['S1','S2','S3','S4','S5']},key:{type:'string'},artifact:{type:'string'},review_id:{type:'integer'},instruction:{type:'string'},timeout_seconds:{type:'number',default:60,description:'Single wait call budget in seconds, 0..300; default 60. The saved review deadline remains 300 seconds.'}},
    pipeline_catalog:{section:{type:'string',enum:['pipelines','capabilities','tasks','templates','protocol','plan_template']},capability:{type:'string'},template_ids:{type:'array',items:{type:'string'}},task_ids:{type:'array',items:{type:'string'}},query:{type:'string'},item_id:{type:'string'},offset:{type:'integer'},limit:{type:'integer'}},
    pipeline_plan:{request_path:{type:'string',description:'JSON request file relative to workspace or absolute. Preferred for large plans and edits: save once, submit its path. File cannot be combined with inline plan fields; host session context is preserved.'},assessment_path:{type:'string',description:'Saved assessment JSON file relative to workspace or absolute. Use with matching selections/inputs instead of copying its contents into assessment; cannot combine with assessment.'},validate_only:{type:'boolean',description:'Check the saved plan without saving a production plan or opening S1. Returns all correction issues; edit only those fields in the same file, then submit with false.'},applies_edit:{type:'string',description:'Path of the active user-edited plan; preserve exact user_markdown. Explicitly changed YAML means retain its assessment/inputs. For prose-only edits, normalize every changed assessment leaf using markdown_resolution and quote the actual added/modified prose or deleted old prose verbatim.'},user_markdown:{type:'string',description:'Exact complete user-edited Markdown from the active plan. Required unchanged when applying.'},markdown_resolution:{type:'array',items:{type:'object',additionalProperties:false,properties:{path:{type:'string',required:true,description:'Assessment-relative dot path; array positions are decimal indices, e.g. coverage.0.count.'},before:{oneOf:[{type:'string'},{type:'number'},{type:'boolean'},{type:'null'},{type:'object',additionalProperties:true},{type:'array',items:{type:'json'}}],description:'Exact old JSON value for this field.'},after:{oneOf:[{type:'string'},{type:'number'},{type:'boolean'},{type:'null'},{type:'object',additionalProperties:true},{type:'array',items:{type:'json'}}],description:'Exact resolved new JSON value for this field.'},instruction:{type:'string',required:true,description:'Exact quote outside the YAML block from newly added/modified prose absent from the old version, or old prose actually deleted in the new version. Unchanged or nonexistent quotes are rejected.'}}}},assessment:{type:'object',additionalProperties:true,description:'Complete resolved assessment. For prose-only edits, synchronize quantity fields with selections and inputs; validate against the saved scene selection.'},objective:{type:'string'},pipeline_id:{type:'string'},capability:{type:'string'},capabilities:{type:'array',items:{type:'string'}},template_ids:{type:'array',items:{type:'string'}},task_ids:{type:'array',items:{type:'string'}},target_items:{type:'integer'},selections:{type:'array',items:{type:'object',additionalProperties:false,properties:{template_ids:{type:'array',items:{type:'string'},required:true},count:{type:'integer',required:true},reason:{type:'string',required:true}}}},steps:{type:'array',items:{type:'object',additionalProperties:true,properties:{id:{type:'string',required:true},uses:{type:'string',required:true},pipeline_id:{type:'string'},arguments:{type:'object',additionalProperties:true},await_terminal:{type:'boolean'}}}},inputs:{type:'object',additionalProperties:true},evidence:{type:'string'},seed:{type:'integer'},split:{type:'string',enum:['train','dev','test','sealed']},service_config:{type:'string'}},
    pipeline_run:{plan:{type:'string',required:true},run:{type:'string'},bindings:{type:'object',additionalProperties:true}},
    pipeline_status:{run:{type:'string',required:true}},
    pipeline_artifacts:{run:{type:'string',required:true},artifact_id:{type:'string'},status:{type:'string',enum:['draft','candidate','verified','rejected','superseded']}},
    pipeline_repair_plan:{run:{type:'string',required:true},artifact_id:{type:'string'},failure_code:{type:'string'},reason:{type:'string'}},
    pipeline_evaluate:{dataset:{type:'string',required:true},predictions:{type:'string',required:true}},
    spatial_catalog:{section:{type:'string',enum:['graph','templates']},capability:{type:'string'},query:{type:'string'},offset:{type:'integer'},limit:{type:'integer'}},
    spatial_generate:{capability:{type:'string'},template_ids:{type:'array',items:{type:'string'}},exclude_template_ids:{type:'array',items:{type:'string'}},groups_per_profile:{type:'integer'},seed:{type:'integer'},render:{type:'boolean'},conditions:{type:'array',items:{type:'string',enum:['natural','supplied_intermediate','isolated']}},heldout_profiles:{type:'array',items:{type:'string'}}},
    spatial_export:{dataset:{type:'string',required:true}},
    spatial_experiment:{config:{type:'string',required:true},run:{type:'string'},seeds:{type:'array',items:{type:'integer'}}},
    spatial_evaluate:{dataset:{type:'string',required:true},partition:{type:'string',enum:['curriculum_dev','selection_dev','sealed_test']},predictions:{type:'string',required:true}},
    curriculum:{state:{type:'string',required:true},feedback:{type:'string'},checkpoint:{type:'string'},window_id:{type:'string'},condition:{type:'string',enum:['A','B','C']},budget:{type:'integer'},template_ids:{type:'array',items:{type:'string'}},settings:{type:'object',additionalProperties:true}},
    spatial_train:{config:{type:'string',required:true},run:{type:'string'},action:{type:'string',enum:['run','start']}},
    training_monitor:{run:{type:'string',required:true},guidance:{type:'object',additionalProperties:true,properties:{pause:{type:'boolean'},stop_after_window:{type:'boolean'},learning_rate:{type:'number'},hint_fraction:{type:'number'},difficulty:{type:'integer'}}}},
    adapt_capture:{input:{type:'string',required:true},simulator:{type:'string',enum:['habitat','libero','carla']},camera:{type:'object',additionalProperties:true},regions:{type:'integer'},radius:{type:'integer'}},
    catalog:{section:{type:'string',enum:['overview','templates']},query:{type:'string'},offset:{type:'integer'},limit:{type:'integer'}},
    status:{},
    plan:{objective:{type:'string',required:true},sources:{type:'array',items:{type:'string'}},target_items:{type:'integer'},notes:{type:'string'}},
    evidence:{input:{type:'string',required:true,description:'Source records JSONL with provenance and JSON-pointer selectors.'}},
    build:{evidence:{type:'string',required:true},items:{type:'string',required:true}},
    evaluate:{authority:{type:'string',required:true},predictions:{type:'string',required:true}},
  };
  const production = {
  "acquire": [
    "Import local records or download an explicitly selected dataset file, preserving original labels and source fields.",
    {
      "input": {
        "type": "string"
      },
      "url": {
        "type": "string"
      },
      "format": {
        "type": "string"
      },
      "fields": {
        "type": "object",
        "additionalProperties": true
      },
      "media_root": {
        "type": "string"
      },
      "provenance": {
        "type": "string"
      },
      "source_id": {
        "type": "string"
      },
      "limit": {
        "type": "integer"
      }
    }
  ],
  "normalize": [
    "Normalize JSONL/JSON/CSV/Parquet/images into reusable evidence records; preserve original source fields.",
    {
      "input": {
        "type": "string",
        "required": true
      },
      "format": {
        "type": "string"
      },
      "fields": {
        "type": "object",
        "additionalProperties": true
      },
      "media_root": {
        "type": "string"
      },
      "provenance": {
        "type": "string"
      },
      "source_id": {
        "type": "string"
      },
      "limit": {
        "type": "integer"
      }
    }
  ],
  "clean": [
    "Clean selected records and readable media; optional Data-Juicer cleans derived text without overwriting labels.",
    {
      "input": {
        "type": "string",
        "required": true
      },
      "backend": {
        "type": "string",
        "enum": [
          "native",
          "data_juicer"
        ]
      },
      "text_field": {
        "type": "string"
      },
      "require_media": {
        "type": "boolean"
      },
      "operators": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": true
        }
      }
    }
  ],
  "literature": [
    "Retrieve primary papers from explicit URLs or an arXiv query and extract full text. Downloaded papers remain unread until inspected.",
    {
      "query": {
        "type": "string"
      },
      "sources": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": true
        }
      },
      "limit": {
        "type": "integer"
      }
    }
  ],
  "research_review": [
    "Bind literature claims to exact passages in downloaded text; reject fabricated or absent quotations.",
    {
      "index": {
        "type": "string",
        "required": true
      },
      "claims": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": true
        },
        "required": true
      }
    }
  ],
  "design": [
    "Validate benchmark intent, capability definitions, source/template/metric bindings and emit Q-matrix plus specification.",
    {
      "spec": {
        "type": "object",
        "additionalProperties": true,
        "required": true
      }
    }
  ],
  "score": [
    "Score saved predictions with declared deterministic metrics and stratified reports; missing score zero, duplicate/unknown IDs fail.",
    {
      "items": {
        "type": "string",
        "required": true
      },
      "predictions": {
        "type": "string",
        "required": true
      },
      "model": {
        "type": "string"
      }
    }
  ],
  "model_eval": [
    "Run explicitly configured models on public questions and images only; save responses, usage, failures and scores. No model question review.",
    {
      "public_items": {
        "type": "string",
        "required": true
      },
      "items": {
        "type": "string"
      },
      "models": {
        "type": "array",
        "items": {
          "type": "string"
        }
      }
    }
  ],
  "baselines": [
    "Run first-choice and seeded random-choice controls without reading gold in the responder. Results are proxy diagnostics.",
    {
      "items": {
        "type": "string",
        "required": true
      },
      "seed": {
        "type": "integer"
      }
    }
  ],
  "package": [
    "Create public and authority packages with media and questions. Optionally include a caller-provided reproducibility bundle.",
    {
      "items": {
        "type": "string",
        "required": true
      },
      "bundle": {
        "type": "string"
      }
    }
  ],
  "report": [
    "Merge real/proxy score files into a model-item matrix and evaluation report, rejecting duplicate responses.",
    {
      "scores": {
        "type": "array",
        "items": {
          "type": "string"
        },
        "required": true
      }
    }
  ],
  "usage": [
    "Summarize exact provider usage counters from an explicit DSH event export; disclose absent counters and subtree coverage.",
    {
      "events": {
        "type": "string",
        "required": true
      }
    }
  ]
};
  for (const [name, [description, schema]] of Object.entries(production)) {definitions[name]=description; schemas[name]=schema;}
  schemas.clean.min_contrast={type:'number',description:'Minimum grayscale standard deviation; default 1 rejects near-constant images.'};
  schemas.clean.min_bright_fraction={type:'number',description:'Optional fraction of pixels above luminance 16, e.g. 0.5 for well-lit captures.'};
  schemas.llm_local={
    action:{type:'string',enum:['infer','models']},
    payload:{...object,description:'OpenAI chat completion request for candidate annotations.'},
    timeout_seconds:{type:'integer'}
  };
  for(const tool of ['habitat','libero','carla']) schemas[tool]={argv:{type:'array',items:{type:'string'},description:'Collector arguments; catalog has examples. Use --help for installed SDK collector options.'},timeout_seconds:{type:'integer'}};
  let annotation;
  if (config.configPath && (!config.includeTools || config.includeTools.includes('llm_local'))) {
    try {
      const settings = JSON.parse(await fs.readFile(path.resolve(config.configPath), 'utf8'));
      const llm = settings.providers?.DSpark4A100;
      annotation = {...llm, ...llm?.roles?.annotation};
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
  const annotationToken = annotation?.token_env;
  const credential = annotationToken ? snapshot.get(annotationToken)?.value : undefined;
  const annotationEnvironment = credential === undefined ? environment : {...environment, [annotationToken]:credential};
  for (const [tool, description] of Object.entries(definitions)) {
    if (config.includeTools && !config.includeTools.includes(tool)) continue;
    if (tool === 'llm_local' && !annotation?.url) continue;
    ctx.tools.register(defineTool({name:`benchforge_${tool}`, description,
      parameters:{workspace:{type:'string',required:true,description:'Absolute task workspace. Use the same workspace for related calls.'},...schemas[tool]},
      output:tool==='catalog'?output:tool==='status'?statusOutput:operationOutput,
      execute:async (args,exec)=>{const {workspace,...request}=args; const signal=exec.signal ? AbortSignal.any([exec.signal,lifetime.signal]) : lifetime.signal;
        const scoped = tool === 'llm_local' ? annotationEnvironment : environment;
        const sessionEnvironment = {...scoped, BENCHFORGE_DSH_SESSION_ID: exec.agent?.session?.id || '', BENCHFORGE_DSH_CALL_ID: exec.callId || ''};
        return invoke(ctx.subprocess,config.python || 'python3',workspace,config.configPath,tool,request,signal,{...config,environment:sessionEnvironment,active});}}));
  }
  if (!config.includeTools || config.includeTools.includes('collaboration')) ctx.tools.register(defineTool({name:'benchforge_collaboration',
    description:'Share lightweight, structured handoffs in the task workspace. Agents can publish observations, artifacts, decisions, blockers and next actions, relate a handoff to earlier work, and reply to another agent. List or read the record when joining, resuming or reconciling parallel work; the protocol does not prescribe an orchestration graph.',
    parameters:{workspace:{type:'string',required:true,description:'Absolute task workspace shared by related agents.'},...handoffParameters},
    output,execute:executeHandoff}));
  if (!config.includeTools || config.includeTools.includes('view_image')) ctx.tools.register(defineTool({name:'benchforge_view_image', description:'Show a real local capture or annotation image to the model and user.',
    parameters:{path:{type:'string',required:true}},
    output:{...output,render:(_args,value)=>[{type:'image',attachment:value.image}]},
    execute:async (args,exec)=>{
      exec.signal?.throwIfAborted();
      const attachments=ctx.attachments;
      const data=await fs.readFile(args.path,{signal:exec.signal});
      exec.signal?.throwIfAborted();
      const image=await attachments.saveImage({data,mediaType:/\.jpe?g$/i.test(args.path)?'image/jpeg':'image/png',name:path.basename(args.path)});
      exec.signal?.throwIfAborted();
      return {image};
    }}));
}
