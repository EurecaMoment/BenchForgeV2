"""Author emitter dimensions explicitly, without changing task intensity."""


def apply_light_geometry(light, spec):
    kind = spec['kind']
    receipt = {'id': spec['id'], 'source_kind': spec.get('source_kind', kind),
               'usd_type': light.GetPrim().GetTypeName(),
               'intensity': light.GetIntensityAttr().Get(),
               'authority': 'authored USD light inputs; not calibrated illumination'}
    size = spec.get('size')
    if kind == 'distant':
        light.CreateAngleAttr(float(spec.get('angle',.53)))
        receipt.update(angle_degrees=light.GetAngleAttr().Get(),
                       extent_source='explicit angular diameter' if 'angle' in spec else 'default solar angular diameter')
    elif kind == 'sphere':
        # An unauthored SphereLight has radius 0.5 m: a one-meter emitter.
        light.CreateRadiusAttr(float(size[0])/2 if size else 0.0)
        light.CreateTreatAsPointAttr(not bool(size))
        receipt.update(radius_m=light.GetRadiusAttr().Get(),
                       treat_as_point=light.GetTreatAsPointAttr().Get(),
                       extent_source='size[0] diameter' if size else 'unsized point/spot; zero radius')
    elif kind == 'rect':
        if size:
            light.CreateWidthAttr(float(size[0]))
            light.CreateHeightAttr(float(size[1]))
        receipt.update(width_m=light.GetWidthAttr().Get(), height_m=light.GetHeightAttr().Get(),
                       extent_source='explicit size' if size else 'USD schema default')
    elif kind == 'disk':
        if size:
            light.CreateRadiusAttr(float(size[0])/2)
        receipt.update(radius_m=light.GetRadiusAttr().Get(),
                       extent_source='size[0] diameter' if size else 'USD schema default')
    return receipt
