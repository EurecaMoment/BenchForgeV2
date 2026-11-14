import {symbols} from '@deepseek-ai/cordis';
import z from '@deepseek-ai/schemastery';

export const name = 'benchforge-preset-aliases';
export const inject = ['agentPresets', 'sessionProjections'];
export const Config = z.object({aliases: z.dict(z.string()).required()});

// DSH's preset registry has no alias field. Map old IDs at its public
// lookup boundary and on projection reads, leaving journal entries intact.
export function installPresetAliases(ctx, aliases) {
  const canonical = id => Object.hasOwn(aliases, id) ? aliases[id] : id;
  const patch = (service, method, wrap) => {
    const target = service[symbols.original] ?? service;
    const previous = Object.getOwnPropertyDescriptor(target, method);
    const original = target[method];
    const callback = wrap(original);
    Object.defineProperty(target, method, {value: callback, configurable: true, writable: true});
    return () => {
      if (target[method] !== callback) return;
      if (previous) Object.defineProperty(target, method, previous);
      else Reflect.deleteProperty(target, method);
    };
  };
  const mapPreset = original => function (id, ...args) {
    return original.call(this, canonical(id), ...args);
  };
  const mapPresetOrDefault = original => function (id, ...args) {
    return original.call(this, canonical(id ?? this.defaultId), ...args);
  };
  const mapValues = values => {
    const id = values?.agentPreset;
    return canonical(id) === id ? values : {...values, agentPreset: canonical(id)};
  };
  const mapSnapshot = snapshot => {
    const values = mapValues(snapshot?.values);
    return values === snapshot?.values ? snapshot : {...snapshot, values};
  };
  const cleanup = [
    ...['resolve', 'acquireScope'].map(method => patch(ctx.agentPresets, method, mapPresetOrDefault)),
    patch(ctx.agentPresets, 'readDocument', mapPreset),
    patch(ctx.agentPresets, 'mount', original => function (agentContext, id) {
      return original.call(this, agentContext, canonical(id ?? this.defaultId));
    }),
    patch(ctx.agentPresets, 'remoteExportList', original => async function () {
      const roster = await original.call(this);
      const selected = this.defaultId;
      const id = canonical(selected);
      if (selected === id) return roster;
      return {...roster, presets: roster.presets.map(row => ({...row, isDefault: row.id === id}))};
    }),
    patch(ctx.sessionProjections, 'stateOf', original => function (session, key) {
      const value = original.call(this, session, key);
      return key === 'agentPreset' ? canonical(value) : value;
    }),
    ...['snapshot', 'cachedSnapshot', 'hydrate'].map(method => patch(ctx.sessionProjections, method,
      original => function (...args) {return mapSnapshot(original.apply(this, args));})),
    patch(ctx.sessionProjections, 'viewCheckpoint', original => function (...args) {
      return mapValues(original.apply(this, args));
    }),
  ];
  return () => {for (const dispose of cleanup.reverse()) dispose();};
}

export function apply(ctx, {aliases}) {
  ctx.effect(() => installPresetAliases(ctx, aliases), name);
}
