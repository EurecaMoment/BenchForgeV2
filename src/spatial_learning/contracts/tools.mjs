export const definitions = {
  "spatial_catalog": "Read the 27-node spatial capability graph and executable template specifications. Conditional graph relations guide task selection without imposing prerequisite locks.",
  "spatial_generate": "Generate grouped training and evaluation worlds, observations, program answers and feedback episodes from selected spatial templates. Train/dev/test roles remain separate.",
  "spatial_evaluate": "Score saved answers or replay actions against program truth and environment states. No model API judging.",
  "curriculum": "Update condition-specific mastery from development feedback and allocate a training budget. Compare fixed A, adaptive B and graph-guided C using the same candidate pool.",
  "spatial_train": "Train a locally configured small model with windowed SFT, development feedback, curriculum sampling and resumable checkpoints. Specify the model and compute configuration explicitly.",
  "training_monitor": "Read live training loss, capability feedback, allocations, checkpoints and guidance from a training run.",
  "spatial_export": "Export spatial datasets as portable Parquet with embedded images and separate program authority.",
  "spatial_experiment": "Compare fixed A, adaptive B and graph-guided C from the same initial local checkpoint and training budget; report actual token and time costs."
};

export const schemas = {
  "spatial_catalog": {
    "section": {
      "type": "string",
      "enum": [
        "graph",
        "templates"
      ]
    },
    "capability": {
      "type": "string"
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
  "spatial_generate": {
    "capability": {
      "type": "string"
    },
    "template_ids": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "exclude_template_ids": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "groups_per_profile": {
      "type": "integer"
    },
    "seed": {
      "type": "integer"
    },
    "render": {
      "type": "boolean"
    },
    "conditions": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "natural",
          "supplied_intermediate",
          "isolated"
        ]
      }
    },
    "heldout_profiles": {
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "spatial_export": {
    "dataset": {
      "type": "string",
      "required": true
    }
  },
  "spatial_experiment": {
    "config": {
      "type": "string",
      "required": true
    },
    "run": {
      "type": "string"
    },
    "seeds": {
      "type": "array",
      "items": {
        "type": "integer"
      }
    }
  },
  "spatial_evaluate": {
    "dataset": {
      "type": "string",
      "required": true
    },
    "partition": {
      "type": "string",
      "enum": [
        "curriculum_dev",
        "selection_dev",
        "sealed_test"
      ]
    },
    "predictions": {
      "type": "string",
      "required": true
    }
  },
  "curriculum": {
    "state": {
      "type": "string",
      "required": true
    },
    "feedback": {
      "type": "string"
    },
    "checkpoint": {
      "type": "string"
    },
    "window_id": {
      "type": "string"
    },
    "condition": {
      "type": "string",
      "enum": [
        "A",
        "B",
        "C"
      ]
    },
    "budget": {
      "type": "integer"
    },
    "template_ids": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "settings": {
      "type": "object",
      "additionalProperties": true
    }
  },
  "spatial_train": {
    "config": {
      "type": "string",
      "required": true
    },
    "run": {
      "type": "string"
    },
    "action": {
      "type": "string",
      "enum": [
        "run",
        "start"
      ]
    }
  },
  "training_monitor": {
    "run": {
      "type": "string",
      "required": true
    },
    "guidance": {
      "type": "object",
      "additionalProperties": true,
      "properties": {
        "pause": {
          "type": "boolean"
        },
        "stop_after_window": {
          "type": "boolean"
        },
        "learning_rate": {
          "type": "number"
        },
        "hint_fraction": {
          "type": "number"
        },
        "difficulty": {
          "type": "integer"
        }
      }
    }
  }
};
