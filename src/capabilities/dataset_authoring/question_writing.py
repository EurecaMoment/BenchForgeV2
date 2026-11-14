"""Public question presentation and deterministic writing admission.

These checks enforce an authoring contract, not an automated human-validity verdict.
Source generators still own measurement semantics and public-information sufficiency.
"""
import re
from copy import deepcopy

SCHEMA = 'benchforge.question-writing/v1'
INSTRUCTIONS = (
    '新题面的 schema 使用 benchforge.question-writing/v1。'
    '每题提交 question_spec：简短自然题干 stem、公开已知条件 context、必要作答规则 conditions、'
    '候选 options、作答说明 response、逐项媒体标题 media_labels，以及与 parameters 完全一致的 parameter_bindings。'
    '题干先说看什么和问什么；采集说明、坐标定义、单位和容差分别放在条件中，必要条件不能藏在技术详情。'
    '对象称呼必须对应公开图片中的真实名称或编号；禁止凭空命名物体。'
    '禁止把内部运行号、路径、相机代码、原始字典或列表拼进题干。'
    '中心、采样点、参照轴等若用于作答，必须在公开媒体中提供对应标记或可用条件。'
    '保留准确模板的目标、参照系、单位、容差、候选和输出合同；改表达不能改变问题。'
    '无需模型判断题目质量。程序检查字段与绑定，并逐模板实际看图检查代表题。'
)


def contract():
    return {'schema': SCHEMA, 'instructions': INSTRUCTIONS,
            'evidence_field': 'question_spec',
            'required_fields': ['stem', 'context', 'conditions', 'options', 'response', 'media_labels', 'parameter_bindings'],
            'example': {'schema': SCHEMA, 'stem': '看图1，标记A的物体在标记B的哪一侧？',
                        'context': ['图中编号用于识别物体。'],
                        'conditions': ['以画面为参照，按图中中心标记判断方向。'],
                        'options': ['左侧', '右侧', '上方', '下方'],
                        'response': '按当前模板的输出合同提交一个方向。',
                        'media_labels': ['图1：场景与物体中心标记'],
                        'parameter_bindings': 'copy the exact evidence parameters object'},
            'validation_scope': 'writing structure and exact source bindings; human answerability requires real media review'}


def public_value(value):
    """Render structured public parameters without Python/JSON serialization."""
    if isinstance(value, dict):
        return '；'.join(f'{key}：{public_value(child)}' for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return '、'.join(public_value(child) for child in value)
    if isinstance(value, bool):
        return '是' if value else '否'
    return str(value)


def validate_spec(spec, parameters, media_count):
    if not isinstance(spec, dict):
        raise ValueError('Source evidence needs question_spec; read pipeline_catalog question_authoring')
    if 'schema' in spec and spec['schema'] != SCHEMA:
        raise ValueError('Unsupported question_spec.schema; use ' + SCHEMA)
    if spec.get('parameter_bindings') != parameters:
        raise ValueError('question_spec.parameter_bindings must preserve the exact source parameters')
    for key in ('stem', 'response'):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            raise ValueError(f'question_spec.{key} needs concrete text')
    for key in ('context', 'conditions', 'options', 'media_labels'):
        if not isinstance(spec.get(key), list) or not all(isinstance(value, str) and value.strip() for value in spec[key]):
            raise ValueError(f'question_spec.{key} must be a list of concrete public text')
    if not spec['conditions']:
        raise ValueError('question_spec.conditions must state the measurement rules')
    if len(spec['media_labels']) != media_count:
        raise ValueError('question_spec.media_labels must describe every public media item in order')
    if len(spec['stem']) > 140:
        raise ValueError('Question stem is too long; move given facts and measurement rules to their sections')
    main = '\n'.join([spec['stem'], *spec['context'], *spec['conditions']])
    if re.search(r'\{[A-Za-z_][\w]*\}', main):
        raise ValueError('Unbound question writing parameter')
    if re.search(r'(?:/home/|/var/|[A-Za-z]:[\\/]|cam_[A-Za-z0-9_]+|sf_[A-Za-z0-9_]+)', main):
        raise ValueError('Internal paths, run IDs and camera codes do not belong in public question text')
    if re.search(r'[\[{]\s*["\']', main):
        raise ValueError('Raw JSON does not belong in the question stem or conditions')
    if re.search(r'[？?][。.]|他者|oracle|ground.truth|质心投影横坐标', main, re.I):
        raise ValueError('Rewrite protocol jargon or malformed question punctuation in public wording')
    if len(set(spec['options'])) != len(spec['options']):
        raise ValueError('Question options must be distinct')
    # Older source writers emitted the complete v1 fields without the version
    # label. Normalize that metadata after validating every substantive field.
    return {'schema': SCHEMA, **{key: deepcopy(spec[key]) for key in
            ('stem', 'context', 'conditions', 'options', 'response', 'media_labels')}}


def builtin_spec(template, sample):
    """Built-in generators use already reviewed public parameters and marked media."""
    text = template['prompt_template'].format_map({key: public_value(value) for key, value in sample['parameters'].items()})
    parts = [part.strip() for part in re.split(r'(?<=[？?。；;])', text) if part.strip()]
    stem, *conditions = parts
    return {'schema': SCHEMA, 'stem': stem, 'context': [],
            'conditions': conditions or [public_value(sample['reference_frame'])], 'options': [],
            'response': '按该题型公开的输出格式作答。',
            'media_labels': [f'图{index + 1}：公开观测' for index in range(len(sample['media']))],
            'parameter_bindings': sample['parameters']}


def question_text(presentation):
    parts = [presentation['stem']]
    for key, title in [('context', '已知条件'), ('conditions', '作答规则'), ('options', '选项')]:
        if presentation[key]:
            parts.append(title + '：\n' + '\n'.join('- ' + value for value in presentation[key]))
    parts.append('作答方式：' + presentation['response'])
    return '\n\n'.join(parts)
