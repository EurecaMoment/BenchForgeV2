"""CPU training-engine demonstration; no downloads, model API or simulator.

Creates a small random Transformer, learns a program-grounded relation task,
saves and reloads an optimizer checkpoint and exposes the standard event log.
This is an engine demonstration, not evidence of 27-capability competence.
"""
import argparse
import json
from pathlib import Path


def main():
    import torch
    from tokenizers import Tokenizer,models,pre_tokenizers,trainers
    from transformers import GPT2Config,GPT2LMHeadModel,PreTrainedTokenizerFast
    from benchforge_core.spatial_learning.generation import generate,write_json
    from benchforge_core.spatial_learning.evaluation import read_rows
    from benchforge_core.spatial_learning.training import run
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',required=True)
    args=parser.parse_args();root=Path(args.workspace).resolve();root.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(2);torch.manual_seed(71)
    result=generate({'template_ids':['N21.unknown_relation.scatter.v1'],'groups_per_profile':100,'render':False},root)
    data=Path(result['dataset']);records=read_rows(data/'train/sft.jsonl')
    tokenizer=Tokenizer(models.WordLevel(unk_token='[UNK]'));tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
    tokenizer.train_from_iterator([m['content'] for r in records for m in r['messages']],trainers.WordLevelTrainer(special_tokens=['[UNK]','[PAD]','[BOS]','[EOS]','[USER]','[ASSISTANT]']))
    fast=PreTrainedTokenizerFast(tokenizer_object=tokenizer,unk_token='[UNK]',pad_token='[PAD]',bos_token='[BOS]',eos_token='[EOS]')
    fast.chat_template="{% for m in messages %}{{ '[USER] ' if m['role']=='user' else '[ASSISTANT] ' }}{{m['content']}}{{ ' [EOS] ' if m['role']=='assistant' else ' ' }}{% endfor %}{% if add_generation_prompt %}{{ '[ASSISTANT] ' }}{% endif %}"
    model=GPT2LMHeadModel(GPT2Config(vocab_size=len(fast),n_positions=512,n_embd=64,n_layer=2,n_head=2,bos_token_id=fast.bos_token_id,eos_token_id=fast.eos_token_id,pad_token_id=fast.pad_token_id))
    model_dir=root/'initial-model';model.save_pretrained(model_dir);fast.save_pretrained(model_dir)
    config={'model':str(model_dir),'dataset':str(data),'device':'cpu','local_files_only':True,'seed':71,
        'windows':3,'steps_per_window':50,'batch_size':4,'learning_rate':.002,'max_length':512,'max_new_tokens':4,
        'dev_limit':15,'selection_limit':10,'condition':'C','curriculum':{'min_scenes':20,'min_samples':100}}
    write_json(root/'train-config.json',config);result=run(config,root/'training')
    config.update(resume=result['checkpoint'],windows=4,steps_per_window=5)
    resumed=run(config,root/'training')
    events=read_rows(root/'training/events.jsonl');updates=[e for e in events if e['event']=='update'];development=[e for e in events if e['event']=='development']
    report={'parameters':sum(p.numel() for p in model.parameters()),'backend':'actual local GPT2 Transformer, randomly initialized',
        'first_loss':updates[0]['loss'],'last_loss':updates[-1]['loss'],'steps':resumed['steps'],
        'initial_selection':development[0]['selection_score'],'final_selection':development[-1]['selection_score'],
        'checkpoint':resumed['checkpoint'],'resume_completed':resumed['steps']>result['steps'],
        'scope':'one controlled relation task; no pretrained-model or graph-transfer claim','sealed_test_used':False}
    write_json(root/'verification.json',report);print(json.dumps(report,indent=2))


if __name__=='__main__':main()
