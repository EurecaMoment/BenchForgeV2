"""Local Transformers checkpoint loading, inference and supervised updates."""
import json
from pathlib import Path


class TransformersSolver:
    def __init__(self,config):
        import torch
        import transformers
        self.torch=torch;self.config=config;self.multimodal=config.get('multimodal',False)
        model=config['model'];kwargs={'local_files_only':config.get('local_files_only',True)}
        self.device=config.get('device','cpu')
        if self.multimodal:
            self.processor=transformers.AutoProcessor.from_pretrained(model,**kwargs)
            self.model=transformers.AutoModelForImageTextToText.from_pretrained(model,**kwargs)
            self.tokenizer=self.processor.tokenizer
        else:
            self.tokenizer=transformers.AutoTokenizer.from_pretrained(model,**kwargs)
            self.model=transformers.AutoModelForCausalLM.from_pretrained(model,**kwargs)
        if self.tokenizer.pad_token_id is None:self.tokenizer.pad_token=self.tokenizer.eos_token
        if config.get('lora'):
            from peft import LoraConfig
            from peft import get_peft_model
            self.model=get_peft_model(self.model,LoraConfig(task_type='CAUSAL_LM',**config['lora']))
        self.model.to(self.device)
        self.optimizer=torch.optim.AdamW((p for p in self.model.parameters() if p.requires_grad),lr=config.get('learning_rate',2e-5))
        self.max_length=config.get('max_length',2048)

    def encode(self,messages,images,assistant=False):
        from PIL import Image
        if images and not self.multimodal:raise ValueError('This dataset has images; select a multimodal checkpoint or a structured-only task subset')
        if self.multimodal:
            messages=[dict(m) for m in messages]
            messages[0]['content']=[*[{'type':'image'} for _ in images],{'type':'text','text':messages[0]['content']}]
            text=self.processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=assistant)
            pixels=[Image.open(p).convert('RGB') for p in images]
            encoded=self.processor(text=[text],images=pixels or None,return_tensors='pt')
            for image in pixels:image.close()
        else:
            text=self.tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=assistant)
            encoded=self.tokenizer(text,return_tensors='pt',add_special_tokens=False)
        if encoded['input_ids'].shape[1]>self.max_length:raise ValueError('Sample exceeds max_length; increase the configured limit or shorten its actual evidence')
        return {k:v.to(self.device) for k,v in encoded.items()}

    def update(self,records):
        self.model.train();self.optimizer.zero_grad();losses=[];tokens=0;input_tokens=0
        for record in records:
            messages=record['messages'];images=record.get('images',[])
            encoded=self.encode(messages,images);prefix=self.encode(messages[:-1],images,assistant=True)
            labels=encoded['input_ids'].clone();labels[:,:prefix['input_ids'].shape[1]]=-100
            input_tokens+=int(encoded['input_ids'].numel())
            tokens+=int((labels!=-100).sum().item())
            if not (labels!=-100).any():raise ValueError('No assistant training tokens')
            loss=self.model(**encoded,labels=labels).loss
            (loss/len(records)).backward();losses.append(float(loss.detach().cpu()))
        self.torch.nn.utils.clip_grad_norm_(self.model.parameters(),self.config.get('max_grad_norm',1.))
        self.optimizer.step();return {'loss':sum(losses)/len(losses),'supervised_tokens':tokens,'input_tokens':input_tokens,'examples':len(records)}

    def predict(self,question):
        self.model.eval();messages=[{'role':'user','content':question['question']+'\n'+json.dumps(question['inputs'],ensure_ascii=False)}]
        encoded=self.encode(messages,question.get('images',[]),assistant=True)
        with self.torch.no_grad():generated=self.model.generate(**encoded,max_new_tokens=self.config.get('max_new_tokens',256),do_sample=False,pad_token_id=self.tokenizer.pad_token_id)
        return self.tokenizer.decode(generated[0,encoded['input_ids'].shape[1]:],skip_special_tokens=True)

    def save(self,path):
        path=Path(path);path.mkdir(parents=True,exist_ok=True)
        self.model.save_pretrained(path);(self.processor if self.multimodal else self.tokenizer).save_pretrained(path)
        self.torch.save({'model':self.model.state_dict(),'optimizer':self.optimizer.state_dict(),'torch_rng':self.torch.get_rng_state(),
                        'cuda_rng':self.torch.cuda.get_rng_state_all() if self.torch.cuda.is_available() else None},path/'training-state.pt')

    def restore(self,path):
        state=self.torch.load(Path(path)/'training-state.pt',map_location=self.device,weights_only=False)
        self.model.load_state_dict(state['model']);self.optimizer.load_state_dict(state['optimizer']);self.torch.set_rng_state(state['torch_rng'].cpu())
        if state['cuda_rng'] is not None:self.torch.cuda.set_rng_state_all(state['cuda_rng'])
