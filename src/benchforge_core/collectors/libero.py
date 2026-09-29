# Adapted from EurecaMoment/BenchClaw (Apache-2.0).
# Modified: configurable machine paths; callable independently of legacy stages.
import argparse
import json
import os
from pathlib import Path
import sys

# Running this file as a CLI must not shadow the installed libero package.
sys.path = [p for p in sys.path if Path(p or '.').resolve() != Path(__file__).resolve().parent]

import h5py
import numpy as np
from PIL import Image

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

from libero.libero import benchmark, get_libero_path
from libero.libero.envs import OffScreenRenderEnv


BDDL_BASE = os.environ.get("LIBERO_BDDL_ROOT") or get_libero_path("bddl_files")
DATASET_BASE = os.environ.get("LIBERO_DATASET_ROOT") or get_libero_path("datasets")


def parse_args():
    parser = argparse.ArgumentParser(description="Collect LIBERO env RGB and GT from live offscreen envs.")
    parser.add_argument("--suite", default="libero_10")
    parser.add_argument("--output-dir", default="output_env_dataset")
    parser.add_argument("--max-tasks", type=int, default=3)
    parser.add_argument("--steps-per-task", type=int, default=8)
    parser.add_argument("--image-size", type=int, default=128)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--action-source", choices=["demo", "zeros"], default="demo")
    return parser.parse_args()


def to_serializable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict):
        return {k: to_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_serializable(v) for v in value]
    return value


def rgb_keys(obs):
    return [k for k, v in obs.items() if isinstance(v, np.ndarray) and v.ndim == 3 and v.shape[-1] == 3]


def save_rgb_images(obs, out_dir, frame_idx):
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key in rgb_keys(obs):
        path = out_dir / key / f"{frame_idx:05d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(obs[key]).save(path)
        paths[key] = str(path)
    return paths


def demo_path_for_task(task, suite_name):
    return os.path.join(DATASET_BASE, suite_name, f"{task.name}_demo.hdf5")


def load_demo_actions(task, suite_name, steps_per_task):
    demo_path = demo_path_for_task(task, suite_name)
    if not os.path.exists(demo_path):
        raise FileNotFoundError(f"Demo HDF5 not found for task {task.name}: {demo_path}")

    with h5py.File(demo_path, "r") as f:
        demo_names = sorted(list(f["data"].keys()))
        demo = f["data"][demo_names[0]]
        actions = np.array(demo["actions"][:steps_per_task], dtype=np.float32)
        init_states = np.array(demo["states"][:1])
    return demo_path, actions, init_states


def collect_task(task_suite, task_id, output_dir, suite_name, steps_per_task, image_size, seed, action_source):
    task = task_suite.get_task(task_id)
    bddl_path = os.path.join(BDDL_BASE, task.problem_folder, task.bddl_file)
    env = OffScreenRenderEnv(
        bddl_file_name=bddl_path,
        camera_heights=image_size,
        camera_widths=image_size,
    )
    env.seed(seed)
    env.reset()

    demo_path = None
    if action_source == "demo":
        demo_path, replay_actions, replay_init_states = load_demo_actions(task, suite_name, steps_per_task)
        env.set_init_state(replay_init_states[0])
    else:
        init_states = task_suite.get_task_init_states(task_id)
        env.set_init_state(init_states[0])
        replay_actions = np.zeros((steps_per_task, 7), dtype=np.float32)

    task_dir = output_dir / f"task_{task_id:02d}_{task.name}"
    records = []

    try:
        for step_idx, action in enumerate(replay_actions):
            obs, reward, done, info = env.step(action)
            image_paths = save_rgb_images(obs, task_dir / "images", step_idx)

            record = {
                "step": step_idx,
                "action": to_serializable(action),
                "reward": float(reward),
                "done": bool(done),
                "image_paths": image_paths,
                "obs": {
                    k: to_serializable(v)
                    for k, v in obs.items()
                    if k not in image_paths
                },
                "info": to_serializable(info),
            }
            records.append(record)
            if done:
                break
    finally:
        env.close()

    manifest = {
        "task_id": task_id,
        "task_name": task.name,
        "language": task.language,
        "bddl_file": bddl_path,
        "action_source": action_source,
        "demo_path": demo_path,
        "steps": len(records),
        "records": records,
    }

    with open(task_dir / "gt.json", "w", encoding="utf-8") as fout:
        json.dump(manifest, fout, indent=2)
    return manifest


def main():
    args = parse_args()
    benchmark_dict = benchmark.get_benchmark_dict()
    task_suite = benchmark_dict[args.suite]()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifests = []
    for task_id in range(min(args.max_tasks, task_suite.n_tasks)):
        manifests.append(
            collect_task(
                task_suite,
                task_id,
                output_dir,
                args.suite,
                args.steps_per_task,
                args.image_size,
                args.seed,
                args.action_source,
            )
        )

    summary = {
        "suite": args.suite,
        "tasks": manifests,
    }
    with open(output_dir / "collection_manifest.json", "w", encoding="utf-8") as fout:
        json.dump(summary, fout, indent=2)

    print("Collected tasks:", len(manifests))
    for item in manifests:
        print(f"  {item['task_name']}: {item['steps']} steps")
    print("Output:", output_dir)


if __name__ == "__main__":
    main()
