# GPU services with storage on a separate host

The DSH and SpatialForge process can stay on the orchestration host while a GPU
host runs model workers behind an HTTP endpoint. Model code, Python environments,
weights, inputs, logs and outputs may all remain on operator-mounted shared
storage. The GPU host does not require a second copy of model weights.

Alternatively, weights can reside on the GPU host while code, inputs and outputs
remain on shared storage. Configure `path_rewrites` to map the orchestration
host's model paths to their compute-host locations:

```json
{
  "path_rewrites": {
    "/shared/models/image-editor": "/data/models/image-editor"
  }
}
```

Rewriting applies to exact path values and their descendants, including nested
request fields; embedded paths in natural-language strings stay unchanged.
Map model directories only to retain shared input and output locations. The
service reports `local-models-shared-code-output` when mappings are configured.
This setting does not download or copy weights.

Mount the required storage at the same absolute paths on both hosts, including
the targets of absolute symlinks. Use a separate output mount when results are
stored outside the source home directory. Do not mount over existing deployments.
The filesystem retains its data on the storage host; reading model weights into
RAM and VRAM is necessary for inference. Cold startup depends on network speed.

Run the API using the GPU host's existing system Python. The server itself uses
the Python standard library; each model uses its configured interpreter:

```sh
python3 -B /shared/code/spatialforge/inference_service.py \
  --config /shared/deployment/inference.json --gpus 1,4 --port 3951
```

Example operator configuration:

```json
{
  "project": "/shared/model-workers",
  "environment": {
    "PYTHONPATH": "/shared/model-workers/src:/shared/spatialforge/src",
    "HOME": "/shared/runtime/home",
    "TMPDIR": "/shared/runtime/tmp",
    "TORCH_EXTENSIONS_DIR": "/shared/runtime/extensions"
  },
  "tools": {
    "diffusion": {
      "python": "/shared/environments/diffusion/bin/python",
      "module": "spatialforge.diffusion_worker",
      "minimum_mib": 28000
    }
  }
}
```

Create the configured temporary and extension directories on the storage host.
The executor disables Python bytecode writes, CUDA's disk cache and model
downloads. Frameworks that require temporary files use the configured storage
host directories. Existing compatible Python environments on the GPU host can
also be reused without installing another environment.

The default listener is loopback. Forward the port over SSH to the orchestration
host, then set `SPATIALFORGE_INFERENCE_URL=http://127.0.0.1:3951` in the
SpatialForge service environment. DSH continues to use its normal SpatialForge
tools. Local GPU selection and local model startup are bypassed when the remote
endpoint is configured. An unavailable endpoint returns an error; it does not
start a second model on the orchestration host.

Direct API callers can submit `POST /jobs` with `tool`, `request` and `work`,
read `GET /jobs/{id}`, and cancel with `DELETE /jobs/{id}`. `GET /health` reports
API readiness and the allowed GPU set; it does not claim that a model has loaded
or passed an inference test. Each job writes `execution.json`, `worker.log`,
`response.json` and `remote_job.json` to shared storage, including the actual
host, GPU and worker PID. Jobs on distinct available GPUs can run concurrently.

Before switching production calls, make a real request, inspect the returned
artifact and confirm the execution receipt names the intended host and GPU.
Preserve the previous service environment for rollback. Removing the endpoint
setting restores local execution. Mounts, tunnels and service launch supervision
are deployment concerns; transient services must be recreated after a host reboot.
