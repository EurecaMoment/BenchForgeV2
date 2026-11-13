"""Capture artifact packaging, separate from candidate and item selection."""
import json
from pathlib import Path
import zipfile

from .run_context import check_cancelled


def capture_file(capture, relative):
    path = capture / relative
    if (
        not relative
        or Path(relative).is_absolute()
        or not path.resolve().is_relative_to(capture.resolve())
    ):
        raise ValueError('Invalid capture evidence reference: ' + str(relative))
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('Missing capture evidence: ' + str(relative))
    return path


def package_capture(directory, release, evidence, *, stop=None):
    """Package recorded scene/action files and expose installed dependencies."""
    capture = directory / 'capture'
    result = {}
    interaction = evidence.get('interaction', {})
    actions = interaction.get('action_results', [])
    if actions:
        files = {}
        for action in actions:
            for key in ('trajectory_file', 'before_image', 'after_image'):
                if action.get(key):
                    files[action[key]] = capture_file(capture, action[key])
            recording = action.get('recording', {})
            spatialtree = recording.get('spatialtree', {}) if isinstance(recording, dict) else {}
            bundle = spatialtree.get('bundle') if isinstance(spatialtree, dict) else None
            if bundle:
                files[bundle] = capture_file(capture, bundle)
            if action.get('success') is True and not all(
                action.get(key) for key in ('trajectory_file', 'before_image', 'after_image')
            ):
                if action.get('action') != 'record_trajectory':
                    raise ValueError(
                        'Successful interaction lacks trajectory or before/after image evidence'
                    )
        with zipfile.ZipFile(
            release / 'interaction_bundle.zip', 'w', zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                'interaction.json', json.dumps(interaction, ensure_ascii=False, indent=2)
            )
            for relative, path in files.items():
                check_cancelled(stop, 'capture packaging')
                archive.write(path, relative)
        result.update(
            interaction_bundle='interaction_bundle.zip',
            interaction_validated=interaction.get('validated') is True,
        )

    if not (capture / 'scene.usda').is_file():
        return result

    files = {
        name: capture_file(capture, name)
        for name in ('scene.usda', 'evidence.json', 'report.json')
    }
    report = json.loads(files['report.json'].read_text())
    if report.get('scene_format') == 'usdc':
        files['scene.usdc'] = capture_file(capture, 'scene.usdc')
    for resource in report.get('scene_resources', []):
        relative = resource['file']
        files[relative] = capture_file(capture, relative)
    files['program.json'] = capture_file(directory, 'program.json')
    if (directory / 'scene_review.json').is_file():
        files['scene_review.json'] = directory / 'scene_review.json'
    if (directory / 'layout_reference.json').is_file():
        files['layout_reference.json'] = capture_file(directory, 'layout_reference.json')
        files['layout_reference.png'] = capture_file(directory, 'layout_reference.png')
    for frame in evidence['frames']:
        relative = frame['image']
        files[relative] = capture_file(capture, relative)
        stem = Path(relative).with_suffix('')
        for suffix in ('.json', '_depth.npy', '_semantic.npy', '_instance.npy'):
            relative = stem.as_posix() + suffix
            files[relative] = capture_file(capture, relative)

    dependencies = {
        'asset_dependencies': evidence.get('asset_dependencies', []),
        'material_dependencies': evidence.get('material_dependencies', []),
        'environment_dependencies': evidence.get('environment_dependencies', []),
        'space_dependencies': evidence.get('space_dependencies', []),
        'scene_resources': report.get('scene_resources', []),
        'scene_resources_unresolved': report.get('scene_resources_unresolved', []),
        'scene_resource_scope': report.get('scene_resource_scope'),
        'self_contained': False,
        'dependency_resolution_verified': False,
        'limitations': [
            'Native USD references and material modules can require the original Isaac asset installation paths.',
            'This package preserves captured files; it does not copy the installed asset library or rewrite USD references.',
        ],
    }
    with zipfile.ZipFile(release / 'scene_bundle.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for relative, path in files.items():
            check_cancelled(stop, 'capture packaging')
            archive.write(path, relative)
        archive.writestr('dependencies.json', json.dumps(dependencies, ensure_ascii=False, indent=2))
        archive.writestr(
            'README.txt',
            'Open scene.usda in Isaac Sim with the original native asset and material installation available.\n'
            'Images listed in scene_resources were copied beside the scene and use relative paths in the exported root layer.\n'
            'Consult dependencies.json for recorded dependencies. This is not a self-contained portable USD package.\n'
            'program.json is the scene request; evidence/report/views are captured results. Interaction traces are in the separate interaction bundle.\n',
        )
    result.update(scene_bundle='scene_bundle.zip', scene_self_contained=False)
    return result
