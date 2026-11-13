"""Persist one public viewpoint movie per completed scene revision, before playback."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
CACHE_ROOT = ROOT / '.deployment/scene-previews'
PREVIEW_FILE = 'preview/scene.mp4'
FORMAT_VERSION = 1


def preview_folder(task_id, revision):
    if not re.fullmatch(r'sf_[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+', task_id) or type(revision) is not int or revision < 0:
        raise ValueError('Invalid scene preview identity')
    return CACHE_ROOT / task_id / ('revision_' + str(revision))


def cached_preview(task_id, revision):
    folder = preview_folder(task_id, revision)
    try:
        saved = json.loads((folder / 'manifest.json').read_text())
        movie = folder / 'scene.mp4'
        if saved.get('version') != FORMAT_VERSION or saved.get('task_id') != task_id or saved.get('revision') != revision:
            return None
        if movie.is_symlink() or movie.stat().st_size != saved.get('bytes') or movie.stat().st_size < 32:
            return None
        return {**saved, 'source_path': str(movie), 'content_type': 'video/mp4'}
    except (OSError, ValueError):
        return None


def encoder_path():
    binary = shutil.which('ffmpeg')
    if binary:
        return binary
    runtime = ROOT / '.deployment/preview-runtime'
    if runtime.is_dir():
        sys.path.insert(0, str(runtime))
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as error:
        raise RuntimeError('Install the workbench preview runtime from requirements-preview.txt') from error


def persist_preview(task_id, revision, frames):
    """Only declared, validated public frame paths reach the encoder; no browser request encodes."""
    if not frames or len(frames) > 40:
        raise ValueError('A scene movie requires 1 to 40 public views')
    folder = preview_folder(task_id, revision)
    fingerprints = [[frame.name, frame.stat().st_size, frame.stat().st_mtime_ns] for frame in frames]
    saved = cached_preview(task_id, revision)
    if saved and saved.get('frames') == fingerprints:
        return {**saved, 'reused': True}
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / 'encoding.lock'
    try:
        with lock.open('x') as handle:
            handle.write(str(time.time()))
    except FileExistsError:
        if time.time() - lock.stat().st_mtime > 120:
            lock.unlink()
            return persist_preview(task_id, revision, frames)
        return {'task_id': task_id, 'revision': revision, 'state': 'running'}
    pending = folder / 'scene.pending.mp4'
    try:
        lines = []
        for frame in [*frames, frames[-1]]:
            filename = str(frame.resolve()).replace('\\', '/').replace("'", "'\\''")
            lines.extend(["file '" + filename + "'", 'duration 1.2'])
        inputs = folder / 'frames.txt'
        inputs.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        subprocess.run([encoder_path(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                        '-f', 'concat', '-safe', '0', '-i', str(inputs), '-t', str(len(frames) * 1.2),
                        '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p', '-r', '24', '-an',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-threads', '1',
                        '-movflags', '+faststart', str(pending)], check=True, capture_output=True, timeout=45)
        if pending.stat().st_size < 32:
            raise RuntimeError('The scene movie was not produced')
        saved = {'version': FORMAT_VERSION, 'task_id': task_id, 'revision': revision, 'frames': fingerprints,
                 'file': PREVIEW_FILE, 'frame_count': len(frames), 'bytes': pending.stat().st_size,
                 'created_at': time.time(), 'purpose': 'scene_tour'}
        pending.replace(folder / 'scene.mp4')
        manifest = folder / 'manifest.pending.json'
        manifest.write_text(json.dumps(saved), encoding='utf-8')
        manifest.replace(folder / 'manifest.json')
        return {**cached_preview(task_id, revision), 'reused': False}
    finally:
        pending.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def prepare_scene(config, session, scene, run_ids=()):
    from production_observer import service_read, stage_artifacts
    products = stage_artifacts(config, session, scene, run_ids=run_ids)
    if products.get('error'):
        return products
    observed = service_read(config, '/inspect', {'run_id': scene})
    movies = []
    for task in observed['tasks'][:8]:
        if task['state'] != 'SUCCEEDED':
            continue
        revision = task['unit']['revision']
        rows = sorted((row for row in products['items'] if row['task_id'] == task['id'] and row['revision'] == revision
                       and re.fullmatch(r'capture/view_\d+\.png', row['file'])),
                      key=lambda row: int(re.search(r'view_(\d+)', row['file']).group(1)))[:40]
        if not rows:
            continue
        source = service_read(config, '/evidence', {'task_id': task['id'], 'revision': revision, 'file': rows[0]['file']})
        if source['latest_revision'] != revision:
            continue
        capture = Path(source['source_path']).resolve().parent
        frames = [capture / Path(row['file']).name for row in rows]
        if any(frame.is_symlink() or not frame.is_file() or frame.resolve().parent != capture for frame in frames):
            raise ValueError('A scene preview frame is not a public capture file')
        movies.append(persist_preview(task['id'], revision, frames))
    return {'scene': scene, 'movies': movies}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--scene', required=True)
    parser.add_argument('--run-ids', default='[]')
    args = parser.parse_args()
    try:
        from production_observer import load_workbench_config
        result = prepare_scene(load_workbench_config(args.config), args.session, args.scene, json.loads(args.run_ids))
    except Exception as error:
        result = {'error': 'Scene movie export failed (' + type(error).__name__ + ')'}
    print(json.dumps(result))
