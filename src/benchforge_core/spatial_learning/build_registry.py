"""Compile auditable task programs, not seed or wording variants, into the core."""
import json
from pathlib import Path

CORE=Path(__file__).resolve().parent
NAMES=['距离感知','尺寸感知','形状感知','自运动感知','外部运动感知','重力方向感知','物体朝向感知','拓扑关系感知','跨视角对应','目标检测','空间定位','空间描述','语义关系理解','运动语义理解','视角转换','可供性理解','认知地图','空间记忆检索','动力学推理','几何问题推理','空间关系推理','操作序列规划','路径规划','操作执行','导航执行','主动知识获取','自主目标生成']
# Each operator changes the queried fact or required behavior. Profiles change the
# spatial construction, motion law, graph structure or interaction failure mode.
OPS={
'N01':'distance nearest farthest rank compare within_count within_set distance_ratio distance_difference pair_nearest pair_farthest equidistant',
'N02':'width height area perimeter diagonal aspect largest smallest size_rank area_compare width_ratio fits',
'N03':'shape sides concave_vertices convex symmetry_axes shape_match shape_count shape_set perimeter_class reflected_match rotated_match holes',
'N04':'translation rotation heading travel_distance displacement_x displacement_y inverse_translation endpoint path_length return_to_start turn_direction pose_sequence',
'N05':'displacement velocity speed acceleration direction path_length approaching separating fastest slowest crossing motion_sequence',
'N06':'down_vector up_vector down_angle camera_roll downhill_step fall_direction projection_x projection_y gravity_projection lower_object settled_side downhill_rank',
'N07':'heading heading_vector clockwise_turn counterclockwise_turn relative_heading aligned parallel perpendicular heading_rank nearest_heading rotate_to face_reference',
'N08':'relation touching overlapping contained disjoint connected components adjacent_set containment_chain intersection_area contact_count reachable_set',
'N09':'target_match all_matches unmatched_a unmatched_b match_count correspondence_pairs target_bbox target_center changed_position changed_orientation same_entity permutation',
'N10':'all_boxes category_boxes category_count category_centers largest_box smallest_box leftmost_box rightmost_box topmost_box bottommost_box region_boxes missing_category',
'N11':'center bbox center_pixels bbox_pixels x_coordinate y_coordinate quadrant nearest_corner visible_area correction translation_to_center region',
'N12':'horizontal_fact vertical_fact distance_fact size_fact direction_fact topology_fact all_pair_facts target_facts scene_facts ranked_description motion_facts bounded_description',
'N13':'resolve_left resolve_right resolve_above resolve_below resolve_nearest resolve_farthest resolve_between resolve_inside resolve_largest resolve_smallest role_swap conjunction',
'N14':'event approach depart clockwise counterclockwise stationary accelerate decelerate reverse stop_start crossing following',
'N15':'point vector inverse_point relative_point compose_points transform_angle transformed_bbox relative_distance camera_origin future_point trajectory change_observer',
'N16':'door_pass clearance fit_container reach lift support stack insert turn_space tool_length traversable_edges feasible_actions',
'N17':'edges adjacency neighbors degree components reachable shortest_cost cycle has_edge missing_link route integrated_map',
'N18':'initial_position last_position previous_position visited_nodes visit_order last_seen first_seen observation_count recalled_edges recalled_heading event_before event_after',
'N19':'future_position future_velocity future_distance intercept collision_time bounce friction_stop acceleration trajectory momentum energy force',
'N20':'rotate reflect translate scale area_union area_intersection bbox_union centroid polygon_area distance_to_line volume surface_area',
'N21':'transitive inverse consistent entailed unknown_relation relation_chain ordering between contradiction reachable relation_set constraint_solution',
'N22':'plan repair_plan remove_redundancy shortest_plan valid_plan next_action preconditions effects plan_cost goal_state alternate_plan recovery_plan',
'N23':'route cost reachable blocked_edges detour alternate_optimum waypoint avoid_node budget_route reverse_route replan feasible_subgraph',
'N24':'insert place stack transfer align sort open_container retrieve assemble inspect_then_act recover_rotation recover_grasp',
'N25':'navigate waypoint visit_all return_home avoid_blockage recover_closed_door collect_delivery ordered_goals shortest_navigation explore_then_go budget_navigation replan',
'N26':'identify hypothesis_split hidden_door hidden_target costly_sensor two_stage_query noisy_repeat compare_sensors discover_edge locate_change diagnose_failure budget_query',
'N27':'utility reward_per_cost reachable_goal budget_goal coverage_goal novelty_goal prerequisite_goal multi_goal balanced_goal information_goal delivery_goal adaptive_goal',
}
PROFILES={
'geometry':['scatter','grid','ring','clusters','corridor','nested','touching','row','staircase','distractors'],
'motion':['linear','accelerating','decelerating','turning','reversal','stop_start','orbit','zigzag','camera_motion','two_targets'],
'graph':['chain','ring','star','grid','tree','diamond','bridge','directed','disconnected','weighted_detour'],
'execution':['reliable','rotation_failure','grasp_failure','blocked_route','reordered_goals','limited_budget','symmetry','distractor','delayed_feedback','multi_stage'],
}
FAMILY={**{f'N{i:02}':'geometry' for i in range(1,28)},
        **{f'N{i:02}':'motion' for i in [4,5,14,18,19]},
        **{f'N{i:02}':'graph' for i in [17,23,25]},
        **{f'N{i:02}':'execution' for i in [22,24,26,27]}}

