# Resident TRELLIS.2 reconstruction

`spatialforge.trellis_service` keeps the TRELLIS.2-4B pipeline on one dedicated
GPU. It takes local/shared-storage 1024x1024 images and optional object masks,
then exports GLB geometry with embedded 4096x4096 base-color and
metallic/roughness textures. The profile uses `1024_cascade`, twelve sampling
steps per stage, and an export target of one million triangles.

The runtime root contains `src/trellis2`, its native dependencies, and local
weights under `models/trellis2`, `models/dinov3`, and `models/birefnet`.
The pipeline configuration must point to those installed paths and use
`PublicDinoV3FeatureExtractor` for the public timm DINOv3 checkpoint loader.
Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` after installing all weights.
Use a compatible isolated PyTorch/CUDA environment; imports alone do not confirm
that inference or export works on the target GPU and driver.

Example configuration:

```json
{"root":"/opt/spatialforge/trellis2","host":"127.0.0.1","port":3956,"max_requests":64,"cpu_threads":8}
```

```bash
CUDA_VISIBLE_DEVICES=7 python -m spatialforge.trellis_service --config service.json
python integrations/spatialforge/trellis/benchmark.py --mode single \
  --root /opt/spatialforge/trellis2 --url http://127.0.0.1:3956 --image /path/input.png
python integrations/spatialforge/trellis/benchmark.py --mode burst64 \
  --root /opt/spatialforge/trellis2 --url http://127.0.0.1:3956 --image /path/input.png
```

The single-request benchmark validates a fresh complete artifact. The burst
benchmark sends 64 requests with distinct seeds and one-second deadlines.
It counts complete artifacts, never queue acknowledgements, cached results,
or timeout responses. Expired queued work is canceled. A failed deadline test
does not measure sustainable successful throughput; report its failures plainly.
One GPU worker and 64 request slots do not establish a 64-request latency SLA.
First-use kernel compilation is part of a cold request's observed wall time.

The resident exporter preserves `remesh=True`, geometry/UV processing, sampling
steps, texture size, and the original OpenCV Telea algorithms and radii. Its
`lossless-parallel-v1` profile runs the four independent inpainting operations
concurrently, and encodes PNG images in two workers with compression level 1.
Lower PNG compression increases encoded size while preserving every decoded
pixel. `trellis_postprocess.py` retains the installed TRELLIS.2 `o_voxel`
postprocessor with stage timing and this independent CPU work separated.

Each asset includes `export_timing` for GPU-synchronized geometry, UV, texture
processing, PNG encoding, and GLB packaging/writing. A controlled `/infer`
request can set `verify_inpaint=true` to compare the original serial operations
against the parallel output on the same actual PBR arrays. It fails before
publishing if any pixel differs. This optional audit repeats the serial work;
leave it off when measuring production latency. Geometry changes such as
disabling remeshing require separate quality acceptance.

For the existing FIT reconstruction route, keep the legacy tool name `sam3d`
and point its external resident gateway port at this service. Set
`SPATIALFORGE_RECONSTRUCTION_PROVIDER=trellis2` on the SpatialForge API so
reconstruction cache identities and the operator catalog identify the new
provider. Gateway availability must allow TRELLIS PBR export when legacy
`texture_baking` is supplied. The plugin exposes `spatialforge_trellis` and
retains `spatialforge_sam3d` as a compatibility alias.

Every TRELLIS result declares `source_frame=y_up`. Preserve that value during
mesh import; the existing converter transforms it into the scene's Z-up frame.
TRELLIS supplies mesh/PBR predictions, without metric scale, source-camera pose,
or Gaussian splats. Existing paired SAM3D assets retain their earlier metadata.

Before switching services, save the affected units/configuration, stop and
disable only the old SAM3D unit, and verify that the selected GPU is available.
Wait for active gateway/API jobs before restarting those CPU services. Acceptance
requires a complete target-generated GLB and one real request through the FIT
API; health status or a source-server demo is insufficient.
