// DSH owns the parent catalog and immutable session headers. Browser-supplied
// session arrays never participate in this scope.
export function sessionFamilyReader(ctx) {
  const verified = new Map();
  return async (parentId, signal) => {
    const service = ctx.get('subagents');
    if (!service) return [];
    let entries;
    try { entries = await service.listChildren(parentId, signal); }
    catch (error) { if (signal?.aborted) throw error; return []; }
    const sessions = ctx.get('sessions'), query = ctx.get('sessionQuery');
    // Rank the existing catalog and resident handles; never open historical
    // sessions merely to decide which eight observations to request.
    const candidates = entries.map((entry, index) => {
      const resident = sessions?.get(entry.id), cached = verified.get(entry.id);
      const created=typeof entry.createdAt==='number' ? entry.createdAt : Date.parse(entry.createdAt);
      return {entry, resident, index, created: Number.isFinite(created) ? created : 0,
        active: Boolean(resident && cached?.header?.parentSession === parentId && cached.state === 'running')};
    }).sort((a, b) => Number(b.active) - Number(a.active) || Number(Boolean(b.resident)) - Number(Boolean(a.resident)) ||
      b.created - a.created || b.index - a.index).slice(0, 8);
    return (await Promise.all(candidates.map(async ({entry, resident}) => {
      signal?.throwIfAborted();
      let header = resident?.header || verified.get(entry.id)?.header;
      let state = resident ? 'unknown' : 'inactive';
      if (query && (resident || !header)) {
        let observation;
        try {
          observation = await query.observeSession(entry.id, resident ? {signal} : {signal, projectionMode: 'none'});
          header = observation.header;
          if (resident) {
            const timing = observation.projections?.values.subagentTiming;
            state = timing?.active ? 'running' : timing ? 'inactive' : 'unknown';
          }
          verified.set(entry.id, {header, state});
          if (verified.size > 128) verified.delete(verified.keys().next().value);
        } catch (error) {
          if (signal?.aborted) throw error;
          return null;
        } finally { observation?.[Symbol.dispose]?.(); }
      }
      if (header?.parentSession !== parentId) return null;
      return {...entry, state};
    }))).filter(Boolean);
  };
}
