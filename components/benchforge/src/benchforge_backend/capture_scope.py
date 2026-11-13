"""Optional output selection; scene construction and physics remain unchanged."""


def capture_scope(program, options=None):
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options) - {'view_indices', 'export_scene'}:
        raise ValueError('capture_options accepts view_indices and export_scene')
    count = len(program['cameras'])
    views = options.get('view_indices', list(range(count)))
    if not isinstance(views, list) or any(type(i) is not int or not 0 <= i < count for i in views) or len(set(views)) != len(views):
        raise ValueError('view_indices must contain distinct zero-based camera indices')
    export = options.get('export_scene', True)
    if type(export) is not bool:
        raise ValueError('export_scene must be a boolean')
    return {'view_indices': views, 'program_camera_count': count,
            'scene_export_requested': export,
            'full_scene_capture': len(views) == count and export}
