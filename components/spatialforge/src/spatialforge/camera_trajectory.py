"""Deterministic camera poses at sampled simulation steps; no physics interpolation."""


def sampled_camera(base, keyframes, elapsed_steps):
    if not keyframes:
        return dict(base)
    if elapsed_steps >= keyframes[-1]['step']:
        return {**base, **{key: keyframes[-1][key] for key in ('position', 'target')}}
    for left, right in zip(keyframes, keyframes[1:]):
        if left['step'] <= elapsed_steps <= right['step']:
            alpha = (elapsed_steps-left['step'])/(right['step']-left['step'])
            return {**base, **{key: [a+(b-a)*alpha for a,b in zip(left[key],right[key])]
                              for key in ('position','target')}}
    return {**base, **{key: keyframes[0][key] for key in ('position', 'target')}}
