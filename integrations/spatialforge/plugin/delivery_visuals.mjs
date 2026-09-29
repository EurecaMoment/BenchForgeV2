// Bring the actual reference and latest render together at the existing review.
// These are production observations, not a separate model evaluator or score.
export function createDeliveryVisuals({ api, images }) {
  return async ({ task, agent, signal }) => {
    if (!task.unit.intent.layout) return [];
    const count = Number.isInteger(task.result?.report?.frames) && task.result.report.frames > 0
      ? task.result.report.frames : 1;
    const files = ['layout/reference.png', ...Array.from({ length: count }, (_value, index) => `capture/view_${index}.png` )];
    const evidence = await Promise.all(files.map(file => api('/evidence', {
      task_id: task.id, revision: task.unit.revision, file,
    }, signal)));
    const paths = evidence.map(item => item.source_path);
    const blocks = await images(paths, agent, signal);
    const labels = [
      'Design reference (appearance intent, not geometry or simulator GT)',
      ...files.slice(1).map((_file, index) => `Latest capture view_${index} (choose the view that best matches the reference; this is not simulator GT)`),
    ];
    return paths.flatMap((path, index) => [
      { type: 'text', text: `${labels[index]}: ${path}` },
      ...blocks[index] ? [blocks[index]] : [],
    ]);
  };
}
