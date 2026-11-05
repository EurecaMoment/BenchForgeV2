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
    if not isinstance(value, dict):
        raise AssessmentValidationError(['assessment must be an object'])
    outline = assessment_template()['assessment']
    issues = []
    invalid = set()

    def issue(path, message):
        invalid.add(path)
        text = f'{path} {message}'
        if text not in issues:
            issues.append(text)

    def ready(path):
        return not any(path == item or path.startswith(item + '.') or path.startswith(item + '[') or
                       item.startswith(path + '.') or item.startswith(path + '[') for item in invalid)

    def check(actual, expected, path):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                issue(path, 'must be an object')
                return
            for key, child in expected.items():
                if key not in actual:
                    field = f'{path}.{key}'
                    invalid.add(field)
                    text = f'Missing {field}; fill the assessment template'
                    if text not in issues:
                        issues.append(text)
                else:
                    check(actual[key], child, f'{path}.{key}')
        elif isinstance(expected, list):
            if not isinstance(actual, list) or (expected and not actual):
                issue(path, 'must be a filled array' if expected else 'must be an array')
                return
            for index, child in enumerate(actual):
                if expected:
                    check(child, expected[0], f'{path}[{index}]')
        elif isinstance(expected, str):
            if not isinstance(actual, str) or not actual.strip() or actual.strip().lower() in ('todo', 'tbd', '待填写'):
                issue(path, 'needs concrete text')

    # An empty selection_path is valid when no scene catalog is attached.
    outline['scenes'].pop('selection_path')
    check(value, outline, 'assessment')
    if value.get('schema') != 'spatialforge.assessment/v1':
        issue('assessment.schema', 'must be spatialforge.assessment/v1')

    # These fields become required only when an author supplies a scene brief.
    # Collect its whole structure before invoking the shared admission validator.
    scenes = value.get('scenes') if isinstance(value.get('scenes'), dict) else {}
    designs = scenes.get('designs') if isinstance(scenes.get('designs'), list) else []
    brief_outline = {
        'summary': '', 'hard_requirements': [''], 'physical_assumptions': [''],
        'object_roles': [{'object_id': '', 'role': ''}],
        'relations': [{'source': '', 'type': '', 'target': '', 'description': ''}],
    }
    relation_types = {'supported_by', 'mounted_to', 'clearance', 'near', 'facing', 'inside'}
    for index, design in enumerate(designs):
        if not isinstance(design, dict) or 'summary' not in design:
            continue
        path = f'assessment.scenes.designs[{index}]'
        check(design, brief_outline, path)
        for number, relation in enumerate(design.get('relations', []) if isinstance(design.get('relations'), list) else []):
            field = f'{path}.relations[{number}].type'
            if isinstance(relation, dict) and ready(field) and relation.get('type') not in relation_types:
                issue(field, 'must be one of ' + ', '.join(sorted(relation_types)))

    declarations = scenes.get('geometry_exceptions', [])
    if 'geometry_exceptions' in scenes:
        if not isinstance(declarations, list):
            issue('assessment.scenes.geometry_exceptions', 'must be an optional array')
        else:
            from .scene_policy import scene_design_parser
            declaration_parser = scene_design_parser()
            declaration_outline = {key: '' for key in declaration_parser.DETAIL_FIELDS}
            declaration_outline.update(scene_design_id='', scene_id='', object_ids=[''])
            for index, declaration in enumerate(declarations):
                path = f'assessment.scenes.geometry_exceptions[{index}]'
                check(declaration, declaration_outline, path)
                if isinstance(declaration, dict):
                    for key in declaration_parser.DETAIL_FIELDS:
                        if isinstance(declaration.get(key), str) and declaration[key].strip().casefold() in {'无', 'none', 'n/a'}:
                            issue(f'{path}.{key}', 'needs concrete text')

    expected_counts = Counter()
    selections_ready = True
    for index, row in enumerate(selections):
        ids, count = row.get('template_ids'), row.get('count')
        if not isinstance(ids, list) or not ids or any(not isinstance(tid, str) or not tid.strip() for tid in ids):
            issue(f'selections[{index}].template_ids', 'must list the selected templates')
            selections_ready = False
            continue
        if type(count) is not int or count < len(ids):
            issue(f'selections[{index}].count', 'must cover its templates at least once')
            selections_ready = False
            continue
        for index, tid in enumerate(ids):
            expected_counts[tid] += count // len(ids) + (index < count % len(ids))
    coverage = Counter()
    objective_rows = value.get('objectives') if isinstance(value.get('objectives'), list) else []
    objectives_ready = bool(objective_rows) and all(isinstance(row, dict) and ready(f'assessment.objectives[{index}].id')
        for index, row in enumerate(objective_rows))
    objectives = {row['id'] for row in objective_rows} if objectives_ready else set()
    coverage_rows = value.get('coverage') if isinstance(value.get('coverage'), list) else []
    coverage_ready = bool(coverage_rows)
    for index, row in enumerate(coverage_rows):
        path = f'assessment.coverage[{index}]'
        if not isinstance(row, dict):
            coverage_ready = False
            continue
        if objectives_ready and ready(path + '.objective_id') and row['objective_id'] not in objectives:
            issue(path + '.objective_id', 'must reference a declared objective')
        if not ready(path + '.count') or not ready(path + '.template_id'):
            coverage_ready = False
            continue
        if type(row.get('count')) is not int or row['count'] <= 0:
            issue(path + '.count', 'must be a positive integer')
            coverage_ready = False
            continue
        coverage[row['template_id']] += row['count']
    if coverage_ready and selections_ready and coverage != expected_counts:
        issue('assessment.coverage', 'counts must match pipeline selections per template')
    dataset = value.get('dataset') if isinstance(value.get('dataset'), dict) else {}
    target = dataset.get('target_items')
    if ready('assessment.dataset.target_items'):
        if type(target) is not int or coverage_ready and target != sum(coverage.values()):
            issue('assessment.dataset.target_items', 'must equal the allocated item count')
        if 'target_items' in inputs and inputs['target_items'] != target:
            issue('assessment.dataset.target_items', 'conflicts with pipeline inputs')
    if ready('assessment.dataset.seed'):
        if type(dataset.get('seed')) is not int:
            issue('assessment.dataset.seed', 'must be an integer')
        if 'seed' in inputs and inputs['seed'] != dataset.get('seed'):
            issue('assessment.dataset.seed', 'conflicts with pipeline inputs')
    from .scene_policy import scene_design_parser
    parser = scene_design_parser()
    if ready('assessment.scenes.designs') and ready('assessment.scenes.geometry_exceptions'):
        try:
            parser.validate_geometry_declarations(scenes)
        except ValueError as error:
            issue('assessment.scenes.geometry_exceptions', ': ' + str(error))
    for index, design in enumerate(designs):
        path = f'assessment.scenes.designs[{index}]'
        if isinstance(design, dict) and 'summary' in design and ready(path):
            try:
                parser.validate_scene_brief(design)
            except ValueError as error:
                issue(path, ': ' + str(error))
    if ready('assessment.scenes.allow_new_scenes'):
        if type(scenes.get('allow_new_scenes')) is not bool:
            issue('assessment.scenes.allow_new_scenes', 'must be a boolean')
        elif not scenes['allow_new_scenes'] and ready('assessment.scenes.selected_scenes') and not scenes['selected_scenes']:
            issue('assessment.scenes.selected_scenes', 'must reference selected scenes for a reuse-only assessment')
    if ready('assessment.scenes.target_scene_count') and scenes.get('target_scene_count') is not None and (
            type(scenes['target_scene_count']) is not int or scenes['target_scene_count'] <= 0):
        issue('assessment.scenes.target_scene_count', 'must be a positive integer or null')
    selection = inputs.get('scene_selection')
    if selection and ready('assessment.scenes.selected_scenes') and ready('assessment.scenes.allow_new_scenes'):
        allowed = selection.get('selected_scenes', selection.get('sources', []))
        allowed_ids = {(row.get('task_id', row.get('id')), row.get('revision')) for row in allowed}
        chosen_ids = set()
        for index, row in enumerate(scenes['selected_scenes']):
            path = f'assessment.scenes.selected_scenes[{index}]'
            if not isinstance(row, dict):
                issue(path, 'must be a scene reference object')
                continue
            identifier, revision = row.get('task_id', row.get('id')), row.get('revision')
            if not isinstance(identifier, str) or not identifier.strip() or not isinstance(revision, (int, str, type(None))):
                issue(path, 'must identify a saved scene and revision')
                continue
            chosen_ids.add((identifier, revision))
        if scenes['allow_new_scenes'] != selection.get('allow_new_scenes') or not chosen_ids <= allowed_ids:
            issue('assessment.scenes', 'must honor the saved scene selection and revisions')
        if scenes.get('selection_path') != selection.get('selection_path'):
            issue('assessment.scenes.selection_path', 'must match the saved selection')
    scoring = value.get('scoring') if isinstance(value.get('scoring'), dict) else {}
    if selections_ready and ready('assessment.scoring.metrics') and {row['template_id'] for row in scoring['metrics']} != set(expected_counts):
        issue('assessment.scoring.metrics', 'must cover exactly the selected templates')
    stages = {'S1', 'S2', 'S3', 'S4', 'S5'}
    if ready('assessment.execution') and {row['stage'] for row in value['execution']} != stages:
        issue('assessment.execution', 'must cover S1 through S5')
    if ready('assessment.delivery.artifacts') and {row['stage'] for row in value['delivery']['artifacts']} != stages:
        issue('assessment.delivery.artifacts', 'must declare viewable artifacts for all five stages')
    if issues:
        raise AssessmentValidationError(issues)
    return deepcopy(value)
