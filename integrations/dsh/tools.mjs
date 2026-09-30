import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';

export const name = 'benchforge-tools';
export const inject = ['tools'];

export function invoke(python, workspace, configPath, tool, request, signal) {
  return new Promise((resolve, reject) => {
    const argv = ['-m', 'benchforge_core.cli', tool, '--workspace', workspace, '--input', '-'];
    if (configPath) argv.push('--config', configPath);
    const child = spawn(python, argv, {stdio:['pipe','pipe','pipe'], signal,
      windowsHide:true, env:{...process.env, PYTHONIOENCODING:'utf-8'}});
    let stdout = '', stderr = '';
    child.stdout.on('data', x => stdout += x);
    child.stderr.on('data', x => stderr += x);
    child.on('error', reject);
    child.on('close', code => {
      if (code !== 0) return reject(new Error(stderr || `BenchForge exited ${code}`));
      try {resolve(JSON.parse(stdout));} catch (error) {reject(error);}
    });
    child.stdin.on('error', reject);
    child.stdin.end(JSON.stringify(request));
  });
}

export async function apply(ctx, config) {
  const {defineTool} = await import(pathToFileURL(path.join(config.dshRoot,'packages/core/tools/lib/index.js')));
  const output = {schema:{type:'object',properties:{},additionalProperties:true},
    render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]};
  const definitions = {
    catalog:'Discover callable production tools and exact request examples. Start with requests and compiler_templates. section=migration separates implementation from validation.',
    status:'Read persisted operation results and artifact paths. Does not retry operations.',
    plan:'Save a benchmark brief. Planning and capability choices belong to you; no fixed stage sequence.',
    sam3:'Segment an image through the configured SAM3 service. Returns candidate masks, scores and paths for inspection; source labels remain the authority for ground truth.',
    yoloe:'Detect requested objects through YOLOE; supports text and visual prompts. Inspect its output.',
    depthanything3:'Request Depth Anything 3 inference or query task/health. Inferred depth needs calibration before metric claims.',
    llm_local:'Call an explicitly configured local VLM for semantic annotation suggestions. Responses are predictions that can guide annotation or repair; source labels remain authoritative.',
    habitat:'Capture real Habitat RGB, depth and agent state with the bundled collector in its configured environment.',
    libero:'Collect LIBERO observations and simulator state using demo or zero actions in its configured environment.',
    carla:'Capture CARLA views and actor metadata from a configured running server.',
    isaac:'Capture a native cuboid scene with the independent Isaac collector in a configured Isaac environment. Supports cameras, depth, labels and recorded poses.',
    evidence:'Import evidence JSONL. provenance.path references one JSON source document; selectors are JSON pointers into it. All relative paths resolve against the input JSONL directory. media contains public images only; assets retains private raw depth, labels and oracle code. Derive JSON oracle outputs from binary simulation inputs in task code.',
    build:'Build model-visible items/media plus separate authority sources and private assets, deriving answers from source JSON and reporting coverage. Keep raw depth and authority labels in the evidence side of the bundle.',
    evaluate:'Score saved predictions with exact match; report missing answers. Does not call model APIs.',
    collaboration:'Share lightweight, structured handoffs in the task workspace. Agents can publish observations, artifacts, decisions, blockers and next actions, relate a handoff to earlier work, and reply to another agent. List or read the record when joining, resuming or reconciling parallel work; the protocol does not prescribe an orchestration graph.'
  };
  const object={type:'object',properties:{},additionalProperties:true};
  Object.assign(definitions, {
    spatial_catalog:'Read the 27-node spatial capability graph and executable template specifications. Conditional graph relations guide task selection without imposing prerequisite locks.',
    spatial_generate:'Generate grouped training and evaluation worlds, observations, program answers and feedback episodes from selected spatial templates. Train/dev/test roles remain separate.',
    spatial_evaluate:'Score saved answers or replay actions against program truth and environment states. No model API judging.',
    curriculum:'Update condition-specific mastery from development feedback and allocate a training budget. Compare fixed A, adaptive B and graph-guided C using the same candidate pool.',
    spatial_train:'Train a locally configured small model with windowed SFT, development feedback, curriculum sampling and resumable checkpoints. Specify the model and compute configuration explicitly.',
    training_monitor:'Read live training loss, capability feedback, allocations, checkpoints and guidance from a training run.'
  });
  definitions.spatial_export='Export spatial datasets as portable Parquet with embedded images and separate program authority.';
  definitions.spatial_experiment='Compare fixed A, adaptive B and graph-guided C from the same initial local checkpoint and training budget; report actual token and time costs.';
  definitions.backend='Inspect or explicitly start an optional configured backend in its own environment. Existing services keep their lifecycle outside this operation.';
  definitions.adapt_capture='Convert native Habitat/LIBERO/CARLA capture to compiler evidence. Habitat samples continuous visible surface regions and computes calibrated camera range from raw depth; semantic labels come from the selected source records.';
  const schemas={
    spatial_catalog:{section:{type:'string',enum:['graph','templates']},capability:{type:'string'},query:{type:'string'},offset:{type:'integer'},limit:{type:'integer'}},
    spatial_generate:{capability:{type:'string'},template_ids:{type:'array',items:{type:'string'}},exclude_template_ids:{type:'array',items:{type:'string'}},groups_per_profile:{type:'integer'},seed:{type:'integer'},render:{type:'boolean'},conditions:{type:'array',items:{type:'string',enum:['natural','supplied_intermediate','isolated']}},heldout_profiles:{type:'array',items:{type:'string'}}},
    spatial_export:{dataset:{type:'string',required:true}},
    spatial_experiment:{config:{type:'string',required:true},run:{type:'string'},seeds:{type:'array',items:{type:'integer'}}},
    spatial_evaluate:{dataset:{type:'string',required:true},partition:{type:'string',enum:['curriculum_dev','selection_dev','sealed_test']},predictions:{type:'string',required:true}},
    curriculum:{state:{type:'string',required:true},feedback:{type:'string'},checkpoint:{type:'string'},window_id:{type:'string'},condition:{type:'string',enum:['A','B','C']},budget:{type:'integer'},template_ids:{type:'array',items:{type:'string'}},settings:{type:'object',additionalProperties:true}},
    spatial_train:{config:{type:'string',required:true},run:{type:'string'},action:{type:'string',enum:['run','start']}},
    training_monitor:{run:{type:'string',required:true},guidance:{type:'object',additionalProperties:true,properties:{pause:{type:'boolean'},stop_after_window:{type:'boolean'},learning_rate:{type:'number'},hint_fraction:{type:'number'},difficulty:{type:'integer'}}}},
    backend:{name:{type:'string',required:true},action:{type:'string',enum:['status','start']}},
    adapt_capture:{input:{type:'string',required:true},simulator:{type:'string',enum:['habitat','libero','carla']},camera:{type:'object',additionalProperties:true},regions:{type:'integer'},radius:{type:'integer'}},
    catalog:{section:{type:'string',enum:['overview','templates','migration']},query:{type:'string'},offset:{type:'integer'},limit:{type:'integer'}},
    status:{},
    plan:{objective:{type:'string',required:true},sources:{type:'array',items:{type:'string'}},target_items:{type:'integer'},notes:{type:'string'}},
    evidence:{input:{type:'string',required:true,description:'Source records JSONL with provenance and JSON-pointer selectors.'}},
    build:{evidence:{type:'string',required:true},items:{type:'string',required:true}},
    evaluate:{authority:{type:'string',required:true},predictions:{type:'string',required:true}},
    collaboration:{action:{type:'string',enum:['publish','list','read'],required:true},history:{type:'boolean',description:'For list: include earlier versions. Default returns only the latest record per handoff, then applies filters.'},handoff_id:{type:'string'},role:{type:'string'},agent:{type:'string'},status:{type:'string',enum:['working','ready','blocked','done']},summary:{type:'string'},inputs:{type:'array',items:{type:'string'}},artifacts:{type:'array',items:{type:'string'}},findings:{type:'array',items:{type:'string'}},blockers:{type:'array',items:{type:'string'}},next_actions:{type:'array',items:{type:'string'}},parent_handoff_id:{type:'string'},reply_to:{type:'string'},related_handoff_ids:{type:'array',items:{type:'string'}},requested_from:{type:'array',items:{type:'string'}},decision:{type:'string'},confidence:{type:'number'},supersedes_handoff_id:{type:'string'},filter:{type:'object',additionalProperties:false,properties:{status:{type:'string'},role:{type:'string'},agent:{type:'string'}}}},
    isaac:{scene_program:{type:'string',required:true},timeout_seconds:{type:'integer'}}
  };
  const production = {
  "method": [
    "Read original professional methods adapted to the harness; search by skill name or topic.",
    {
      "query": {
        "type": "string"
      },
      "limit": {
        "type": "integer"
      }
    }
  ],
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
  "annotate": [
    "Run the original VLM→YOLOE→SAM3→DA3 chain per image; retain candidate annotations and a review queue. Predictions never become GT.",
    {
      "input": {
        "type": "string",
        "required": true
      },
      "hint": {
        "type": "string"
      },
      "max_terms": {
        "type": "integer"
      },
      "annotate_simulation": {
        "type": "boolean"
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
  "kinship": [
    "Analyze GT field nodes, relationships, reasoning chains and difficulty support using the original implementation.",
    {
      "input": {
        "type": "string",
        "required": true
      },
      "bundle": {
        "type": "string"
      },
      "max_records": {
        "type": "integer"
      },
      "max_pairs": {
        "type": "integer"
      }
    }
  ],
  "images": [
    "Create reusable neutral overlays, crops and panels from supplied annotations/recipes; bind the image manifest into the compiler bundle.",
    {
      "bundle": {
        "type": "string",
        "required": true
      },
      "input": {
        "type": "string"
      },
      "requests": {
        "type": "string"
      }
    }
  ],
  "compile": [
    "Compile authoritative evidence into reusable GT/asset/template/metric/generator bundle using migrated BenchClaw algorithms. Run a pilot before scale-up.",
    {
      "spec": {"description":"Validated benchmark_spec.json path or design object; compiler checks template/metric bindings", "oneOf":[{"type":"string"},{"type":"object","additionalProperties":true}]},
      "input": {
        "type": "string",
        "required": true
      },
      "templates": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "adapter": {
        "type": "string"
      },
      "generator": {
        "type": "string"
      },
      "image_requests": {
        "type": "string"
      },
      "difficulty": {
        "type": "object",
        "additionalProperties": true
      }
    }
  ],
  "synthesize": [
    "Generate pilot or full benchmark with deterministic oracle, screen invalid items, check scorer controls and package portable artifacts.",
    {
      "bundle": {
        "type": "string",
        "required": true
      },
      "input": {
        "type": "string"
      },
      "limit": {
        "type": "integer"
      },
      "seed": {
        "type": "integer"
      },
      "template_id": {
        "type": "string"
      },
      "mode": {
        "type": "string",
        "enum": [
          "pilot",
          "full"
        ]
      },
      "package": {
        "type": "boolean"
      }
    }
  ],
  "screen": [
    "Run deterministic malformed-option, media, anchor and provenance screening; output accepted/rejected items with findings.",
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
  "diagnose": [
    "Run original CDM/IRT response-matrix diagnostics; report small-sample limits and Rasch-style proxy interpretation.",
    {
      "scores": {
        "type": "array",
        "items": {
          "type": "string"
        },
        "required": true
      },
      "items": {
        "type": "string"
      }
    }
  ],
  "package": [
    "Package model-visible media/questions separately from authority and reproducible compiler code with copied input files.",
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
  schemas.compile.templates={oneOf:[{type:'string'},{type:'array',items:{oneOf:[{type:'string'},{type:'object',additionalProperties:true}]}}],description:'Built-in template IDs, complete template objects, or a JSONL registry path.'};
  schemas.clean.min_contrast={type:'number',description:'Minimum grayscale standard deviation; default 1 rejects near-constant images.'};
  schemas.compile.collection={type:'object',additionalProperties:true,description:'Optional full-synthesis gates: min_sources, min_unique_media, max_items_per_source_media, max_template_majority, reject_duplicate_evidence_questions.'};
  schemas.clean.min_bright_fraction={type:'number',description:'Optional fraction of pixels above luminance 16, e.g. 0.5 for well-lit captures.'};
  schemas.compile.recipes={type:'array',items:{type:'object',additionalProperties:true},description:'Optional declarative template contracts with answer_program and visible_anchor; supports comparisons, counts, ordering, distance, temporal differences and mappings.'};
  for(const tool of ['sam3','yoloe','depthanything3','llm_local']) schemas[tool]={
    action:{type:'string',description:'infer (default), health; DA3 also task, YOLOE visual, local VLM models.'},
    payload:{...object,description:'Native backend inference arguments. Catalog includes exact examples.'},task_id:{type:'string'},timeout_seconds:{type:'integer'}};
  for(const tool of ['habitat','libero','carla']) schemas[tool]={argv:{type:'array',items:{type:'string'},description:'Collector arguments; catalog has examples. Use --help for installed SDK collector options.'},timeout_seconds:{type:'integer'}};
  for (const [tool, description] of Object.entries(definitions)) {
    if (config.includeTools && !config.includeTools.includes(tool)) continue;
    if (tool === 'collaboration') continue;
    ctx.tools.register(defineTool({name:`benchforge_${tool}`, description,
      parameters:{workspace:{type:'string',required:true,description:'Absolute task workspace. Use the same workspace for related calls.'},...schemas[tool]},
      output, execute:(args,exec)=>{const {workspace,...request}=args; return invoke(config.python || 'python',workspace,config.configPath,tool,request,exec.signal);}}));
  }
  if (!config.includeTools || config.includeTools.includes('collaboration')) ctx.tools.register(defineTool({name:'benchforge_collaboration', description:definitions.collaboration,
    parameters:{workspace:{type:'string',required:true,description:'Absolute task workspace shared by related agents.'},...schemas.collaboration}, output,
    execute:async (args,exec)=>{
      const {workspace,...request}=args;
      const directory=path.join(path.resolve(workspace),'.benchforge','collaboration');
      const file=path.join(directory,'handoffs.jsonl');
      await fs.mkdir(directory,{recursive:true});
      if(request.action==='publish'){
        if(!request.role || !request.summary) throw new Error('collaboration publish needs role and summary');
        const handoff={handoff_id:request.handoff_id || `${Date.now()}-${Math.random().toString(36).slice(2,8)}`,
          created_at:new Date().toISOString(),agent:request.agent || exec.agent?.session?.id || 'current-agent',
          role:request.role,status:request.status || 'working',summary:request.summary,
          inputs:request.inputs || [],artifacts:request.artifacts || [],findings:request.findings || [],
          blockers:request.blockers || [],next_actions:request.next_actions || [],parent_handoff_id:request.parent_handoff_id || null,
          reply_to:request.reply_to || null,related_handoff_ids:request.related_handoff_ids || [],
          requested_from:request.requested_from || [],decision:request.decision || null,
          confidence:request.confidence ?? null,supersedes_handoff_id:request.supersedes_handoff_id || null};
        await fs.appendFile(file,JSON.stringify(handoff)+'\n','utf8');
        return handoff;
      }
      let rows=[];
      try{rows=(await fs.readFile(file,'utf8')).split(/\r?\n/).filter(Boolean).map(line=>JSON.parse(line));}
      catch(error){if(error.code!=='ENOENT') throw error;}
      if(request.action==='list') {
        if(!request.history) rows=[...new Map(rows.map(item=>[item.handoff_id,item])).values()];
        const filter=request.filter || {};
        return {handoffs:rows.filter(item =>
          (!filter.status || item.status===filter.status) &&
          (!filter.role || item.role===filter.role) &&
          (!filter.agent || item.agent===filter.agent))};
      }
      if(request.action==='read'){
        const row=rows.findLast(item=>item.handoff_id===request.handoff_id);
        if(!row) throw new Error(`Unknown collaboration handoff: ${request.handoff_id}`);
        return row;
      }
      throw new Error(`Unknown collaboration action: ${request.action}`);
    }}));
  if (!config.includeTools || config.includeTools.includes('view_image')) ctx.tools.register(defineTool({name:'benchforge_view_image', description:'Show a real local capture or annotation image to the model and user.',
    parameters:{path:{type:'string',required:true}},
    output:{...output,render:(_args,value)=>[{type:'image',attachment:value.image}]},
    execute:async args=>{
      const attachments=ctx.get('attachments');
      const data=await fs.readFile(args.path);
      return {image:await attachments.saveImage({data,mediaType:/\.jpe?g$/i.test(args.path)?'image/jpeg':'image/png',name:path.basename(args.path)})};
    }}));
}
