"""One model-facing assessment template and deterministic design checks."""
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path


class AssessmentValidationError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('Plan needs corrections:\n' + '\n'.join('- ' + issue for issue in issues)
                         + '\nEdit these fields in the saved source file; do not rewrite the complete assessment.')


def assessment_template():
    from .question_writing import contract
    value = json.loads(Path(__file__).with_name('assessment_template.json').read_text(encoding='utf-8'))
    value['question_authoring'] = contract()
    value['instructions'] += ' 题面写作约束：' + value['question_authoring']['instructions']
    value['scene_authoring'] = {
        'default': '真实可辨识资产；简化几何用于计划明确声明的空间实验。',
        'optional_field': 'assessment.scenes.geometry_exceptions (省略或空数组均可)',
        'declaration': {'scene_design_id': '对应 scenes.designs[].id', 'scene_id': '对应 SceneProgram.scene_id',
                        'object_ids': ['精确对应简化物体的 id'], 'purpose': '具体测量目的',
                        'reason': '该测量为何需要简化', 'simplifications': '简化内容及使用范围',
                        'retained_constraints': '保留的物理规律及实验布局约束',
                        'excluded_claims': '不声称的实景、生活真实性等能力'},
        'program_reference': {'kind': 'scene_plan', 'path': '保存计划的绝对路径',
                              'scene_design_id': '对应的设计 id'},
        'instructions': '每项说明填写具体内容，简洁完整即可，不按字数判定质量。SceneProgram.provenance.sources 引用保存的计划；口头声明或只在程序中写用途不构成例外。前端优先展示目的、简化范围和约束，标识放在技术详情。'}
    value['scene_authoring']['scene_brief'] = {
        'location': 'assessment.scenes.designs[]', 'name': '清晰的场景标题',
        'summary': '先写200到400字的详细段落，说明用途、空间、物体、朝向、支撑、光照、动线和取用关系。',
        'hard_requirements': ['用户原始硬要求，自动修复不得降低或删去'],
        'object_roles': [{'object_id': '实际物体 id', 'role': '物体在场景中的作用与位置'}],
        'relations': [{'source': '实际物体 id', 'type': 'supported_by|mounted_to|clearance|near|facing|inside',
                       'target': '实际物体 id 或 ground', 'description': '具体空间关系与使用理由'}],
        'physical_assumptions': ['明确质量、摩擦、支撑、固定安装的先验与验证限制'],
        'previous_capture_directory': '修订已有场景时填写上一版实际采集目录；继承该目录冻结的全部硬要求',
        'revision_history': [{'revision': 1, 'changes': ['根据实拍或回执发现的问题修改具体设计'], 'evidence_directory': '实际依据目录',
                              'unresolved': [],
                              'evidence_refs': [{'path': 'capture/view_0.png', 'observation': '实际视图中可见的空间或使用问题'},
                                                {'path': 'capture/evidence.json', 'observation': '原生支撑、姿态或物理回执中的具体发现'}]}],
        'iteration': '按摘要生产并比对实拍；发现遗漏可基于实拍修订软设计与摘要。每次保存新版本、依据、改动和待解问题；硬要求受保护。修订摘要不能代替修正程序、重新采集和验收。'}
    value['scene_authoring']['realism_review'] = {
        'purpose_and_identity': '先说明谁在何处做什么；主要物件具有可辨识结构，容器有真实开口，家具保持原资产比例，避免按名字推断身份。',
        'functional_relations': '检查椅子前侧与工作面、腿部空间、门和抽屉开启范围、取物高度、工具操作范围、连续通路与门窗净空；同一物件不得承担相互矛盾的用途。',
        'physical_relations': '明确支撑链、实际接触面、固定安装连接；空心家具按真实层板和箱底检查，叶片、把手和桌腿保留余量。不能只靠整体包围盒或声明支撑。',
        'actions': '检查动作前沉降、实际施力轨迹和动作后画面；推动后的滑移、倾倒、掉落及最终支撑须符合原实验目的。修复不得悄悄移除交互或放宽用户硬指标。',
        'evidence_and_iteration': '采用全景布局与关键接触近景，逐图、逐关系核对；看不清则补机位。硬要求保持，软设计按证据修订，保留旧版、差异、依据与未解问题。',
        'limits': '原生碰撞与沉降只证明本次参数和动作范围；静态布局不证明动力学，合成质量摩擦不等于实测。无法验证的要求明确失败并停在场景阶段。'}
    value['instructions'] += (' 场景质量约束：默认使用真实可辨识资产。模型在保存的场景生产计划中明确声明测量目的、简化原因、物体范围、保留约束和不声称的能力时，允许简化几何实验；按 scene_authoring 合同填写可选声明并绑定程序。'
                              '先审查完整SceneProgram再采集，实际看图并检查物理、支撑及符合实验设定的生活合理性后出题。已删除场景及派生产物不得复用；资产不足不能成为未经计划声明的自动降级理由。')
    return value


