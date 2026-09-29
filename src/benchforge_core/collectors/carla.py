# Adapted from EurecaMoment/BenchClaw (Apache-2.0).
# Modified: configurable machine paths; callable independently of legacy stages.
import argparse
import json
import math
import os
import queue
import random
import socket
import subprocess
import time
import sys
from pathlib import Path

# The adapter name must not shadow the CARLA SDK during direct script execution.
sys.path = [p for p in sys.path if Path(p or '.').resolve() != Path(__file__).resolve().parent]

import carla
import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect RGB frames from one or more CARLA maps."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--tm-port", type=int, default=5800)
    parser.add_argument("--output-dir", default="output_rgb")
    parser.add_argument(
        "--maps",
        default="",
        help="Comma separated map names. Empty means current map only.",
    )
    parser.add_argument(
        "--all-maps", action="store_true", help="Iterate all drivable Town maps."
    )
    parser.add_argument("--frames-per-map", type=int, default=30)
    parser.add_argument(
        "--save-every", type=int, default=1, help="Save one frame every N world ticks."
    )
    parser.add_argument(
        "--warmup-ticks",
        type=int,
        default=40,
        help="Ticks to let the vehicle start moving before sampling.",
    )
    parser.add_argument(
        "--min-save-distance",
        type=float,
        default=8.0,
        help="Minimum ego travel distance in meters between saved frames.",
    )
    parser.add_argument(
        "--min-speed-mps",
        type=float,
        default=2.0,
        help="Do not save until ego speed reaches this threshold.",
    )
    parser.add_argument(
        "--max-idle-ticks",
        type=int,
        default=200,
        help="Respawn the vehicle if it stays too slow for too long.",
    )
    parser.add_argument(
        "--max-respawns",
        type=int,
        default=3,
        help="Maximum vehicle respawns when traffic is blocked.",
    )
    parser.add_argument(
        "--speed-diff",
        type=float,
        default=-35.0,
        help="TrafficManager percentage speed difference. Negative makes ego faster than limit.",
    )
    parser.add_argument(
        "--lead-distance",
        type=float,
        default=5.0,
        help="TrafficManager following distance in meters.",
    )
    parser.add_argument(
        "--cameras",
        default="front,side_left,side_right,rear,top",
        help="Comma separated camera names to attach. Default: all 5 angles.",
    )
    parser.add_argument(
        "--metadata-cameras",
        default="all",
        help="Comma separated camera names that should compute visible object metadata. Use 'all' or a subset like 'front,top'.",
    )
    parser.add_argument(
        "--save-instance-maps",
        action="store_true",
        help="Save raw instance segmentation images alongside RGB outputs.",
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--fov", type=int, default=90)
    parser.add_argument(
        "--min-visible-pixels",
        type=int,
        default=12,
        help="Minimum visible pixels for an actor to be kept in visible_objects.",
    )
    parser.add_argument("--delta-seconds", type=float, default=0.05)
    parser.add_argument("--format", choices=["png", "jpg"], default="jpg")
    parser.add_argument("--jpeg-quality", type=int, default=90)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument(
        "--restart-per-map",
        action="store_true",
        help="Start a fresh CARLA server process for each map.",
    )
    parser.add_argument(
        "--server-script",
        default=os.environ.get("CARLA_SERVER_SCRIPT"),
    )
    parser.add_argument("--server-start-timeout", type=float, default=90.0)
    parser.add_argument("--server-ready-timeout", type=float, default=60.0)
    parser.add_argument("--load-wait-seconds", type=float, default=3.0)
    parser.add_argument("--load-world-timeout", type=float, default=120.0)
    return parser.parse_args()


def normalize_map_name(name):
    if "/" in name:
        return name.rsplit("/", 1)[-1]
    return name


def resolve_maps(client, world, args):
    if args.all_maps:
        maps = []
        for name in client.get_available_maps():
            short_name = normalize_map_name(name)
            if short_name.startswith("Town"):
                maps.append(short_name)
        return sorted(set(maps))

    if args.maps.strip():
        return [item.strip() for item in args.maps.split(",") if item.strip()]

    return [normalize_map_name(world.get_map().name)]


def wait_for_port(host, port, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(1.0)
    raise TimeoutError(f"Timed out waiting for {host}:{port} to listen")


def port_is_listening(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def reserve_port_block(host, start_port, block_size=2, step=10, attempts=200):
    candidate = start_port
    for _ in range(attempts):
        blocked = False
        for offset in range(block_size):
            if port_is_listening(host, candidate + offset):
                blocked = True
                break
        if not blocked:
            return candidate
        candidate += step
    raise RuntimeError(f"Could not find a free port block starting from {start_port}")


def connect_client(host, port, ready_timeout):
    deadline = time.time() + ready_timeout
    last_error = None
    while time.time() < deadline:
        try:
            client = carla.Client(host, port)
            client.set_timeout(60.0)
            client.get_world()
            return client
        except RuntimeError as exc:
            last_error = exc
            time.sleep(1.0)
    raise TimeoutError(
        f"Timed out waiting for CARLA RPC readiness on {host}:{port}: {last_error}"
    )


def start_server(args, rpc_port, map_name):
    log_dir = os.path.abspath(args.output_dir)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(
        log_dir, f"server_{normalize_map_name(map_name)}_{rpc_port}.log"
    )
    log_handle = open(log_path, "w", encoding="utf-8")

    state_root = f"/tmp/carla_capture_{rpc_port}"
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = os.path.join(state_root, "config")
    env["XDG_CACHE_HOME"] = os.path.join(state_root, "cache")
    os.makedirs(env["XDG_CONFIG_HOME"], exist_ok=True)
    os.makedirs(env["XDG_CACHE_HOME"], exist_ok=True)

    command = [os.path.abspath(args.server_script), f"-carla-rpc-port={rpc_port}"]
    process = subprocess.Popen(
        command, stdout=log_handle, stderr=subprocess.STDOUT, env=env
    )

    try:
        wait_for_port(args.host, rpc_port, args.server_start_timeout)
        client = connect_client(args.host, rpc_port, args.server_ready_timeout)
        return process, log_handle, log_path, client
    except Exception:
        stop_server(process, log_handle)
        raise


def stop_server(process, log_handle):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10.0)
    log_handle.close()


def bootstrap_maps(args):
    rpc_port = reserve_port_block(args.host, args.port)
    bootstrap_args = argparse.Namespace(**vars(args))
    bootstrap_args.port = rpc_port
    process, log_handle, log_path, client = start_server(
        bootstrap_args, rpc_port, "bootstrap"
    )
    try:
        world = client.get_world()
        maps = resolve_maps(client, world, args)
        return maps, log_path, rpc_port
    finally:
        stop_server(process, log_handle)


def ensure_map_loaded(client, map_name, wait_seconds, load_world_timeout):
    world = client.get_world()
    current_map = normalize_map_name(world.get_map().name)
    if current_map != normalize_map_name(map_name):
        print(f"loading map {map_name}")
        client.set_timeout(load_world_timeout)
        world = client.load_world(map_name)
        client.set_timeout(60.0)
        time.sleep(wait_seconds)
    return world


def destroy_actors(client, actors):
    actor_ids = [actor.id for actor in actors if actor is not None]
    if actor_ids:
        client.apply_batch(
            [carla.command.DestroyActor(actor_id) for actor_id in actor_ids]
        )


def sensor_actors(camera_sensors):
    return [info["actor"] for info in camera_sensors.values()]


def location_distance(a, b):
    dx = a.x - b.x
    dy = a.y - b.y
    dz = a.z - b.z
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def speed_mps(velocity):
    return (
        velocity.x * velocity.x + velocity.y * velocity.y + velocity.z * velocity.z
    ) ** 0.5


def serialize_location(location):
    return {
        "x": round(location.x, 6),
        "y": round(location.y, 6),
        "z": round(location.z, 6),
    }


def serialize_rotation(rotation):
    return {
        "pitch": round(rotation.pitch, 6),
        "yaw": round(rotation.yaw, 6),
        "roll": round(rotation.roll, 6),
    }


def serialize_transform(transform):
    return {
        "location": serialize_location(transform.location),
        "rotation": serialize_rotation(transform.rotation),
    }


def resolve_metadata_cameras(args, camera_names):
    value = args.metadata_cameras.strip().lower()
    if value == "all":
        return set(camera_names)
    selected = {
        name.strip() for name in args.metadata_cameras.split(",") if name.strip()
    }
    return {name for name in selected if name in camera_names}


def build_projection_matrix(width, height, fov, is_behind_camera=False):
    focal = width / (2.0 * np.tan(fov * np.pi / 360.0))
    k = np.identity(3)
    k[0, 0] = k[1, 1] = -focal if is_behind_camera else focal
    k[0, 2] = width / 2.0
    k[1, 2] = height / 2.0
    return k


def get_image_point(loc, k, world_to_camera):
    point = np.array([loc.x, loc.y, loc.z, 1.0])
    point_camera = np.dot(world_to_camera, point)
    point_camera = np.array([point_camera[1], -point_camera[2], point_camera[0]])

    if point_camera[2] == 0:
        return None

    point_img = np.dot(k, point_camera)
    point_img[0] /= point_img[2]
    point_img[1] /= point_img[2]
    return point_img[0:2]


def project_actor_bbox_3d(actor, camera_actor, width, height, fov):
    world_to_camera = np.array(camera_actor.get_transform().get_inverse_matrix())
    k = build_projection_matrix(width, height, fov)
    k_back = build_projection_matrix(width, height, fov, is_behind_camera=True)
    cam_transform = camera_actor.get_transform()
    cam_location = cam_transform.location
    cam_forward = cam_transform.get_forward_vector()

    vertices = actor.bounding_box.get_world_vertices(actor.get_transform())
    points_2d = []
    edges = []

    for vertex in vertices:
        ray = vertex - cam_location
        point_k = k if cam_forward.dot(ray) > 0 else k_back
        projected = get_image_point(vertex, point_k, world_to_camera)
        if projected is not None:
            points_2d.append(projected)

    if not points_2d:
        return None

    xs = [float(p[0]) for p in points_2d]
    ys = [float(p[1]) for p in points_2d]
    projected_bbox = {
        "xmin": max(0, int(min(xs))),
        "ymin": max(0, int(min(ys))),
        "xmax": min(width - 1, int(max(xs))),
        "ymax": min(height - 1, int(max(ys))),
    }

    edge_pairs = [
        [0, 1],
        [1, 3],
        [3, 2],
        [2, 0],
        [0, 4],
        [4, 5],
        [5, 1],
        [5, 7],
        [7, 6],
        [6, 4],
        [6, 2],
        [7, 3],
    ]
    for start, end in edge_pairs:
        p1 = get_image_point(vertices[start], k, world_to_camera)
        p2 = get_image_point(vertices[end], k, world_to_camera)
        if p1 is None or p2 is None:
            continue
        edges.append(
            [
                [round(float(p1[0]), 3), round(float(p1[1]), 3)],
                [round(float(p2[0]), 3), round(float(p2[1]), 3)],
            ]
        )

    return {
        "bbox_2d_from_3d": projected_bbox,
        "projected_edges": edges,
    }


def decode_instance_segmentation(image):
    img = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
        (image.height, image.width, 4)
    )
    semantic_labels = img[..., 2]
    actor_ids = img[..., 1].astype(np.uint32) + (img[..., 0].astype(np.uint32) << 8)
    return semantic_labels, actor_ids


def actor_speed(actor):
    velocity = actor.get_velocity()
    return math.sqrt(
        velocity.x * velocity.x + velocity.y * velocity.y + velocity.z * velocity.z
    )


def collect_visible_actor_metadata(camera_info, instance_image, world):
    semantic_labels, actor_ids = decode_instance_segmentation(instance_image)
    unique_actor_ids = np.unique(actor_ids)

    visible_objects = []
    semantic_histogram = {}

    for label in np.unique(semantic_labels):
        count = int(np.count_nonzero(semantic_labels == label))
        if count > 0:
            semantic_histogram[int(label)] = count

    for actor_id in unique_actor_ids:
        if actor_id == 0:
            continue

        mask = actor_ids == actor_id
        pixel_count = int(np.count_nonzero(mask))
        if pixel_count < camera_info["min_visible_pixels"]:
            continue

        ys, xs = np.where(mask)
        bbox = {
            "xmin": int(xs.min()),
            "ymin": int(ys.min()),
            "xmax": int(xs.max()),
            "ymax": int(ys.max()),
            "pixel_count": pixel_count,
        }

        actor = world.get_actor(int(actor_id))
        semantic_ids = np.unique(semantic_labels[mask]).astype(int).tolist()

        item = {
            "actor_id": int(actor_id),
            "semantic_labels": semantic_ids,
            "bbox_2d": bbox,
        }

        if actor is not None:
            projected_3d = project_actor_bbox_3d(
                actor,
                camera_info["actor"],
                camera_info["image_width"],
                camera_info["image_height"],
                camera_info["fov"],
            )
            item.update(
                {
                    "type_id": actor.type_id,
                    "actor_pose": serialize_transform(actor.get_transform()),
                    "speed_mps": round(actor_speed(actor), 3),
                    "distance_to_camera_m": round(
                        actor.get_transform().location.distance(
                            camera_info["actor"].get_transform().location
                        ),
                        3,
                    ),
                    "bbox_3d_projected": projected_3d,
                }
            )
            if hasattr(actor, "semantic_tags"):
                item["semantic_tags"] = [int(tag) for tag in actor.semantic_tags]

        visible_objects.append(item)

    return {
        "visible_actor_count": len(visible_objects),
        "visible_actors": visible_objects,
        "semantic_histogram": semantic_histogram,
    }


def camera_mounts(vehicle):
    bbox = vehicle.bounding_box
    center = bbox.location
    extent = bbox.extent

    front_x = center.x + extent.x + 0.25
    rear_x = center.x - extent.x - 0.3
    side_y = extent.y + 0.18
    roof_z = center.z + extent.z
    front_z = roof_z + 0.2
    side_z = roof_z + 0.15
    rear_z = roof_z + 0.2
    top_z = roof_z + 12.0

    return {
        "front": {
            "loc": carla.Location(x=front_x, y=0.0, z=front_z),
            "rot": carla.Rotation(pitch=-6.0, yaw=0.0, roll=0.0),
        },
        "side_right": {
            "loc": carla.Location(x=center.x + 0.15, y=-side_y, z=side_z),
            "rot": carla.Rotation(pitch=-10.0, yaw=-92.0, roll=0.0),
        },
        "side_left": {
            "loc": carla.Location(x=center.x + 0.15, y=side_y, z=side_z),
            "rot": carla.Rotation(pitch=-10.0, yaw=92.0, roll=0.0),
        },
        "rear": {
            "loc": carla.Location(x=rear_x, y=0.0, z=rear_z),
            "rot": carla.Rotation(pitch=-8.0, yaw=180.0, roll=0.0),
        },
        "top": {
            "loc": carla.Location(x=center.x, y=0.0, z=top_z),
            "rot": carla.Rotation(pitch=-90.0, yaw=0.0, roll=0.0),
        },
    }


def setup_vehicle_and_camera(
    world, traffic_manager, blueprints, spawn_points, args, rng
):
    vehicle_bp = rng.choice(list(blueprints.filter("vehicle.*")))
    vehicle = spawn_vehicle(world, vehicle_bp, spawn_points, rng)

    camera_bp = blueprints.find("sensor.camera.rgb")
    camera_bp.set_attribute("image_size_x", str(args.width))
    camera_bp.set_attribute("image_size_y", str(args.height))
    camera_bp.set_attribute("fov", str(args.fov))
    camera_bp.set_attribute("sensor_tick", "0.0")
    camera_bp.set_attribute("lens_circle_falloff", "3.0")
    camera_bp.set_attribute("chromatic_aberration_intensity", "0.0")
    camera_bp.set_attribute("motion_blur_intensity", "0.0")

    inst_camera_bp = blueprints.find("sensor.camera.instance_segmentation")
    inst_camera_bp.set_attribute("image_size_x", str(args.width))
    inst_camera_bp.set_attribute("image_size_y", str(args.height))
    inst_camera_bp.set_attribute("fov", str(args.fov))
    inst_camera_bp.set_attribute("sensor_tick", "0.0")

    camera_defs = camera_mounts(vehicle)

    camera_names = [n.strip() for n in args.cameras.split(",") if n.strip()]
    if not camera_names:
        camera_names = list(camera_defs.keys())

    metadata_cameras = resolve_metadata_cameras(args, camera_names)

    sensors = {}
    for cam_name in camera_names:
        if cam_name not in camera_defs:
            print(f"  WARNING: unknown camera '{cam_name}', skipping")
            continue
        cam = world.spawn_actor(
            camera_bp,
            carla.Transform(camera_defs[cam_name]["loc"], camera_defs[cam_name]["rot"]),
            attach_to=vehicle,
        )
        inst_cam = world.spawn_actor(
            inst_camera_bp,
            carla.Transform(camera_defs[cam_name]["loc"], camera_defs[cam_name]["rot"]),
            attach_to=vehicle,
        )
        q = queue.Queue()
        inst_q = queue.Queue()
        cam.listen(q.put)
        inst_cam.listen(inst_q.put)
        sensors[cam_name] = {
            "actor": cam,
            "queue": q,
            "inst_actor": inst_cam,
            "inst_queue": inst_q,
            "image_width": args.width,
            "image_height": args.height,
            "fov": args.fov,
            "min_visible_pixels": args.min_visible_pixels,
            "collect_metadata": cam_name in metadata_cameras,
            "mount": {
                "location": serialize_location(camera_defs[cam_name]["loc"]),
                "rotation": serialize_rotation(camera_defs[cam_name]["rot"]),
            },
        }
        print(
            f"  camera {cam_name} attached at loc={camera_defs[cam_name]['loc']} rot={camera_defs[cam_name]['rot']}"
        )

    vehicle.set_autopilot(True, traffic_manager.get_port())
    traffic_manager.distance_to_leading_vehicle(vehicle, args.lead_distance)
    traffic_manager.auto_lane_change(vehicle, True)
    traffic_manager.random_left_lanechange_percentage(vehicle, 20.0)
    traffic_manager.random_right_lanechange_percentage(vehicle, 20.0)
    traffic_manager.vehicle_percentage_speed_difference(vehicle, args.speed_diff)

    return vehicle, sensors


def spawn_vehicle(world, vehicle_bp, spawn_points, rng):
    shuffled_points = list(spawn_points)
    rng.shuffle(shuffled_points)
    for spawn_point in shuffled_points:
        vehicle = world.try_spawn_actor(vehicle_bp, spawn_point)
        if vehicle is not None:
            return vehicle
    raise RuntimeError("Failed to spawn vehicle after trying all spawn points")


def configure_world(world, traffic_manager, delta_seconds):
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = delta_seconds
    world.apply_settings(settings)
    traffic_manager.set_synchronous_mode(True)


def reset_world(world, traffic_manager):
    try:
        settings = world.get_settings()
        settings.synchronous_mode = False
        settings.fixed_delta_seconds = None
        world.apply_settings(settings)
        traffic_manager.set_synchronous_mode(False)
    except RuntimeError as exc:
        print(f"warning: failed to reset world cleanly: {exc}")


def capture_map(client, world, map_name, args, rng):
    client.set_timeout(60.0)
    traffic_manager = client.get_trafficmanager(args.tm_port)
    configure_world(world, traffic_manager, args.delta_seconds)
    traffic_manager.global_percentage_speed_difference(args.speed_diff)

    # Pulse world after enabling synchronous mode so sensor listeners get frames
    for _ in range(5):
        world.tick()

    blueprints = world.get_blueprint_library()
    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        raise RuntimeError(f"No spawn points available in {map_name}")

    vehicle = None
    camera_sensors = {}  # {cam_name: {"actor": cam, "queue": q}}

    def respawn_rig():
        nonlocal vehicle, camera_sensors
        if camera_sensors:
            for cam_name, info in camera_sensors.items():
                try:
                    info["actor"].stop()
                except Exception:
                    pass
                try:
                    info["inst_actor"].stop()
                except Exception:
                    pass
        destroy_actors(
            client,
            sensor_actors(camera_sensors)
            + [info["inst_actor"] for info in camera_sensors.values()]
            + [vehicle],
        )
        vehicle, camera_sensors = setup_vehicle_and_camera(
            world, traffic_manager, blueprints, spawn_points, args, rng
        )

    respawn_rig()

    map_dir = os.path.join(args.output_dir, normalize_map_name(map_name))

    saved_frames = 0
    tick_count = 0
    total_distance = 0.0
    last_saved_distance = 0.0
    idle_ticks = 0
    respawn_count = 0
    last_location = None
    tick_durations = []
    frame_records = []
    start_time = time.time()
    try:
        # Warmup
        for _ in range(args.warmup_ticks):
            world.tick()
            for cam_name, info in camera_sensors.items():
                try:
                    info["queue"].get(timeout=3.0)
                except Exception:
                    pass
                try:
                    info["inst_queue"].get(timeout=3.0)
                except Exception:
                    pass

        while saved_frames < args.frames_per_map:
            tick_start = time.time()
            world.tick()
            tick_durations.append(time.time() - tick_start)
            tick_count += 1

            # Poll all camera queues for one frame each
            images = {}
            instance_images = {}
            for cam_name, info in camera_sensors.items():
                try:
                    images[cam_name] = info["queue"].get(timeout=3.0)
                except Exception:
                    images[cam_name] = None
                try:
                    instance_images[cam_name] = info["inst_queue"].get(timeout=3.0)
                except Exception:
                    instance_images[cam_name] = None

            transform = vehicle.get_transform()
            velocity = vehicle.get_velocity()
            current_speed = speed_mps(velocity)
            current_loc = transform.location

            if last_location is not None:
                total_distance += location_distance(current_loc, last_location)
            last_location = carla.Location(current_loc.x, current_loc.y, current_loc.z)

            if current_speed < args.min_speed_mps:
                idle_ticks += 1
            else:
                idle_ticks = 0

            if idle_ticks >= args.max_idle_ticks:
                if respawn_count >= args.max_respawns:
                    raise RuntimeError(
                        f"Vehicle stayed under {args.min_speed_mps} m/s for {idle_ticks} ticks on {map_name}"
                    )
                respawn_count += 1
                idle_ticks = 0
                last_location = None
                print(
                    f"respawn {normalize_map_name(map_name)} blocked vehicle count={respawn_count}"
                )
                for cam_name in camera_sensors:
                    try:
                        while not camera_sensors[cam_name]["queue"].empty():
                            camera_sensors[cam_name]["queue"].get_nowait()
                    except Exception:
                        pass
                respawn_rig()
                for _ in range(args.warmup_ticks):
                    world.tick()
                    for cam_name, info in camera_sensors.items():
                        try:
                            info["queue"].get(timeout=3.0)
                        except Exception:
                            pass
                        try:
                            info["inst_queue"].get(timeout=3.0)
                        except Exception:
                            pass
                continue

            if tick_count % args.save_every != 0:
                continue
            if current_speed < args.min_speed_mps:
                continue
            if total_distance - last_saved_distance < args.min_save_distance:
                continue

            # Save frame for each camera
            cam_dirs = []
            image_paths = {}
            instance_paths = {}
            for cam_name, info in camera_sensors.items():
                cam_dir = os.path.join(map_dir, cam_name)
                os.makedirs(cam_dir, exist_ok=True)
                fname = (
                    f"{normalize_map_name(map_name)}_{saved_frames:05d}.{args.format}"
                )
                path = os.path.join(cam_dir, fname)
                if images.get(cam_name) is not None:
                    images[cam_name].save_to_disk(path)
                    image_paths[cam_name] = path
                if (
                    args.save_instance_maps
                    and info["collect_metadata"]
                    and instance_images.get(cam_name) is not None
                ):
                    inst_dir = os.path.join(map_dir, f"{cam_name}_instance")
                    os.makedirs(inst_dir, exist_ok=True)
                    instance_path = os.path.join(inst_dir, Path(fname).stem + '.png')
                    instance_images[cam_name].save_to_disk(instance_path)
                    instance_paths[cam_name] = instance_path
                cam_dirs.append(cam_name)

            saved_frames += 1
            last_saved_distance = total_distance

            rec = {
                "frame_index": saved_frames - 1,
                "sim_frame": next(
                    (image.frame for image in images.values() if image is not None), 0
                ),
                "ego_pose": serialize_transform(transform),
                "speed_mps": round(current_speed, 3),
                "distance_since_start": round(total_distance, 3),
                "cameras": cam_dirs,
                "image_paths": image_paths,
                "instance_paths": instance_paths,
                "camera_poses": {
                    cam_name: {
                        "mount": info["mount"],
                        "world": serialize_transform(info["actor"].get_transform()),
                        "visible_objects": (
                            collect_visible_actor_metadata(
                                info,
                                instance_images[cam_name],
                                world,
                            )
                            if info["collect_metadata"] and instance_images.get(cam_name) is not None
                            else None
                        ),
                    }
                    for cam_name, info in camera_sensors.items()
                },
            }
            frame_records.append(rec)
            print(
                f"saved {normalize_map_name(map_name)} sim_frame={rec['sim_frame']} count={saved_frames} "
                f"cameras={','.join(cam_dirs)} speed={current_speed:.2f}mps dist={total_distance:.2f}m"
            )
    finally:
        for cam_name, info in camera_sensors.items():
            try:
                info["actor"].stop()
            except Exception:
                pass
            try:
                info["inst_actor"].stop()
            except Exception:
                pass
        destroy_actors(
            client,
            sensor_actors(camera_sensors)
            + [info["inst_actor"] for info in camera_sensors.values()]
            + [vehicle],
        )
        reset_world(world, traffic_manager)

    elapsed = time.time() - start_time
    return {
        "map": normalize_map_name(map_name),
        "saved_frames": saved_frames,
        "tick_count": tick_count,
        "elapsed_seconds": round(elapsed, 3),
        "capture_fps": round(saved_frames / elapsed, 3) if elapsed else None,
        "tick_fps": round(tick_count / elapsed, 3) if elapsed else None,
        "mean_tick_seconds": round(sum(tick_durations) / len(tick_durations), 4)
        if tick_durations
        else None,
        "distance_travelled_m": round(total_distance, 3),
        "respawn_count": respawn_count,
        "frames_per_camera": {n: saved_frames for n in camera_sensors},
        "frame_records": frame_records,
        "output_dir": map_dir,
        "camera_names": list(camera_sensors.keys()),
        "metadata_cameras": sorted(
            [
                cam_name
                for cam_name, info in camera_sensors.items()
                if info["collect_metadata"]
            ]
        ),
        "save_instance_maps": args.save_instance_maps,
        "camera_mounts": {
            cam_name: info["mount"] for cam_name, info in camera_sensors.items()
        },
    }


def main():
    args = parse_args()
    rng = random.Random(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)

    bootstrap_log = None
    bootstrap_port = None
    if args.restart_per_map:
        maps, bootstrap_log, bootstrap_port = bootstrap_maps(args)
    else:
        client = carla.Client(args.host, args.port)
        client.set_timeout(30.0)
        world = client.get_world()
        maps = resolve_maps(client, world, args)

    summary = {
        "host": args.host,
        "port": args.port,
        "tm_port": args.tm_port,
        "maps": maps,
        "frames_per_map": args.frames_per_map,
        "save_every": args.save_every,
        "resolution": [args.width, args.height],
        "format": args.format,
        "delta_seconds": args.delta_seconds,
        "restart_per_map": args.restart_per_map,
        "bootstrap_log": bootstrap_log,
        "bootstrap_port": bootstrap_port,
        "results": [],
    }

    if args.restart_per_map:
        for index, map_name in enumerate(maps):
            rpc_port = reserve_port_block(args.host, args.port + index * 10)
            tm_port = reserve_port_block(
                args.host, args.tm_port + index * 10, block_size=1
            )
            run_args = argparse.Namespace(**vars(args))
            run_args.port = rpc_port
            run_args.tm_port = tm_port

            process, log_handle, log_path, client = start_server(
                run_args, rpc_port, map_name
            )
            try:
                world = ensure_map_loaded(
                    client,
                    map_name,
                    run_args.load_wait_seconds,
                    run_args.load_world_timeout,
                )
                result = capture_map(client, world, map_name, run_args, rng)
                result["server_log"] = log_path
                result["rpc_port"] = rpc_port
                result["tm_port"] = tm_port
                summary["results"].append(result)
            finally:
                stop_server(process, log_handle)
    else:
        for map_name in maps:
            world = ensure_map_loaded(
                client, map_name, args.load_wait_seconds, args.load_world_timeout
            )
            summary["results"].append(capture_map(client, world, map_name, args, rng))

    summary_path = os.path.join(args.output_dir, "collection_manifest.json")
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(f"manifest {summary_path}")


if __name__ == "__main__":
    main()
