"""Deterministic measurement using published RGB-D/K/poses/masks/axes only.

This module does not read answer files, object GT centers, sizes, world poses,
native USD, annotation JSONL or the private point-world coordinate.
"""
from pathlib import Path
import json
import math
import re
import numpy as np
from PIL import Image
from public_sensor_cache import _BoundedCache, _file_version
from public_geometry_cache import PUBLIC_GEOMETRY_RESULTS, public_geometry_key, freeze_geometry


class PublicMeasurementError(ValueError):
    pass


_PUBLIC_IMAGES = _BoundedCache(512, 128*1024*1024)
_METRIC_FRAMES = _BoundedCache(32, 256*1024*1024)


def _public_image(path, version=None):
    """Only decode whitelisted public image files; never open native sources."""
    key = version or _file_version(path)
    def load():
        with Image.open(key[0]) as image:
            array = np.asarray(image).copy()
        array.setflags(write=False)
        return array
    return _PUBLIC_IMAGES.load(key, load)


def _public_metric_frame(depth_path, valid_path, unit_scale):
    depth_key, valid_key = _file_version(depth_path), _file_version(valid_path)
    key = depth_key, valid_key, float(unit_scale)
    def load():
        depth = np.asarray(_public_image(depth_path, depth_key), dtype=np.float64)*float(unit_scale)
        valid = _public_image(valid_path, valid_key) > 0
        depth.setflags(write=False)
        valid.setflags(write=False)
        return depth, valid
    return _METRIC_FRAMES.load(key, load)


def cache_status():
    return {'public_images': _PUBLIC_IMAGES.stats(), 'metric_frames': _METRIC_FRAMES.stats(),
            'public_geometry_results': PUBLIC_GEOMETRY_RESULTS.stats()}


def _tag(value):
    match = re.match(r"([ABC]\d{2})", str(value))
    if not match:
        raise PublicMeasurementError("Public object reference has no numbered label")
    return match.group(1)


