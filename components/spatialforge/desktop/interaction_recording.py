"""Record sampled simulation images without inventing intermediate motion."""
import json
from pathlib import Path
import zipfile


class InteractionRecording:
    def __init__(self, output, index, settings, dt, capture):
        self.output = Path(output)
        self.stem = f'interaction_{index}'
        self.every_steps = settings.get('every_steps', max(1, round(1 / (30 * dt))))
        self.dt = dt
        self.capture = capture
        self.frames = []
        (self.output / (self.stem + '_frames')).mkdir(exist_ok=True)

    def sample(self, step, phase, state):
        if self.frames and (step - self.frames[0]['step']) % self.every_steps:
            return
        name = f'{self.stem}_frames/{len(self.frames):06d}.png'
        self.capture(name)
        self.frames.append({'image': name, 'step': step, 'timestamp_sim': step * self.dt,
                            'phase': phase, **state})

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
        (self.output / timeline).write_text(json.dumps(record, indent=2), encoding='utf8')
        return {key: value for key, value in record.items() if key != 'frames'}