def main():
    nodes=[];rows=[]
    for i,name in enumerate(NAMES,1):
        nid=f'N{i:02}';level='L1' if i<=11 else 'L2' if i<=18 else 'L3' if i<=23 else 'L4'
        nodes.append({'id':nid,'name':name,'level':level,'source':{'document':'空间能力知识图谱_周报汇报.pptx','pages':[3,4]},
                      'family':FAMILY[nid],'measurement_scope':'controlled synthetic scenes and explicit input conditions',
                      'training_status':'unmeasured','candidate_dependencies_are_not_locks':True})
        assert len(OPS[nid].split())==12
        for op in OPS[nid].split():
            for profile in PROFILES[FAMILY[nid]]:
                mode='interactive' if i>=24 else 'image_sequence' if nid in ['N04','N05','N09','N14','N18'] else 'image' if i<=13 else 'structured'
                rows.append({'id':f'{nid}.{op}.{profile}.v1','version':1,'primary_capabilities':[nid],
                    'supporting_capabilities':[],'query':op,'scene_family':FAMILY[nid], 'scene_profile':profile,
                    'input_mode':mode,'difficulty_axes':['density','precision','reasoning_steps','observation_budget','scene_profile','failure_mode'],
                    'answer_spec':{'encoding':'json','frame':'explicit in student input','metric':'task-specific program scorer'},
                    'oracle':f'{nid}.{op}.v1','source':{'kind':'engineering_extension','basis':'PPT node + 2026-09-30 training plan'},
                    'student_view':'observations and task conditions only','authority_view':'scene state, oracle answer and environment state',
                    'split_unit':'base_scene_group','control_conditions':['natural','supplied_intermediate','isolated'],
                    'semantic_family':op,'profile_effects':{'geometry':'layout,scale,occlusion','motion':'law,boundary,pose_history',
                    'graph':'topology,weights,feasibility','execution':'failure,feedback,budget'}[FAMILY[nid]]})
    edges=[{'source':s,'target':'N17','relation':'conditional_information_support','condition':c,'substitutable_by':alt,'evidence':'PPT page 4','validated_training_transfer':False}
           for s,c,alt in [('N01','metric mapping','given metric depth'),('N04','moving observer','given camera poses'),('N08','connectivity mapping','given local edges'),('N09','multiple views','given correspondences'),('N11','landmark positions','given coordinates'),('N15','multiple reference frames','given transforms')]]
    edges.extend({'source':'N17','target':t,'relation':'conditional_information_support','condition':'map-based task','substitutable_by':'given map','evidence':'PPT page 4','validated_training_transfer':False} for t in ['N18','N23','N25','N26'])
    for source,target,condition,substitute in [
        ('N10','N11','localization starts from visual object identification','given target box'),
        ('N01','N13','metric referring expressions','given pair distances'),
        ('N02','N16','clearance or size-dependent affordance','given dimensions'),
        ('N03','N16','shape-dependent fitting','given compatible interfaces'),
        ('N06','N19','gravity-dependent prediction','given gravity vector'),
        ('N05','N19','predicting motion from observation','given velocity and acceleration'),
        ('N07','N15','orientation-sensitive frame transform','given transformation matrix'),
        ('N09','N15','transform across views with object correspondence','given correspondences'),
        ('N11','N15','transforming visually observed positions','given coordinates'),
        ('N01','N20','metric geometric reasoning','given metric coordinates'),
        ('N03','N20','reasoning over observed geometry','given geometric primitives'),
        ('N12','N21','reasoning over a spatial description','given relation facts'),
        ('N13','N22','planning for a relationally specified target','given goal state'),
        ('N16','N22','planning under action affordances','given legal transitions'),
        ('N07','N22','orientation-dependent operation plan','given aligned pose'),
        ('N22','N24','executing a multi-action goal','given executable plan'),
        ('N11','N24','feedback-driven target positioning','given measured pose'),
        ('N23','N25','navigation using planned routes','given feasible path'),
        ('N18','N25','navigation using prior observations','given visited-state history'),
        ('N14','N26','choose observations about ambiguous motion','given event classification'),
        ('N21','N26','eliminating spatial hypotheses','given surviving hypotheses'),
        ('N16','N27','selecting feasible goals','given goal feasibility'),
        ('N23','N27','cost-sensitive spatial goals','given route costs'),
        ('N26','N27','information-seeking goal selection','given information estimates')]:
        edges.append({'source':source,'target':target,'relation':'conditional_information_support','condition':condition,
            'substitutable_by':substitute,'evidence':'engineering curriculum hypothesis; not an imported PPT edge','validated_training_transfer':False})
    graph={'schema':'benchforge.spatial_graph/v1','nodes':nodes,'edges':edges,
           'source_inventory':{'capabilities':27,'reported_candidate_edges':155,'reported_tasks':44,'reported_question_types':25,'original_json_supplied':False},
           'source_boundary':'Only relationships identifiable in supplied pages are imported; other templates are engineering extensions.',
           'courses':[
               {'id':'LOC','primary':['N11'],'source_page':7,'controls':['center','bbox','correction']},
               {'id':'XVP','primary':['N15','N19'],'source_page':8,'controls':['motion_only','transform_only','future_state_supplied','joint']},
               {'id':'MAP','original_task_id':'T-C08','primary':['N17','N16','N23'],'supporting':['N02'],'source_page':9,'controls':['local_observations','given_map','given_feasible_graph']},
               {'id':'INS','primary':['N11','N07','N22','N24'],'source_page':10,'controls':['given_pose','given_plan','feedback_execution','failure_recovery']}],
           'scheduling':'Branch-specific mastery; no mandatory L1-to-L4 order.'}
    CORE.mkdir(parents=True,exist_ok=True)
    (CORE/'graph.json').write_text(json.dumps(graph,ensure_ascii=False,indent=2),encoding='utf8')
    (CORE/'templates.json').write_text('[\n'+',\n'.join(json.dumps(row,ensure_ascii=False,separators=(',',':')) for row in rows)+'\n]\n',encoding='utf8')
    print(json.dumps({'nodes':len(nodes),'templates':len(rows),'per_capability':120}))

if __name__=='__main__':main()
