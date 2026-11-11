"""CARLA geometry helpers used by the bundled capture worker."""
import numpy as np


def camera_mounts(vehicle):
    import carla

    bounds = vehicle.bounding_box
    center, extent = bounds.location, bounds.extent
    front_x = center.x + extent.x + 0.25
    rear_x = center.x - extent.x - 0.3
    side_y = extent.y + 0.18
    roof_z = center.z + extent.z
    return {
        "front": {"loc": carla.Location(x=front_x, y=0.0, z=roof_z + 0.2),
                  "rot": carla.Rotation(pitch=-6.0, yaw=0.0, roll=0.0)},
        "side_right": {"loc": carla.Location(x=center.x + 0.15, y=-side_y, z=roof_z + 0.15),
                       "rot": carla.Rotation(pitch=-10.0, yaw=-92.0, roll=0.0)},
        "side_left": {"loc": carla.Location(x=center.x + 0.15, y=side_y, z=roof_z + 0.15),
                      "rot": carla.Rotation(pitch=-10.0, yaw=92.0, roll=0.0)},
        "rear": {"loc": carla.Location(x=rear_x, y=0.0, z=roof_z + 0.2),
                 "rot": carla.Rotation(pitch=-8.0, yaw=180.0, roll=0.0)},
        "top": {"loc": carla.Location(x=center.x, y=0.0, z=roof_z + 12.0),
                "rot": carla.Rotation(pitch=-90.0, yaw=0.0, roll=0.0)},
    }


def _projection_matrix(width, fov, behind=False):
    focal = width / (2.0 * np.tan(fov * np.pi / 360.0))
    matrix = np.identity(3)
    matrix[0, 0] = matrix[1, 1] = -focal if behind else focal
    matrix[0, 2] = width / 2.0
    matrix[1, 2] = width / 2.0
    return matrix


def _image_point(location, matrix, world_to_camera):
    point = np.dot(world_to_camera, [location.x, location.y, location.z, 1.0])
    camera = np.array([point[1], -point[2], point[0]])
    if camera[2] == 0:
        return None
    projected = np.dot(matrix, camera)
    projected[:2] /= projected[2]
    return projected[:2]


def _project_actor_bbox(actor, camera, width, height, fov):
    transform = camera.get_transform()
    world_to_camera = np.asarray(transform.get_inverse_matrix())
    forward = transform.get_forward_vector()
    projection = _projection_matrix(width, fov)
    behind_projection = _projection_matrix(width, fov, behind=True)
    vertices = actor.bounding_box.get_world_vertices(actor.get_transform())
    points = []
    for vertex in vertices:
        ray = vertex - transform.location
        point = _image_point(vertex, projection if forward.dot(ray) > 0 else behind_projection, world_to_camera)
        if point is not None:
            points.append(point)
    if not points:
        return None
    projected_bbox = {
            "xmin": max(0, int(min(point[0] for point in points))),
            "ymin": max(0, int(min(point[1] for point in points))),
            "xmax": min(width - 1, int(max(point[0] for point in points))),
            "ymax": min(height - 1, int(max(point[1] for point in points))),
    }
    edge_pairs = ([0, 1], [1, 3], [3, 2], [2, 0], [0, 4], [4, 5],
                  [5, 1], [5, 7], [7, 6], [6, 4], [6, 2], [7, 3])
    edges = []
    for start, end in edge_pairs:
        first = _image_point(vertices[start], projection, world_to_camera)
        second = _image_point(vertices[end], projection, world_to_camera)
        if first is not None and second is not None:
            edges.append([
                [round(float(first[0]), 3), round(float(first[1]), 3)],
                [round(float(second[0]), 3), round(float(second[1]), 3)],
            ])
    return {"bbox_2d_from_3d": projected_bbox, "projected_edges": edges}


def actor_speed(actor):
    velocity = actor.get_velocity()
    return float(np.linalg.norm([velocity.x, velocity.y, velocity.z]))


def _serialize_transform(transform):
    location, rotation = transform.location, transform.rotation
    return {
        "location": {axis: round(getattr(location, axis), 6) for axis in ("x", "y", "z")},
        "rotation": {axis: round(getattr(rotation, axis), 6) for axis in ("pitch", "yaw", "roll")},
    }


def collect_visible_actor_metadata(camera_info, instance_image, world):
    image = np.frombuffer(instance_image.raw_data, dtype=np.uint8).reshape(
        (instance_image.height, instance_image.width, 4)
    )
    semantic_labels = image[..., 2]
    actor_ids = image[..., 1].astype(np.uint32) + (image[..., 0].astype(np.uint32) << 8)
    semantic_histogram = {
        int(label): int(np.count_nonzero(semantic_labels == label))
        for label in np.unique(semantic_labels)
    }
    visible_actors = []
    for actor_id in np.unique(actor_ids):
        if actor_id == 0:
            continue
        mask = actor_ids == actor_id
        pixel_count = int(np.count_nonzero(mask))
        if pixel_count < camera_info["min_visible_pixels"]:
            continue
        ys, xs = np.where(mask)
        actor = world.get_actor(int(actor_id))
        item = {
            "actor_id": int(actor_id),
            "semantic_labels": np.unique(semantic_labels[mask]).astype(int).tolist(),
            "bbox_2d": {"xmin": int(xs.min()), "ymin": int(ys.min()),
                        "xmax": int(xs.max()), "ymax": int(ys.max()), "pixel_count": pixel_count},
        }
        if actor is not None:
            projected = _project_actor_bbox(
                actor, camera_info["actor"], camera_info["image_width"],
                camera_info["image_height"], camera_info["fov"],
            )
            item.update({
                "type_id": actor.type_id,
                "actor_pose": _serialize_transform(actor.get_transform()),
                "speed_mps": round(actor_speed(actor), 3),
                "distance_to_camera_m": round(
                    actor.get_transform().location.distance(camera_info["actor"].get_transform().location), 3
                ),
                "bbox_3d_projected": projected,
            })
            if hasattr(actor, "semantic_tags"):
                item["semantic_tags"] = [int(tag) for tag in actor.semantic_tags]
        visible_actors.append(item)
    return {
        "visible_actor_count": len(visible_actors),
        "visible_actors": visible_actors,
        "semantic_histogram": semantic_histogram,
    }
