import z from '@deepseek-ai/schemastery';

export const name='benchforge-persistent-shell';
export const inject=['tools','terminals'];
export const Config=z.object({
  shell:z.union(['bash','pwsh']).default('bash'),
  backendType:z.string().default('shell'),
  timeoutMs:z.number().step(1).min(1).default(300_000),
  maxOutputChars:z.number().step(1).min(1).default(16_000),
  description:z.string(),
  // Accepted for existing overlays; module resolution uses public package exports.
  dshRoot:z.string(),
});

export async function apply(ctx, config) {
  const implementation=config.shell==='pwsh'
    ?await import('@deepseek-ai/dsh-tool-pwsh-persistent')
    :await import('@deepseek-ai/dsh-tool-bash-persistent');
  const tools=new Proxy(ctx.tools,{get(target,key){
    if(key==='register')return definition=>target.register({...definition,name:`persistent_${config.shell}`});
    const value=Reflect.get(target,key,target);
    return typeof value==='function'?value.bind(target):value;
  }});
  const scoped=new Proxy(ctx,{get(target,key){
    if(key==='tools')return tools;
    const value=Reflect.get(target,key,target);
    return typeof value==='function'?value.bind(target):value;
  }});
  return implementation.apply(scoped,{
    backendType:config.backendType,
    timeoutMs:config.timeoutMs,
    maxOutputChars:config.maxOutputChars,
    description:config.description??`Persistent ${config.shell} for task code; cwd and environment survive calls.`,
  });
}
