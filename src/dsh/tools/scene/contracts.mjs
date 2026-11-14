// Stable response families shared by the service, with room for its evidence
// and operation-specific fields. Do not require fields an endpoint omits.
const textRender=(_args,value)=>[{type:'text',text:JSON.stringify(value)}];
const object=(properties)=>({schema:{type:'object',additionalProperties:true,properties},render:textRender});
const string={type:'string',required:true};

export const objectOutput=object({});
export const runOutput=object({run_id:string,state:string});
export const taskRunOutput=object({run_id:string,task_id:string,state:string});
export const observationOutput=object({run_id:string,state:string,tasks:{type:'array',required:true,items:{type:'object',additionalProperties:true}}});
export const taskOutput=object({task_id:string});
export const cancellationOutput=object({cancel_requested:{type:'boolean',required:true}});