def geometry_from_points(points, local_axes):
    points = np.asarray(points, dtype=np.float64)
    axes = np.asarray(local_axes, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0 or not np.isfinite(points).all():
        raise PublicMeasurementError("No finite published surface points")
    if axes.shape != (3,3) or not np.allclose(axes@axes.T, np.eye(3), atol=1e-4):
        raise PublicMeasurementError("Published local directions are not orthonormal")
    local = points@axes.T
    low, high = local.min(axis=0), local.max(axis=0)
    return {"center": ((low+high)*.5)@axes, "size": high-low,
            "basis": "published metric-depth surface extremes in declared local axes"}


def triangulate_public_marker(frames, observations):
    matrices, rhs = [], []
    used = set()
    for observation in observations:
        index = int(observation["frame_index"])
        if index in used or not 0 <= index < len(frames):
            continue
        used.add(index)
        frame = frames[index]
        k = np.asarray(frame["K"], dtype=np.float64)
        transform = np.asarray(frame["T_reference_camera_optical"], dtype=np.float64)
        u,v = map(float, observation["pixel_uv"])
        ray = transform[:3,:3]@np.linalg.solve(k,np.array([u,v,1.]))
        ray /= np.linalg.norm(ray)
        projector = np.eye(3)-np.outer(ray,ray)
        matrices.append(projector); rhs.append(projector@transform[:3,3])
    if len(used) < 2:
        raise PublicMeasurementError("A 3D marker needs at least two public calibrated observations")
    matrix = sum(matrices)
    if np.linalg.cond(matrix) > 1e8:
        raise PublicMeasurementError("Public marker views do not establish useful triangulation")
    return np.linalg.solve(matrix,sum(rhs))


class PublicReconstruction:
    def __init__(self, calibration_file):
        self.path = Path(calibration_file).resolve()
        self.base = self.path.parent
        self.card = json.loads(self.path.read_text(encoding="utf-8"))
        if not self.card.get("metric_input_ready"):
            raise PublicMeasurementError("Public metric sensor calibration is incomplete")
        self.frames = self.card["frames"]
        axes_file = self._asset(self.card.get("local_axes_asset"))
        axes = json.loads(axes_file.read_text(encoding="utf-8"))
        self.axes = {obj["object_label"]:obj["local_axes_in_reference_camera"] for obj in axes["objects"]}
        self.point_cache, self.geometry_cache, self.frame_cache = {}, {}, {}
        self.geometry_point_counts, self.asset_version_cache = {}, {}

    def _asset(self, value):
        if not value:
            raise PublicMeasurementError("A required public asset is missing")
        path = Path(value)
        if not path.is_absolute(): path = self.base/path
        path = path.resolve()
        path.relative_to(self.base)
        return path

    def points(self, label):
        if label in self.point_cache: return self.point_cache[label]
        arrays = []
        for frame_index,frame in enumerate(self.frames):
            mask_path = frame.get("object_masks", {}).get(label)
            depth_meta = frame.get("depth")
            if not mask_path or not depth_meta: continue
            mask = _public_image(self._asset(mask_path)) > 0
            if frame_index not in self.frame_cache:
                depth, valid = _public_metric_frame(
                    self._asset(depth_meta['asset']), self._asset(depth_meta['valid_mask']),
                    depth_meta['unit_scale_to_m'])
                self.frame_cache[frame_index] = (depth,valid)
            depth, source_valid = self.frame_cache[frame_index]
            valid = source_valid.copy()
            if mask.shape != depth.shape or valid.shape != depth.shape:
                raise PublicMeasurementError("Public mask and depth dimensions differ")
            valid &= mask & np.isfinite(depth) & (depth > 0)
            y,x = np.nonzero(valid)
            if len(x) == 0: continue
            offset = frame.get("pixel_center_offset_px")
            if offset is None: raise PublicMeasurementError("Pixel-center sampling is not declared")
            uv = np.stack([x+float(offset[0]),y+float(offset[1]),np.ones(len(x))],axis=1)
            k = np.asarray(frame["K"],dtype=np.float64)
            transform = np.asarray(frame["T_reference_camera_optical"],dtype=np.float64)
            camera_points = (uv@np.linalg.inv(k).T)*depth[valid][:,None]
            arrays.append(camera_points@transform[:3,:3].T+transform[:3,3])
        if not arrays: raise PublicMeasurementError("No published metric pixels for object "+label)
        points = np.concatenate(arrays,axis=0)
        self.point_cache[label] = points
        return points

    def _public_asset_version(self, value):
        if value not in self.asset_version_cache:
            self.asset_version_cache[value] = _file_version(self._asset(value))
        return self.asset_version_cache[value]

    def geometry(self,label):
        if label not in self.geometry_cache:
            if label not in self.axes: raise PublicMeasurementError("No public local axes for "+label)
            key = public_geometry_key(self.card, self.frames, self.axes[label], label, self._public_asset_version)
            def reconstruct():
                points = self.points(label)
                return freeze_geometry(geometry_from_points(points,self.axes[label]),len(points))
            result = PUBLIC_GEOMETRY_RESULTS.load(key,reconstruct)
            self.geometry_cache[label] = result
            self.geometry_point_counts[label] = result.point_count
        result = self.geometry_cache[label]
        # Copies protect both this instance and later questions from caller mutation.
        return {"center": np.array(result.center,dtype=np.float64),
                "size": np.array(result.size,dtype=np.float64), "basis": result.basis}

    def point_count(self,label):
        if label in self.geometry_point_counts:
            return self.geometry_point_counts[label]
        return len(self.points(label))

    def predict(self,query):
        if any(name in query for name in ("answer","private","objects_gt","object_GT","point_world","settled_center_m","size_xyz_m")):
            raise PublicMeasurementError("Hidden truth is not a public query input")
        template = query["template_id"]
        center = lambda label:self.geometry(label)["center"]
        distance = lambda a,b:float(np.linalg.norm(center(a)-center(b)))
        if template == "C01-T01": return distance(query["A"],query["B"])
        if template == "C01-T02":
            from scipy.spatial import cKDTree
            a,b = self.points(query["A"]),self.points(query["B"])
            return float(np.min(cKDTree(b).query(a,k=1,workers=1)[0]))
        if template == "C01-T03":
            marker=triangulate_public_marker(self.frames,query["point_observations"])
            return float(np.linalg.norm(center(query["A"])-marker))
        if template == "C03-T01":
            camera=np.asarray(self.frames[int(query.get("camera_index",0))]["T_reference_camera_optical"],dtype=float)
            return float(np.linalg.norm(center(query["object"])-camera[:3,3]))
        if template in {"C04-T01","C04-T02"}:
            ranking=sorted(query["candidates"],key=lambda label:(distance(query["anchor"],label),label))
            return ranking[0] if template=="C04-T01" else ranking
        if template=="C05-T01":
            camera=np.asarray(self.frames[int(query.get("camera_index",0))]["T_reference_camera_optical"],dtype=float)
            depth=lambda label:float((camera[:3,:3].T@(center(label)-camera[:3,3]))[2])
            delta=depth(query["A"])-depth(query["B"])
            return "相同" if abs(delta)<=float(query["epsilon"]) else ("更小" if delta<0 else "更大")
        if template=="C07-T02": return float(self.geometry(query["object"])["size"].max()*100)
        if template=="C09-T01":
            a,b=query["A"],query["B"]
            return a if self.geometry(a)["size"].max()>self.geometry(b)["size"].max() else b
        if template=="C11-T01":
            return sum(distance(query["anchor"],label)<=float(query["radius"]) for label in query["universe"] if label!=query["anchor"])
        raise PublicMeasurementError("Unsupported frozen template "+template)


def public_query(template, parameters, calibration_file, marker_observations=()):
    """Construct a query from public parameter bindings; never accept oracle fields."""
    query={"template_id":template}
    if template in {"C01-T01","C01-T02","C09-T01","C05-T01"}:
        query.update(A=_tag(parameters["A"]),B=_tag(parameters["B"]))
    elif template=="C01-T03":
        if not marker_observations:
            card=json.loads(Path(calibration_file).read_text(encoding="utf-8"))
            marker_observations=card.get("marker_observations",[])
        query.update(A=_tag(parameters["A"]),point_observations=[
            observation for observation in marker_observations if observation.get("point_label")==parameters.get("P")])
    elif template in {"C03-T01","C07-T02"}: query["object"]=_tag(parameters["object"])
    elif template in {"C04-T01","C04-T02"}:
        query.update(anchor=_tag(parameters["anchor"]),candidates=re.findall(r"[ABC]\d{2}",parameters["objects"]))
    elif template=="C11-T01":
        card=json.loads(Path(calibration_file).read_text(encoding="utf-8"))
        labels=sorted({label for frame in card["frames"] for label in frame["object_masks"]})
        anchor = _tag(parameters["anchor"])
        universe = parameters.get("universe", card.get("counting_universe"))
        if universe is None:
            universe = labels
        else:
            if not isinstance(universe, list) or any(not isinstance(label, str) for label in universe):
                raise PublicMeasurementError("Explicit counting universe must be a list of object labels")
            universe = [_tag(label) for label in universe]
            if len(universe) != len(set(universe)) or anchor in universe or sorted(universe) != sorted(label for label in labels if label != anchor):
                raise PublicMeasurementError("Explicit counting universe differs from the published masks")
            if card.get("counting_universe") is not None and sorted(card["counting_universe"]) != sorted(universe):
                raise PublicMeasurementError("Card and question counting universes differ")
        query.update(anchor=anchor,radius=float(parameters["radius"]),universe=universe)
    if template=="C05-T01": query.update(epsilon=float(parameters["epsilon"]),camera_index=0)
    if template=="C03-T01": query["camera_index"]=0
    return query
