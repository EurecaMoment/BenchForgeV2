const sceneOnlySuffixes = new Set(['catalog', 'status', 'sam3', 'sam3d', 'evidence', 'collaboration']);
const legacyPrefix = 'spatialforge_';

export function canonicalSceneToolName(name) {
  if (typeof name !== 'string' || !name.startsWith(legacyPrefix)) return name;
  const suffix = name.slice(legacyPrefix.length);
  return (sceneOnlySuffixes.has(suffix) ? 'benchforge_scene_' : 'benchforge_') + suffix;
}

export function sceneToolNames(name) {
  return [name, legacyPrefix + name.replace(/^benchforge_(?:scene_)?/, '')];
}

export const captureObservationNames = ['benchforge_scene_status', 'benchforge_wait', 'benchforge_scene_evidence'];
