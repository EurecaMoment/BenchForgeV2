// Bring the actual reference and latest render together at the existing review.
// These are production observations, not a separate model evaluator or score.
export function createDeliveryVisuals({ api, images }) {
  return async ({ task, agent, signal }) => {
    const hasReference = Boolean(task.unit.intent.layout);
    const count = Number.isInteger(task.result?.report?.frames) && task.result.report.frames > 0
      ? task.result.report.frames : 1;
    const views = Array.from({ length: count }, (_value, index) => `capture/view_${index}.png`);
    const files = [...(hasReference ? ['layout/reference.png'] : []), ...views];
    const evidence = await Promise.all(files.map(file => api('/evidence', {
      task_id: task.id, revision: task.unit.revision, file,
    }, signal)));
    const paths = evidence.map(item => item.source_path);
    const blocks = await images(paths, agent, signal);
    const labels = [
      ...(hasReference ? ['Design reference (appearance intent, not geometry or simulator GT)'] : []),
      ...views.map((_file, index) => `Latest capture view_${index} (captured scene appearance, not a visual-quality acceptance)`),
    ];
    const content = paths.flatMap((path, index) => [
      { type: 'text', text: `${labels[index]}: ${path}` },
      ...blocks[index] ? [blocks[index]] : [],
    ]);
    if (!hasReference) content.unshift({ type: 'text', text: 'Actual renders; no linked design reference. When matching a user-selected reference, inspect that image alongside these views. Link an existing image with layout={mode:"reference",source_image:<source_path>}. A scene requested without a reference needs no reference image.' });
    return content;
  };
}
