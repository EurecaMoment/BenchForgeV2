export const definitions = {
  "catalog": "Discover callable production tools and exact request examples. See exact request examples and the V2 task template catalog.",
  "status": "Read persisted operation results and artifact paths. Does not retry operations.",
  "plan": "Save a benchmark brief. Planning and capability choices belong to you; no fixed stage sequence.",
  "model_infer": "Call the configured OpenAI-compatible vision model for semantic annotation suggestions. Responses are predictions that can guide annotation or repair; source labels remain authoritative.",
  "habitat": "Capture real Habitat RGB, depth and agent state with the bundled collector in its configured environment.",
  "libero": "Collect LIBERO observations and simulator state using demo or zero actions in its configured environment.",
  "carla": "Capture CARLA views and actor metadata from a configured running server.",
  "evidence": "Import evidence JSONL. provenance.path references one JSON source document; selectors are JSON pointers into it. All relative paths resolve against the input JSONL directory. media contains public images only; assets retains private raw depth, labels and oracle code. Derive JSON oracle outputs from binary simulation inputs in task code.",
  "build": "Build model-visible items/media plus separate authority sources and private assets, deriving answers from source JSON and reporting coverage. Keep raw depth and authority labels in the evidence side of the bundle.",
  "evaluate": "Score saved predictions with exact match; report missing answers. Does not call model APIs.",
  "pipeline_catalog": "Discover composable production recipes and the user-provided 89 tasks / 267 exact measurement templates. Capability links retrieve candidates; they do not define primary measurement or inherit validation. Read conditions and execution support before selecting.",
  "pipeline_plan": "Prefer request_path or assessment_path for durable plans. Use validate_only=true to obtain all issues, patch only the existing file, then submit the same path with false. Never retranscribe a large document after an error. Read pipeline_catalog section=plan_template and supply the complete assessment document alongside the executable selections. Create a persistent production plan for one capability or multiple exact task templates. Interpret user intent and supply selections with template_ids/count/reason; plain text without explicit IDs returns candidates for your semantic decomposition. Compose recipes with shared typed artifacts. A user-edited plan blocks older plans: read edit_revision.base_plan and user_markdown. If exactly one assessment-yaml block is explicitly changed, preserve the saved assessment, allocation and production inputs exactly. If the block is absent or unchanged, resolve changed prose into assessment fields and inputs, then pass markdown_resolution entries with the exact schema [{path,before,after,instruction}]: one per changed assessment leaf, path relative to assessment (dot-separated keys and numeric array indices), before/after exact old/new JSON values, instruction an exact quote outside the YAML block from either newly added or modified prose absent from old prose, or old prose actually deleted from new prose. Unchanged quotes and quotes absent from both versions are rejected; quotes must cover actual prose deletions. Keep protected scene_selection and split. Validate assessment, selections and matching inputs; resolve seed through assessment.dataset.seed. Update executable steps or evidence for non-parameter prose changes. Preserve exact user_markdown; pipeline_plan validates and audits the resolution on the applied plan.",
  "pipeline_run": "Execute or resume a frozen pipeline plan. Reuses completed steps, submits to the existing single Isaac queue, and returns waiting/needs_input/needs_evidence when unfinished. For exact document templates supply protocol-bound source evidence when no program generator exists. State completed concerns production, not benchmark approval.",
  "pipeline_status": "Read the persisted pipeline step states and artifacts without submitting or retrying work.",
  "pipeline_artifacts": "Inspect the typed artifact lineage for a persisted run. This is a read-only manifest of candidates, contracts and parent references; it does not approve a benchmark or retry a step.",
  "pipeline_repair_plan": "Create a deterministic, reviewable repair proposal for one failed artifact. It selects the smallest repair scope from the failure code and never changes GT, templates or remote services.",
  "pipeline_evaluate": "Score saved answers against the exact imported template protocol: numeric error with units, grouped ordering and IoU/detection sets. Separate per-template metrics; no model API judging or pooled 27-capability claim.",
  "adapt_capture": "Convert native Habitat/LIBERO/CARLA capture to compiler evidence. Habitat samples continuous visible surface regions and computes calibrated camera range from raw depth; semantic labels come from the selected source records.",
  "stage_review": "After each completed S1-S5 stage, open a durable 300-second user instruction window with its saved artifact and a stable production key. An executable plan opens S1 automatically; a pending user-edit draft does not. Call wait with a default 60-second call budget and repeat until elapsed or continued, then resume existing work; the saved window still lasts 300 seconds. A paused or needs_input window blocks production; apply the saved user instruction before acknowledging. Do not skip waits or report them as capture queue blockage.",
  "acquire": "Import local records or download an explicitly selected dataset file, preserving original labels and source fields.",
  "normalize": "Normalize JSONL/JSON/CSV/Parquet/images into reusable evidence records; preserve original source fields.",
  "clean": "Clean selected records and readable media; optional Data-Juicer cleans derived text without overwriting labels.",
  "literature": "Retrieve primary papers from explicit URLs or an arXiv query and extract full text. Downloaded papers remain unread until inspected.",
  "research_review": "Bind literature claims to exact passages in downloaded text; reject fabricated or absent quotations.",
  "design": "Validate benchmark intent, capability definitions, source/template/metric bindings and emit Q-matrix plus specification.",
  "score": "Score saved predictions with declared deterministic metrics and stratified reports; missing score zero, duplicate/unknown IDs fail.",
  "model_eval": "Run explicitly configured models on public questions and images only; save responses, usage, failures and scores. No model question review.",
  "baselines": "Run first-choice and seeded random-choice controls without reading gold in the responder. Results are proxy diagnostics.",
  "package": "Create public and authority packages with media and questions. Optionally include a caller-provided reproducibility bundle.",
  "report": "Merge real/proxy score files into a model-item matrix and evaluation report, rejecting duplicate responses.",
  "usage": "Summarize exact provider usage counters from an explicit DSH event export; disclose absent counters and subtree coverage."
};

