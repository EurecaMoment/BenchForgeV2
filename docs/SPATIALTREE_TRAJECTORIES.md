# Isaac trajectory data for SpatialTree

BenchForgeV2 can extend an existing Isaac interaction recording with a native
trajectory bundle. The bundle is intended for moving-camera and moving-object
SpatialTree data, including N04 self-motion, N05 external motion, N09
cross-view correspondence and N14 motion understanding.

The feature is opt-in. Existing recordings, DSH, model services and Isaac
worker configuration remain unchanged unless an action explicitly contains a
`recording.spatialtree` object.

## Recording configuration

Add this to an executable interaction's recording settings. The image size is
the capture job's actual `width`/`height` and is recorded in the manifest:

```json
{
  "recording": {
    "every_steps": 4,
    "spatialtree": {
      "scenario_id": "camera_or_object_motion_001",
      "split": "train"
    }
  }
}
```

The existing Isaac executor reuses its persistent render product. Each sampled
frame writes:

- RGB PNG;
- distance-to-image-plane depth as `.npy`;
- semantic and instance annotator data as `.npy`;
- authored camera intrinsics and `T_world_camera_usd`;
- each scene object's `T_world_object`, visibility count and 2D box;
- simulation step, timestamp and the action phase.

The recorder writes `<interaction>_spatialtree/manifest.json`,
`frames.jsonl`, `actions.jsonl` and `<interaction>_spatialtree.zip`.
`manifest.json` declares
`schema=spatialtree.trajectory/v1`, `source=isaac_native`,
`ground_truth=true`, and the native simulator authority. It derives camera
motion, object motion and shared object IDs between consecutive frames. No
SpatialTracker, Qwen, SAM3, DA3 or other prediction is used to write these
GT fields.

## Boundaries

The manifest is high-confidence synthetic GT for the rendered scene state. It
does not claim real-world dynamics or calibration. Predicted depth, masks,
tracks or language descriptions may be added as separate candidate fields, but
must not overwrite the native `ground_truth` fields. Keep train/dev/test splits
by scenario, object arrangement and trajectory, rather than randomly splitting
adjacent video frames.

For camera-only video, use an interaction with
`action:"record_trajectory"`, a declared `camera_id`, `duration_steps`, and
the same recording object. Add an optional `camera_path` list of keyframes
with `step:0`, `position`, and `target`. Keyframes are linearly interpolated at
simulation steps and the last pose is held. Omitting `camera_path` records a
fixed camera. This can also be added to `apply_force` or `robot_push` to
combine self-motion and object motion. The native ZIP is uploaded as a normal
capture file and is available through the existing evidence tool.

For example, add this to a SceneProgram that declares a camera with ID `view`:

```json
{
  "id": "walk_camera",
  "action": "record_trajectory",
  "camera_id": "view",
  "duration_steps": 120,
  "recording": {
    "every_steps": 4,
    "spatialtree": {"scenario_id": "room_walk_001", "split": "train"},
    "camera_path": [
      {"step": 0, "position": [0, -2, 1.5], "target": [0, 0, 0.8]},
      {"step": 120, "position": [2, 0, 1.5], "target": [0, 0, 0.8]}
    ]
  }
}
```

Submit the program with the existing `spatialforge_capture` tool. Read
`capture/interaction_0_spatialtree.json` with `spatialforge_evidence` and copy
`capture/interaction_0_spatialtree.zip` into the task workspace. The ZIP
contains native GT; build model-visible RGB/video inputs separately so that
evaluation inputs do not expose the answers. Correspondence is by scene object
identity and visibility, not dense surface-point tracking or optical flow.

The recorder module is dependency-free. Recording tests also use NumPy and
OpenCV, as does the existing video exporter. Validate outside Isaac with:

```bash
python -m unittest components/spatialforge/desktop/test_spatialtree_trajectory.py
```
