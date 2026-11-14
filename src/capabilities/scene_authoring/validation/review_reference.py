"""Explicit native spatial context; rendered-view acceptance remains independent."""
from capabilities.scene_authoring.contracts.scene_design import validate_reference
from capabilities.scene_authoring.contracts.scene_design import _review_reference_vector as _vector
from capabilities.scene_authoring.contracts.scene_design import _review_reference_dot as _dot
from capabilities.scene_authoring.contracts.scene_design import _review_reference_unit as _unit

GUIDANCE = '''空间审查先固定参照，再看全部实际图片：世界方向、相机画面方向、使用者朝向和桌面前沿是不同定义。桌面“前沿/前区”通常指靠使用者的一侧；“在使用者前方”指其面朝方向，必须按保存的 front 定义区分。不得把画面上方当北/后、下方当前，或相机换位后改写同一关系。下面的局部坐标投影来自本次原生最终中心，只证明方向和位置关系，不能单独证明物体身份、可操作性、接触或生活合格；这些仍须逐图核实。方向定义缺失或坐标与视觉解释冲突时先明确引用哪个参照和哪张实际图，建议澄清摘要或改善观察，不能从低可信画面感觉直接给出移位修复。
支撑按整个采集集合判断：一张图遮挡不等于全体图无法确认。主图或任何单张无需同时呈现全部场景要求，除非原始需求明确指定该机位必须包含该对象。窗户和采光来源在其对应实际机位查证；相机朝向另一侧而窗户处于画外，不能据此断言窗缺失或要求移动窗户。采光效果仍按实际图中的光照判断，光源身份须由对应视图支持。对同一物体检查其他已附机位；原生支撑回执通过且另一实际图清楚显示底座落在台面时，单视角的不可见只作观察限制，不得同时报告支撑缺失。所有机位均无法确认必要接触、或实图明确悬空/穿插时仍须失败，真实图与原生回执冲突须保留冲突并调查。不能以 declared support 或 stable=true 独自宣称图片合格。issues、life_review、brief_alignment 对同一事实须一致，并给出具体图片名和观察；已在某图确认的接触不能又在全局称完全未验证。
修复建议先说明具体缺陷、支持它的全部实际图、参照及原生事实。可信度低或证据冲突时建议澄清参照/补观察，不建议移动已获支持的物体；能看清但真实不合生活用途的缺陷照常保留。确需调整位置时说明预期改善及需保护的支撑余量、碰撞、通行、操作空间和原始硬要求；执行前仍由原生预检验证，之后重新实拍验收。不得为迎合一条视觉意见反向制造悬空、过悬、穿插或姿态错误。'''


def review_spatial_context(brief, evidence, native_checks=()):
    """Resolve declared frames from final native centers; no authored-pose fallback."""
    context = {'schema': 'benchforge.review-spatial-context/v1',
               'authority': 'native coordinate/support context only; actual images still determine visual/life acceptance',
               'resolved_frames': [], 'directional_facts': [], 'unresolved_reference': [],
               'native_support_checks': [{k: row[k] for k in ('index','type','source','target','passed','evidence','basis') if k in row}
                                        for row in native_checks if isinstance(row, dict)]}
    entities = evidence.get('entities', {})
    try:
        reference = validate_reference(brief, set(entities))
    except ValueError as error:
        context['unresolved_reference'].append(str(error))
        return context
    context['reference_declaration'] = reference
    if not isinstance(reference, dict):
        context['reference_scope'] = 'text-only reference; do not infer numerical axes from camera framing'
        return context
    up = _unit(_vector(reference['world_up'], 'world_up'), 'world_up')
    def center(oid):
        entity = entities.get(oid, {})
        for key in ('current_center', 'final_center', 'settled_center'):
            if entity.get(key) is not None:
                # Native entity world transforms are recorded in world meters.
                if 'meter' not in str(entity.get('world_transform_convention', '')):
                    raise ValueError(oid + ': native center units are not recorded as world meters')
                return _vector(entity[key], oid + '.' + key)
        raise ValueError(oid + ': final captured center unavailable')
    resolved = {}
    for frame in reference['frames']:
        try:
            origin = center(frame['origin_object_id'])
            if frame['kind'] == 'user':
                observer, target = center(frame['observer_object_id']), center(frame['facing_target_object_id'])
                look = tuple(b-a for a,b in zip(observer,target))
                forward = _unit(tuple(v-_dot(look,up)*u for v,u in zip(look,up)), 'captured user forward')
                right = _unit((forward[1]*up[2]-forward[2]*up[1], forward[2]*up[0]-forward[0]*up[2],
                               forward[0]*up[1]-forward[1]*up[0]), 'captured observer right')
                front = forward if frame['front'] == 'observer_forward' else tuple(-v for v in forward)
            else:
                front = _unit(_vector(frame['front_world'], 'front_world'), 'front_world')
                right = _unit(_vector(frame['right_world'], 'right_world'), 'right_world')
            row = {'id':frame['id'], 'kind':frame['kind'], 'origin_object_id':frame['origin_object_id'],
                   'origin_m':list(origin),'front_world':list(front),'right_world':list(right),'up_world':list(up),
                   'front_definition':frame.get('front','explicit_world_axis'),
                   'basis':'declared semantics and final captured centers; actual facing still needs image verification'}
            resolved[frame['id']] = row
            context['resolved_frames'].append(row)
        except ValueError as error:
            context['unresolved_reference'].append(str(error))
    for index, relation in enumerate(brief.get('relations', [])):
        frame = resolved.get(relation.get('reference_frame'))
        if frame is None:
            continue
        try:
            source = center(relation['source'])
            delta = tuple(a-b for a,b in zip(source,frame['origin_m']))
            projections = {key:_dot(delta,frame[key+'_world']) for key in ('right','front','up')}
            directions = relation.get('expected_direction', [])
            signed = {'right':projections['right'], 'left':-projections['right'],
                      'front':projections['front'], 'back':-projections['front'],
                      'above':projections['up'], 'below':-projections['up']}
            context['directional_facts'].append({'index':index,'source':relation['source'],'target':relation['target'],
                'reference_frame':frame['id'],'world_delta_m':list(delta),'projections_m':projections,
                'expected_direction':directions,'declared_direction_signs':{name:signed[name] for name in directions},
                'basis':'captured center projection; no visible-contact or life pass assertion'})
        except ValueError as error:
            context['unresolved_reference'].append(str(error))
    return context
