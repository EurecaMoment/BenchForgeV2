"""Concrete producers. Unsupported protocols use explicit source-evidence binding."""
import math
import random
from collections import defaultdict
from pathlib import Path

BUILTINS = {f'{task}-T{i:02}' for task in ('C01', 'C04', 'C44', 'P001', 'P002') for i in range(1, 4)} | {'C43-T01', 'C43-T03'}
PALETTE = [(56, 117, 167), (191, 76, 74), (68, 147, 101), (164, 106, 190), (213, 152, 56), (60, 146, 154)]


def supports(template_id):
    return {'program_generator': template_id in BUILTINS,
            'evidence_binding': True,
            'scope': 'calibrated synthetic geometry / explicit rules' if template_id in BUILTINS else 'requires task-specific source evidence and oracle; no generic substitute',
            'validation': 'adapter tests and generated artifacts; not real-world validity or training transfer'}


def canvas(path, width=640, height=360):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (width, height), (245, 246, 248))
    return image, ImageDraw.Draw(image)


def calibrated_views(scene, directory):
    """Three explicitly calibrated orthographic views, all objects fully visible."""
    images = []
    for axes in ((0, 1), (0, 2), (1, 2)):
        path = Path(directory) / f'view_{len(images)}.png'
        image, draw = canvas(path, 640, 640)
        for value in range(11):
            pixel = 50 + value * 54
            draw.line((pixel, 50, pixel, 590), fill=(215, 220, 227))
            draw.line((50, pixel, 590, pixel), fill=(215, 220, 227))
            draw.text((pixel-3, 594), str(value), fill=(25, 40, 55))
            draw.text((22, 586-value*54), str(value), fill=(25, 40, 55))
        draw.text((50, 18), f'Orthographic {"xyz"[axes[0]]}-{ "xyz"[axes[1]]}; 1 grid = 1 m', fill=(25, 40, 55))
        for index, obj in enumerate(scene['objects']):
            x, y = 50+obj['center'][axes[0]]*54, 590-obj['center'][axes[1]]*54
            radius = obj['radius']*54
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=PALETTE[index % len(PALETTE)], outline=(35, 45, 55), width=2)
            draw.text((x+radius+3, y-radius-12), obj['id'], fill=(15, 30, 45))
            draw.line((x-3, y, x+3, y), fill=(0, 0, 0))
            draw.line((x, y-3, x, y+3), fill=(0, 0, 0))
        image.save(path)
        images.append(path)
    return images


def sphere_world(rng, count):
    # Distinct x/y/z slots ensure identification and no overlapping projections.
    slots = list(range(1, 10))
    coordinates = [rng.sample(slots, count) for _ in range(3)]
    objects = [{'id': chr(65+i), 'center': [coordinates[a][i] + rng.uniform(-.12, .12) for a in range(3)],
                'radius': rng.uniform(.15, .30)} for i in range(count)]
    return {'objects': objects, 'unit': 'm', 'projection': 'three calibrated orthographic views',
            'grid_spacing_m': 1, 'shape': 'sphere', 'nonpenetrating': True}


