"""Public dataset delivery operation for captured scene evidence."""

def produce_scene_dataset(directory, split='dev', intent=None, *, stop=None, context=None):
    from .server.dataset_authoring.scene_capture.products import produce
    return produce(directory, split, intent, stop=stop, context=context)


def current_plan(*args, **kwargs):
    from .server.assessment_planning.plan_versions import current
    return current(*args, **kwargs)


def review_stage(*args, **kwargs):
    from .server.pipelines.stage_review import review
    return review(*args, **kwargs)
