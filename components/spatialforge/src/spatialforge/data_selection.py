"""Answer-free eligibility receipts for the existing BenchClaw marker renderer."""
from collections import Counter


def filter_readable_candidates(pairs):
    """Keep geometry and GT untouched; require room around the center marker.

    BenchClaw renders radius r with a white outline. Requiring bbox extent
    2*r+6 leaves three pixels on each side of that diameter. This is a small
    marker eligibility rule, not a semantic, occlusion or realism certificate.
    """
    eligible=[];excluded={};by_source=Counter();policies={}
    for row,record in pairs:
        size=record.data['entities']['image_size']
        font_size=max(10,min(24,round(min(size['width'],size['height'])*.035)))
        radius=max(2,round(font_size/7));minimum=2*radius+6
        policies[record.record_id]={'image_size':size,'marker_radius_px':radius,'min_bbox_edge_px':minimum}
        problems=[]
        for obj in row['provenance']['objects']:
            x1,y1,x2,y2=obj['bbox']
            if min(x2-x1,y2-y1)<minimum:
                problems.append(obj['id'])
                excluded[(record.record_id,obj['id'])]={
                    'source_record':record.record_id,'object_id':obj['id'],
                    'bbox':obj['bbox'],'bbox_extent_px':[x2-x1,y2-y1],
                    'reason':'bbox_too_small_for_center_marker','min_bbox_edge_px':minimum}
        if problems:by_source[record.record_id]+=1
        else:eligible.append((row,record))
    examples=list(excluded.values())
    return eligible,{'schema':'spatialforge.data-selection/v1',
        'generated_candidates':len(pairs),'eligible_candidates':len(eligible),
        'filtered_by_marker_size':len(pairs)-len(eligible),
        'filtered_candidates_by_source':dict(by_source),'marker_policy_by_source':policies,
        'excluded_object_count':len(examples),'excluded_objects':examples[:80],
        'excluded_objects_omitted':max(0,len(examples)-80),
        'policy_basis':'BenchClaw spatial_tasks.render center radius; bbox minimum = marker diameter + 6 pixels',
        'operator_guidance':'For excluded objects, inspect the capture and choose a closer or less occluded camera view if they matter to the task. No scene parameters are changed automatically.',
        'gt_modified':False,'semantic_acceptance':False,
        'limitations':['Marker size eligibility does not prove label visibility, lack of overlap, or semantic answerability.',
                       'Visual item review still applies; review decisions are model opinions, not benchmark certification.']}