def oracle(template_id, source):
    """Recompute independently from the private source world, not public answer text."""
    task, variant = template_id.split('-T')
    variant = int(variant)
    if task == 'C01':
        a, b = source['objects'][:2]
        value = math.dist(a['center'], b['center'])
        if variant == 2:
            value = max(0, value-a['radius']-b['radius'])
        if variant == 3 and source['requested_unit'] == 'cm':
            value *= 100
        return {'value': value, 'unit': source.get('requested_unit', 'm')}
    if task == 'C04':
        anchor, *objects = source['objects']
        distances = sorted((math.dist(anchor['center'], o['center']), o['id']) for o in objects)
        if variant == 1:
            return {'choice_id': distances[0][1]}
        if variant == 2:
            return {'sequence': [identifier for _, identifier in distances]}
        bins = defaultdict(list)
        for distance, identifier in distances:
            bins[math.floor(distance / source['epsilon'])].append(identifier)
        return {'groups': [sorted(bins[k]) for k in sorted(bins)]}
    if task == 'C43':
        return {'value': source['distance']/source['speed'], 'unit': 's'} if variant == 1 else {'value': sum(s['speed']*s['duration'] for s in source['segments']), 'unit': 'm'}
    if task == 'C44':
        speed, gravity, height = source.get('v0', 0), source['gravity'], source['height']
        return {'value': (math.sqrt(speed*speed+2*gravity*height)-speed)/gravity, 'unit': 's'}
    if task == 'P001':
        def area(points):
            return abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(points, points[1:]+points[:1])))/2
        areas = {key: area(value['boundary']) - sum(area(hole) for hole in value.get('holes', [])) for key, value in source['regions'].items()}
        if abs(areas['A']-areas['B']) < 1:
            raise ValueError('Area comparison is inside the excluded equality band')
        return {'label': max(areas, key=areas.get)}
    if task == 'P002':
        boxes = source['visible_boxes']
        if variant == 2:
            return {'detections': [{'box': b, 'class': 'disk', 'confidence': 1.0} for b in boxes]}
        return {'box': boxes[0]}
    raise ValueError(f'No built-in oracle for {template_id}; use source evidence')


