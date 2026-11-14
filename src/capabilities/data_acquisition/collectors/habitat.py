# Adapted from EurecaMoment/BenchClaw (Apache-2.0).
# Modified: configurable machine paths; callable independently of legacy stages.
import argparse
import json
import math
from pathlib import Path

from PIL import Image
import habitat_sim
import numpy as np




def parse_args():
    parser = argparse.ArgumentParser(description="Collect Habitat RGB frames and GT from multiple scenes.")
    parser.add_argument("--output-dir", default="output_dataset")
    parser.add_argument("--scenes", required=True, help="Comma separated scene .glb paths")
    parser.add_argument("--frames-per-scene", type=int, default=12)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--seed", type=int, default=12345)
    return parser.parse_args()


def serialize_vec3(values):
    return [round(float(v), 6) for v in values]


def serialize_quat(quat):
    return {
        "x": round(float(quat.x), 6),
        "y": round(float(quat.y), 6),
        "z": round(float(quat.z), 6),
        "w": round(float(quat.w), 6),
    }


def sensor_specs(width, height):
    rgb = habitat_sim.CameraSensorSpec()
    rgb.uuid = "color_sensor"
    rgb.sensor_type = habitat_sim.SensorType.COLOR
    rgb.resolution = [height, width]
    rgb.position = [0.0, 1.5, 0.0]
    rgb.hfov = 90.0

    depth = habitat_sim.CameraSensorSpec()
    depth.uuid = "depth_sensor"
    depth.sensor_type = habitat_sim.SensorType.DEPTH
    depth.resolution = [height, width]
    depth.position = [0.0, 1.5, 0.0]
    depth.hfov = 90.0

    return [rgb, depth]


def make_sim(scene, width, height):
    sim_cfg = habitat_sim.SimulatorConfiguration()
    sim_cfg.scene_id = scene
    sim_cfg.gpu_device_id = 0

    agent_cfg = habitat_sim.agent.AgentConfiguration()
    agent_cfg.sensor_specifications = sensor_specs(width, height)

    cfg = habitat_sim.Configuration(sim_cfg, [agent_cfg])
    sim = habitat_sim.Simulator(cfg)
    agent = sim.initialize_agent(0)
    return sim, agent


def save_depth(depth_array, output_path):
    depth = np.nan_to_num(depth_array, nan=0.0, posinf=0.0, neginf=0.0)
    depth = np.clip(depth, 0.0, 10.0)
    depth_u16 = (depth / 10.0 * 65535.0).astype(np.uint16)
    Image.fromarray(depth_u16).save(output_path)


def sample_agent_states(sim, frames_per_scene):
    pathfinder = sim.pathfinder
    if not pathfinder.is_loaded:
        raise RuntimeError("Habitat pathfinder is not loaded for this scene")

    states = []
    for _ in range(frames_per_scene):
        pos = pathfinder.get_random_navigable_point()
        yaw = np.random.uniform(-math.pi, math.pi)
        states.append((pos, yaw))
    return states


def collect_scene(scene_path, output_root, frames_per_scene, width, height):
    scene_name = Path(scene_path).stem
    scene_dir = output_root / scene_name
    rgb_dir = scene_dir / "rgb"
    depth_dir = scene_dir / "depth"
    rgb_dir.mkdir(parents=True, exist_ok=True)
    depth_dir.mkdir(parents=True, exist_ok=True)

    sim, agent = make_sim(scene_path, width, height)
    records = []

    try:
        for frame_index, (position, yaw) in enumerate(sample_agent_states(sim, frames_per_scene)):
            state = habitat_sim.AgentState()
            state.position = position
            state.rotation = habitat_sim.utils.common.quat_from_angle_axis(yaw, np.array([0.0, 1.0, 0.0]))
            agent.set_state(state)

            obs = sim.get_sensor_observations()

            rgb_name = f"{scene_name}_{frame_index:05d}.png"
            depth_name = f"{scene_name}_{frame_index:05d}.png"
            rgb_path = rgb_dir / rgb_name
            depth_path = depth_dir / depth_name

            Image.fromarray(obs["color_sensor"][:, :, :3]).save(rgb_path)
            save_depth(obs["depth_sensor"], depth_path)
            raw_depth_path = depth_dir / f"{scene_name}_{frame_index:05d}.npy"
            np.save(raw_depth_path, obs["depth_sensor"])

            agent_state = agent.get_state()
            records.append(
                {
                    "frame_index": frame_index,
                    "scene": scene_name,
                    "scene_path": scene_path,
                    "rgb_path": str(rgb_path),
                    "depth_path": str(depth_path),
                    "raw_depth_path": str(raw_depth_path),
                    "depth_preview_encoding": "uint16 clipped to 0..10 meters; use raw_depth_path for measurements",
                    "agent_state": {
                        "position": serialize_vec3(agent_state.position),
                        "rotation": serialize_quat(agent_state.rotation),
                    },
                    "sensor_states": {
                        sensor_name: {
                            "position": serialize_vec3(sensor_state.position),
                            "rotation": serialize_quat(sensor_state.rotation),
                        }
                        for sensor_name, sensor_state in agent_state.sensor_states.items()
                    },
                    "navmesh_loaded": bool(sim.pathfinder.is_loaded),
                }
            )
    finally:
        sim.close()

    manifest = {
        "scene": scene_name,
        "scene_path": scene_path,
        "frames": len(records),
        "image_size": [width, height],
        "camera": {"fx": width / 2, "fy": width / 2, "cx": (width - 1) / 2, "cy": (height - 1) / 2,
                   "width": width, "height": height, "hfov_degrees": 90.0},
        "depth_semantics": {"type": "camera_forward_z", "units": "meters", "raw_format": "float32_npy",
                            "note": "Camera-forward depth is not Euclidean range. Convert with pixel coordinates and intrinsics for distance-to-camera questions."},
        "records": records,
    }
    with open(scene_dir / "gt.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main():
    args = parse_args()
    np.random.seed(args.seed)

    output_root = Path(args.output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    scenes = [item.strip() for item in args.scenes.split(",") if item.strip()]
    summary = {
        "frames_per_scene": args.frames_per_scene,
        "image_size": [args.width, args.height],
        "scenes": [],
    }

    for scene in scenes:
        summary["scenes"].append(
            collect_scene(scene, output_root, args.frames_per_scene, args.width, args.height)
        )

    with open(output_root / "collection_manifest.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Collected scenes:", len(summary["scenes"]))
    for item in summary["scenes"]:
        print(f"  {item['scene']}: {item['frames']} frames")
    print("Output:", output_root)


if __name__ == "__main__":
    main()
