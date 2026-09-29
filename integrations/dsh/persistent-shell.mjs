import path from 'node:path';
import {pathToFileURL} from 'node:url';
export const name='benchforge-persistent-shell';
export const inject=['tools','terminals'];
export async function apply(ctx, config) {
  const implementation=await import(pathToFileURL(path.join(config.dshRoot,
    `packages/shell/tool-${config.shell}-persistent/lib/index.js`)));
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
  return implementation.apply(scoped,{timeoutMs:config.timeoutMs,
    description:`Persistent ${config.shell} for task code; cwd and environment survive calls.`});
}