def generate(template_id, seed, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    task, variant = template_id.split('-T')
    variant = int(variant)
    media, provided = [], []
    parameters = {}
    if task in ('C01', 'C04'):
        source = sphere_world(rng, 2 if task == 'C01' else rng.randint(4, 7))
        if task == 'C04':
            distances = sorted(math.dist(source['objects'][0]['center'], o['center']) for o in source['objects'][1:])
            if any(b-a < .10 for a, b in zip(distances, distances[1:])):
                return None
            source['epsilon'] = .8
            if variant == 3 and any(min(d % .8, .8-d % .8) < .06 for d in distances):
                return None
            parameters = {'anchor': 'A', 'objects': ', '.join(o['id'] for o in source['objects'][1:]), 'epsilon': .8}
        else:
            source['requested_unit'] = rng.choice(['m', 'cm']) if variant == 3 else 'm'
            parameters = {'A': 'A', 'B': 'B', 'P': 'B', 'unit': source['requested_unit']}
        media = calibrated_views(source, directory)
        parameters['media'] = '所附三张标定正交视图，黑十字表示球心，每格1米'
        provided = ['projection', 'grid_spacing_m', 'object_identity', 'sphere_shape', 'axis_labels']
    elif task == 'C43':
        if variant == 1:
            source = {'speed': round(rng.uniform(.2, 12), 2), 'distance': round(rng.uniform(.5, 120), 2)}
            parameters = source.copy()
        else:
            source = {'segments': [{'speed': round(rng.uniform(.2, 8), 2), 'duration': round(rng.uniform(.5, 15), 2), 'direction': rng.choice(['正向', '反向'])} for _ in range(rng.randint(2, 4))]}
            parameters['segments'] = '；'.join(f"速率{s['speed']}米/秒，持续{s['duration']}秒，{s['direction']}" for s in source['segments'])
        provided = ['speed', 'time_or_distance', 'straight_motion_rule']
    elif task == 'C44':
        source = {'height': round(rng.uniform(.2, 20), 2), 'gravity': rng.choice([1.62, 3.71, 9.8, 12.0])}
        if variant == 2:
            source['v0'] = round(rng.uniform(0, 5), 2)
        parameters = source.copy()
        provided = ['gravity', 'no_drag', 'downward_positive', 'horizontal_ground']
        if variant == 3:
            path = directory/'observation.png'
            image, draw = canvas(path, 300, 620)
            scale = 25
            for value in range(21):
                y = 570-value*scale
                draw.line((70, y, 240, y), fill=(200, 211, 221))
                draw.text((40, y-5), str(value), fill=(25, 40, 55))
            y = 570-source['height']*scale
            draw.ellipse((143, y-7, 157, y+7), fill=PALETTE[seed % len(PALETTE)])
            draw.text((75, 16), 'Height scale: metres; ground=0', fill=(25, 40, 55))
            image.save(path)
            media = [path]
            parameters = {'scene': '所附竖直标尺图，球心为释放点，地面标为0', 'gravity': source['gravity']}
            provided.append('calibrated_height_scale')
    elif task == 'P001':
        # Vary position, aspect, size and color; polygon area is independent of paint.
        aw, ah = rng.randint(65, 190), rng.randint(70, 230)
        bw, bh = rng.randint(65, 190), rng.randint(70, 230)
        ax, ay, bx, by = 80, 80, 360, 80
        a = [[ax, ay], [ax+aw, ay], [ax+aw, ay+ah], [ax, ay+ah]]
        if variant == 2:
            a = [[ax, ay], [ax+aw, ay], [ax+aw, ay+ah*.35], [ax+aw*.35, ay+ah*.35], [ax+aw*.35, ay+ah], [ax, ay+ah]]
        b = [[bx, by], [bx+bw, by], [bx+bw, by+bh], [bx, by+bh]]
        source = {'regions': {'A': {'boundary': a, 'holes': []}, 'B': {'boundary': b, 'holes': []}}, 'unit': 'pixel^2'}
        if variant == 3:
            source['regions']['A']['holes'] = [[[ax+aw*.2, ay+ah*.2], [ax+aw*.8, ay+ah*.2], [ax+aw*.8, ay+ah*.8], [ax+aw*.2, ay+ah*.8]]]
        try:
            oracle(template_id, source)
        except ValueError:
            return None
        path = directory/'observation.png'
        image, draw = canvas(path)
        colors = rng.sample(PALETTE, 2)
        for i, (key, region) in enumerate(source['regions'].items()):
            draw.polygon([tuple(p) for p in region['boundary']], fill=colors[i])
            for hole in region['holes']:
                draw.polygon([tuple(p) for p in hole], fill=(245, 246, 248))
            draw.text((region['boundary'][0][0], 50), key, fill=(25, 40, 55))
        draw.line((35, 330, 135, 330), fill=(20, 30, 40), width=2)
        draw.text((40, 335), '100 pixels', fill=(25, 40, 55))
        image.save(path)
        media = [path]
        parameters = {'image': '所附同平面正交图，标尺单位像素', 'A': 'A', 'B': 'B'}
        provided = ['region_identity', 'orthographic_plane', 'fill_and_hole_convention']
    elif task == 'P002':
        from PIL import Image
        path = directory/'observation.png'
        image, draw = canvas(path)
        count = rng.randint(0, 6) if variant == 2 else 1
        masks = []
        for i in range(count):
            x = 40+(i % 3)*200+rng.randint(0, 35)
            y = 50+(i // 3)*150+rng.randint(0, 20)
            radius = rng.randint(18, 38)
            shape = (x, y, x+2*radius, y+2*radius)
            draw.ellipse(shape, fill=PALETTE[(seed+i) % len(PALETTE)])
            mask = Image.new('L', image.size)
            from PIL import ImageDraw
            ImageDraw.Draw(mask).ellipse(shape, fill=255)
            if variant == 3:
                occluder = (x+radius, y, x+2*radius+10, y+2*radius+10)
                draw.rectangle(occluder, fill=(150, 157, 165))
                ImageDraw.Draw(mask).rectangle(occluder, fill=0)
            masks.append(mask)
        image.save(path)
        source = {'image_size': list(image.size), 'visible_boxes': [list(m.getbbox()) for m in masks], 'category': 'disk', 'coordinate_convention': 'pixel half-open xyxy', 'box_definition': 'visible'}
        media = [path]
        parameters = {'image': '所附640×360像素图，左上原点，半开xyxy边界', 'object': '唯一彩色圆盘', 'category': '彩色圆盘(disk)', 'box_definition': '可见'}
        provided = ['image_size', 'pixel_axes', 'half_open_box_convention', 'category_dictionary', 'visible_box_definition']
    else:
        raise ValueError(f'{template_id} needs source evidence, not a substituted legacy task')
    return {'parameters': parameters, 'media': media, 'source': source, 'provided_information': provided,
            'oracle': oracle(template_id, source), 'oracle_version': 'pipeline-program-v1', 'reference_frame': source.get('projection', source.get('coordinate_convention', 'explicit task rules'))}
