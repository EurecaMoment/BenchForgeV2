"""Small report adapters; all analytical inputs come from declared Bundle records."""
import importlib.util
import json
import sys
from pathlib import Path


def export_kinship(bundle,output):
    path=Path(__file__).resolve().parents[2]/'BenchClaw/tools/gt_kinship_base.py'
    name='benchclaw_kinship'
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    module=sys.modules[name]
    # IDs are local sequential identities; no cryptographic hash checks or file scans.
    identities={}
    module.stable_hash=lambda value,length=12: identities.setdefault(value,str(len(identities)+1).zfill(length))
    used={ref for answer in bundle.answers for ref in answer.evidence_refs}
    selected={ref for ev in bundle.evidence if ev.evidence_id in used for ref in getattr(ev,'source_refs',[])}
    records=[r for r in bundle.records if r.record_id in selected]
    assets={a.asset_id:a for a in bundle.assets}
    class Analyzer(module.GTKinshipAnalyzerBase):
        def infer_gt_origin(self,evidence,field_path,value):
            return evidence.source_type
        def infer_visibility_status(self,evidence,field_path,value):
            return 'visible' if 'bbox_2d' in field_path or 'category' in field_path else 'uncertain'
        def is_answerable_source(self,evidence,field_path,value,origin,visibility):
            return visibility=='visible' or origin=='official_label'
    analyzer=Analyzer(workspace_root=output,output_dir=output,max_fields_per_record=80,max_group_pairs=120,max_kinship_pairs=2000,max_chains=80)
    evidence=[module.EvidenceRecord(record_id=r.record_id,source_file=Path('source_records.jsonl'),
        source_type='official_label' if r.format=='official_qa' else 'model_annotation',source_sample_id=r.record_id,
        scene_id=assets[r.asset_refs[0]].scene_id,media_refs=[assets[a].uri for a in r.asset_refs],raw=r.data) for r in records]
    fields=analyzer.make_gt_fields(evidence);nodes=analyzer.build_nodes(fields);edges=analyzer.build_edges(nodes)
    matrix=analyzer.build_kinship_matrix(nodes,edges);chains,filtered=analyzer.build_reasoning_chains(nodes,edges,matrix)
    graph=analyzer.build_kinship_graph(nodes,edges,matrix,chains)
    output.mkdir(exist_ok=True);analyzer.write_outputs(nodes,edges,matrix,chains,filtered,graph,[])
    (output/'scope.json').write_text(json.dumps({'selected_source_records':len(records),'nodes':len(nodes),'edges':len(edges),
        'chains':len(chains),'max_fields_per_record':80,'max_pairs':2000,
        'purpose':'bounded candidate kinship diagnostics; generated questions still require deterministic evidence replay',
        'files_scanned':0,'cryptographic_hash_checks':0}))
    return {'nodes':len(nodes),'edges':len(edges),'chains':len(chains)}
