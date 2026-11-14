type ReadView = 'runtime' | 'summary' | 'progress' | 'run' | 'stage_artifacts' | 'catalog' | 'dataset' |
  'scene_library' | 'scene_selection' | 'stage_review' | 'plan_template' | 'execution_status' | 'synthesis_status';

type WriteView = 'stage_review' | 'scene_selection' | 'plan_edit' | 'execution_control' | 'synthesis_start';

export type ReadQuery = {view: ReadView} & Record<string, string>;
export type WriteQuery = {view: WriteView} & Record<string, string>;

export type JsonValue = null | boolean | number | string | JsonValue[] | {[key: string]: JsonValue};
