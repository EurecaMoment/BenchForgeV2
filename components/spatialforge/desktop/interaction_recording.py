"""Record sampled simulation images without inventing intermediate motion."""
import json
from pathlib import Path
import zipfile


class InteractionRecording:
    def __init__(self, output, index, settings, dt, capture, trajectory_frame=None, before_capture=None, width=None, height=None):
        self.output = Path(output)
        self.stem = f'interaction_{index}'
        self.every_steps = settings.get('every_steps', max(1, round(1 / (30 * dt))))
        self.dt = dt
        self.capture = capture
        self.trajectory_frame = trajectory_frame
        self.before_capture = before_capture
        self.spatialtree_action_id = None
        self.spatialtree = None
        spatialtree = settings.get('spatialtree')
        if spatialtree is not None:
            if not isinstance(spatialtree, dict):
                raise ValueError('recording.spatialtree must be an object')
            from spatialforge.trajectory import SpatialTreeTrajectoryRecorder
            if type(width) is not int or type(height) is not int:
                raise ValueError('native trajectory needs the actual capture width and height')
            self.spatialtree = SpatialTreeTrajectoryRecorder(
                self.output / (self.stem + '_spatialtree'),
                fps=1 / (self.every_steps * dt),
                width=width,
                height=height,
                scenario_id=spatialtree.get('scenario_id', self.stem),
                split=spatialtree.get('split', 'train'),
            )
        self.frames = []
        (self.output / (self.stem + '_frames')).mkdir(exist_ok=True)

    def sample(self, step, phase, state):
        if self.frames and (step - self.frames[0]['step']) % self.every_steps:
            return
        name = f'{self.stem}_frames/{len(self.frames):06d}.png'
        if self.before_capture is not None:
            self.before_capture(step)
        self.capture(name)
        self.frames.append({'image': name, 'step': step, 'timestamp_sim': step * self.dt,
                            'phase': phase, **state})
        if self.spatialtree is not None:
            if self.trajectory_frame is None:
                raise ValueError('recording.spatialtree requires a trajectory_frame callback')
            payload = self.trajectory_frame(step, phase, self.output / name)
            if not isinstance(payload, dict):
                raise ValueError('trajectory_frame must return an object')
            payload.setdefault('action_ids', [] if self.spatialtree_action_id is None else [self.spatialtree_action_id])
            self.spatialtree.add_frame(**payload)

    def finish(self, end_step):
        import cv2
        first = cv2.imread(str(self.output / self.frames[0]['image']))
        height, width = first.shape[:2]
        fps = 1 / (self.every_steps * self.dt)
        video = self.stem + '.mp4'
        writer = cv2.VideoWriter(str(self.output / video), cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError('Cannot encode interaction MP4; captured PNG frames remain available')
        try:
            for frame in self.frames:
                writer.write(cv2.imread(str(self.output / frame['image'])))
        finally:
            writer.release()
        archive = self.stem + '_frames.zip'
        with zipfile.ZipFile(self.output / archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
            for frame in self.frames:
                bundle.write(self.output / frame['image'], frame['image'])
        timeline = self.stem + '_recording.json'
        record = {'source': 'rendered_simulation_steps', 'video': video, 'timeline_file': timeline,
                  'frames_archive': archive,
                  'frame_count': len(self.frames), 'fps': fps, 'physics_dt': self.dt,
                  'every_steps': self.every_steps, 'start_step': self.frames[0]['step'],
                  'last_frame_step': self.frames[-1]['step'], 'action_end_step': end_step,
                  'width': width, 'height': height, 'interpolated_frames': 0,
                  'frames': self.frames}
        if self.spatialtree is not None:
            record['spatialtree'] = self.spatialtree.finalize(video_path=self.output / video)
            record['spatialtree']['bundle'] = self._bundle_spatialtree()
            summary = self.stem + '_spatialtree.json'
            record['spatialtree']['summary'] = summary
            (self.output / summary).write_text(json.dumps(record['spatialtree'], indent=2), encoding='utf8')
        (self.output / timeline).write_text(json.dumps(record, indent=2), encoding='utf8')
        return {key: value for key, value in record.items() if key != 'frames'}

    def _bundle_spatialtree(self):
        bundle = self.output / (self.stem + '_spatialtree.zip')
        with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.spatialtree.output.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(self.spatialtree.output).as_posix())
        return bundle.name