export const schemas = {
  "stage_review": {
    "action": {
      "type": "string",
      "enum": [
        "open",
        "status",
        "wait",
        "continue",
        "pause",
        "instruction",
        "acknowledge"
      ]
    },
    "stage": {
      "type": "string",
      "enum": [
        "S1",
        "S2",
        "S3",
        "S4",
        "S5"
      ]
    },
    "key": {
      "type": "string"
    },
    "artifact": {
      "type": "string"
    },
    "review_id": {
      "type": "integer"
    },
    "instruction": {
      "type": "string"
    },
    "timeout_seconds": {
      "type": "number",
      "default": 60,
      "description": "Single wait call budget in seconds, 0..300; default 60. The saved review deadline remains 300 seconds."
    }
  },
  "pipeline_catalog": {
    "section": {
      "type": "string",
      "enum": [
        "pipelines",
        "capabilities",
        "tasks",
        "templates",
        "protocol",
        "plan_template"
      ]
    },
    "capability": {
      "type": "string"
    },
    "template_ids": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "task_ids": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "query": {
      "type": "string"
    },
    "item_id": {
      "type": "string"
    },
    "offset": {
      "type": "integer"
    },
    "limit": {
      "type": "integer"
    }
  },
  "pipeline_plan": {
    "request_path": {
      "type": "string",
      "description": "JSON request file relative to workspace or absolute. Preferred for large plans and edits: save once, submit its path. File cannot be combined with inline plan fields; host session context is preserved."
    },
    "assessment_path": {
      "type": "string",
      "description": "Saved assessment JSON file relative to workspace or absolute. Use with matching selections/inputs instead of copying its contents into assessment; cannot combine with assessment."
    },
    "validate_only": {
      "type": "boolean",
      "description": "Check the saved plan without saving a production plan or opening S1. Returns all correction issues; edit only those fields in the same file, then submit with false."
    },
    "applies_edit": {
      "type": "string",
      "description": "Path of the active user-edited plan; preserve exact user_markdown. Explicitly changed YAML means retain its assessment/inputs. For prose-only edits, normalize every changed assessment leaf using markdown_resolution and quote the actual added/modified prose or deleted old prose verbatim."
    },
    "user_markdown": {
      "type": "string",
      "description": "Exact complete user-edited Markdown from the active plan. Required unchanged when applying."
    },
    "markdown_resolution": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "path": {
            "type": "string",
            "required": true,
            "description": "Assessment-relative dot path; array positions are decimal indices, e.g. coverage.0.count."
          },
          "before": {
            "oneOf": [
              {
                "type": "string"
              },
              {
                "type": "number"
              },
              {
                "type": "boolean"
              },
              {
                "type": "null"
              },
              {
                "type": "object",
                "additionalProperties": true
              },
              {
                "type": "array",
                "items": {
                  "type": "json"
                }
              }
            ],
            "description": "Exact old JSON value for this field."
          },
          "after": {
            "oneOf": [
              {
                "type": "string"
              },
              {
                "type": "number"
              },
              {
                "type": "boolean"
              },
              {
                "type": "null"
              },
              {
                "type": "object",
                "additionalProperties": true
              },
              {
                "type": "array",
                "items": {
                  "type": "json"
                }
              }
            ],
            "description": "Exact resolved new JSON value for this field."
          },
          "instruction": {
            "type": "string",
            "required": true,
            "description": "Exact quote outside the YAML block from newly added/modified prose absent from the old version, or old prose actually deleted in the new version. Unchanged or nonexistent quotes are rejected."
          }
        }
      }
    },
    "assessment": {
      "type": "object",
      "additionalProperties": true,
      "description": "Complete resolved assessment. For prose-only edits, synchronize quantity fields with selections and inputs; validate against the saved scene selection."
    },
    "objective": {
      "type": "string"
    },
    "pipeline_id": {
      "type": "string"
    },
    "capability": {
      "type": "string"
    },
    "capabilities": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "template_ids": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "task_ids": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "target_items": {
      "type": "integer"
    },
    "selections": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "template_ids": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "required": true
          },
          "count": {
            "type": "integer",
            "required": true
          },
          "reason": {
            "type": "string",
            "required": true
          }
        }
      }
    },
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": true,
        "properties": {
          "id": {
            "type": "string",
            "required": true
          },
          "uses": {
            "type": "string",
            "required": true
          },
          "pipeline_id": {
            "type": "string"
          },
          "arguments": {
            "type": "object",
            "additionalProperties": true
          },
          "await_terminal": {
            "type": "boolean"
          }
        }
      }
    },
    "inputs": {
      "type": "object",
      "additionalProperties": true
    },
    "evidence": {
      "type": "string"
    },
    "seed": {
      "type": "integer"
    },
    "split": {
      "type": "string",
      "enum": [
        "train",
        "dev",
        "test",
        "sealed"
      ]
    },
    "service_config": {
      "type": "string"
    }
  },
  "pipeline_run": {
    "plan": {
      "type": "string",
      "required": true
    },
    "run": {
      "type": "string"
    },
    "bindings": {
      "type": "object",
      "additionalProperties": true
    }
  },
  "pipeline_status": {
    "run": {
      "type": "string",
      "required": true
    }
  },
  "pipeline_artifacts": {
    "run": {
      "type": "string",
      "required": true
    },
    "artifact_id": {
      "type": "string"
    },
    "status": {
      "type": "string",
      "enum": [
        "draft",
        "candidate",
        "verified",
        "rejected",
        "superseded"
      ]
    }
  },
  "pipeline_repair_plan": {
    "run": {
      "type": "string",
      "required": true
    },
    "artifact_id": {
      "type": "string"
    },
    "failure_code": {
      "type": "string"
    },
    "reason": {
      "type": "string"
    }
  },
  "pipeline_evaluate": {
    "dataset": {
      "type": "string",
      "required": true
    },
    "predictions": {
      "type": "string",
      "required": true
    }
  },
  "adapt_capture": {
    "input": {
      "type": "string",
      "required": true
    },
    "simulator": {
      "type": "string",
      "enum": [
        "habitat",
        "libero",
        "carla"
      ]
    },
    "camera": {
      "type": "object",
      "additionalProperties": true
    },
    "regions": {
      "type": "integer"
    },
    "radius": {
      "type": "integer"
    }
  },
  "catalog": {
    "section": {
      "type": "string",
      "enum": [
        "overview",
        "templates"
      ]
    },
    "query": {
      "type": "string"
    },
    "offset": {
      "type": "integer"
    },
    "limit": {
      "type": "integer"
    }
  },
  "status": {},
  "plan": {
    "objective": {
      "type": "string",
      "required": true
    },
    "sources": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "target_items": {
      "type": "integer"
    },
    "notes": {
      "type": "string"
    }
  },
  "evidence": {
    "input": {
      "type": "string",
      "required": true,
      "description": "Source records JSONL with provenance and JSON-pointer selectors."
    }
  },
  "build": {
    "evidence": {
      "type": "string",
      "required": true
    },
    "items": {
      "type": "string",
      "required": true
    }
  },
  "evaluate": {
    "authority": {
      "type": "string",
      "required": true
    },
    "predictions": {
      "type": "string",
      "required": true
    }
  },
  "acquire": {
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
  },
  "normalize": {
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
  },
  "clean": {
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
    },
    "min_contrast": {
      "type": "number",
      "description": "Minimum grayscale standard deviation; default 1 rejects near-constant images."
    },
    "min_bright_fraction": {
      "type": "number",
      "description": "Optional fraction of pixels above luminance 16, e.g. 0.5 for well-lit captures."
    }
  },
  "literature": {
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
  },
  "research_review": {
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
  },
  "design": {
    "spec": {
      "type": "object",
      "additionalProperties": true,
      "required": true
    }
  },
  "score": {
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
  },
  "model_eval": {
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
  },
  "baselines": {
    "items": {
      "type": "string",
      "required": true
    },
    "seed": {
      "type": "integer"
    }
  },
  "package": {
    "items": {
      "type": "string",
      "required": true
    },
    "bundle": {
      "type": "string"
    }
  },
  "report": {
    "scores": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "required": true
    }
  },
  "usage": {
    "events": {
      "type": "string",
      "required": true
    }
  },
  "model_infer": {
    "action": {
      "type": "string",
      "enum": [
        "infer",
        "models"
      ]
    },
    "payload": {
      "type": "object",
      "properties": {},
      "additionalProperties": true,
      "description": "OpenAI chat completion request for candidate annotations."
    },
    "timeout_seconds": {
      "type": "integer"
    }
  },
  "habitat": {
    "argv": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Collector arguments; catalog has examples. Use --help for installed SDK collector options."
    },
    "timeout_seconds": {
      "type": "integer"
    }
  },
  "libero": {
    "argv": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Collector arguments; catalog has examples. Use --help for installed SDK collector options."
    },
    "timeout_seconds": {
      "type": "integer"
    }
  },
  "carla": {
    "argv": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Collector arguments; catalog has examples. Use --help for installed SDK collector options."
    },
    "timeout_seconds": {
      "type": "integer"
    }
  }
};