def validate_assessment(value, selections, inputs):
    if not isinstance(value, dict) or value.get('schema') != 'spatialforge.assessment/v1':
        raise ValueError('assessment.schema must be spatialforge.assessment/v1')
    outline = assessment_template()['assessment']
    issues = []

    def check(actual, expected, path):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                issues.append(f'{path} must be an object')
                return
            for key, child in expected.items():
                if key not in actual:
                    issues.append(f'Missing {path}.{key}; fill the assessment template')
                else:
                    check(actual[key], child, f'{path}.{key}')
        elif isinstance(expected, list):
            if not isinstance(actual, list) or (expected and not actual):
                issues.append(f'{path} must be a filled array')
                return
            for index, child in enumerate(actual):
                if expected:
                    check(child, expected[0], f'{path}[{index}]')
        elif expected == '':
            if not isinstance(actual, str) or not actual.strip() or actual.strip().lower() in ('todo', 'tbd', '待填写'):
                issues.append(f'{path} needs concrete text')

    # An empty selection_path is valid when no scene catalog is attached.
    outline['scenes'].pop('selection_path')
    check(value, outline, 'assessment')
    if issues:
        raise AssessmentValidationError(issues)
    expected_counts = Counter()
    for row in selections:
        ids, count = row['template_ids'], row['count']
        if not ids or type(count) is not int or count < len(ids):
            issues.append('Each selection count must cover its templates at least once')
            continue
        for index, tid in enumerate(ids):
            expected_counts[tid] += count // len(ids) + (index < count % len(ids))
    coverage = Counter()
    objectives = {row['id'] for row in value['objectives']}
    for row in value['coverage']:
        if row['objective_id'] not in objectives:
            issues.append('coverage.objective_id must reference a declared objective')
        if type(row['count']) is not int or row['count'] <= 0:
            issues.append('coverage.count must be a positive integer')
            continue
        coverage[row['template_id']] += row['count']
    if coverage != expected_counts:
        issues.append('assessment.coverage counts must match pipeline selections per template')
    target = value['dataset']['target_items']
    if type(target) is not int or target != sum(coverage.values()):
        issues.append('assessment.dataset.target_items must equal the allocated item count')
    if 'target_items' in inputs and inputs['target_items'] != target:
        issues.append('assessment target_items conflicts with pipeline inputs')
    if 'seed' in inputs and inputs['seed'] != value['dataset']['seed']:
        issues.append('assessment dataset.seed conflicts with pipeline inputs')
    scenes = value['scenes']
    from .scene_policy import scene_design_parser
    try:
        scene_design_parser().validate_geometry_declarations(scenes)
    except ValueError as error:
        issues.append('assessment.scenes: ' + str(error))
    for index, design in enumerate(scenes.get('designs', [])):
        if 'summary' in design:
            try:
                scene_design_parser().validate_scene_brief(design)
            except ValueError as error:
                issues.append(f'assessment.scenes.designs[{index}]: {error}')
    if type(scenes['allow_new_scenes']) is not bool:
        issues.append('scenes.allow_new_scenes must be a boolean')
    if not scenes['allow_new_scenes'] and not scenes['selected_scenes']:
        issues.append('A reuse-only assessment must reference selected scenes')
    if scenes['target_scene_count'] is not None and (type(scenes['target_scene_count']) is not int or scenes['target_scene_count'] <= 0):
        issues.append('scenes.target_scene_count must be a positive integer or null')
    if type(value['dataset']['seed']) is not int:
        issues.append('dataset.seed must be an integer')
    selection = inputs.get('scene_selection')
    if selection:
        allowed = selection.get('selected_scenes', selection.get('sources', []))
        allowed_ids = {(row.get('task_id', row.get('id')), row.get('revision')) for row in allowed}
        chosen_ids = {(row.get('task_id', row.get('id')), row.get('revision')) for row in scenes['selected_scenes']}
        if scenes['allow_new_scenes'] != selection.get('allow_new_scenes') or not chosen_ids <= allowed_ids:
            issues.append('assessment.scenes must honor the saved scene selection and revisions')
        if scenes.get('selection_path') != selection.get('selection_path'):
            issues.append('assessment.scenes.selection_path must match the saved selection')
    if {row['template_id'] for row in value['scoring']['metrics']} != set(coverage):
        issues.append('scoring.metrics must cover exactly the selected templates')
    stages = {'S1', 'S2', 'S3', 'S4', 'S5'}
    if {row['stage'] for row in value['execution']} != stages:
        issues.append('assessment.execution must cover S1 through S5')
    if {row['stage'] for row in value['delivery']['artifacts']} != stages:
        issues.append('assessment.delivery must declare viewable artifacts for all five stages')
    if issues:
        raise AssessmentValidationError(issues)
    return deepcopy(value)
