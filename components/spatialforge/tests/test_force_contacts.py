import copy
import unittest
from spatialforge.contracts import validate_program
from spatialforge.robot_contact import contact_observation, summarize_object_contacts


class ForceContacts(unittest.TestCase):
    def test_force_contacts_can_observe_both_movable_and_static_objects(self):
        def obj(name, dynamic):
            return dict(id=name,label=name,kind='box',size=[.1,.1,.1],xy=[0,0],
                        support='ground',base_z=0,dynamic=dynamic,mass_kg=.2)
        program=dict(schema='spatialforge.scene/v1',scene_id='force_contact',title='Contact',assumptions=[],
            objects=[obj('target',True),obj('receiver',True),obj('table',False)],
            cameras=[dict(position=[1,-1,1],target=[0,0,0])],
            interactions=[dict(id='push',action='apply_force',object_id='target',force_newtons=[0,2,0],
                               contact_object_ids=['receiver','table'])])
        self.assertEqual(validate_program(program),program)
        for contacts in (['target'],['missing'],['receiver','receiver'],[{}]):
            invalid=copy.deepcopy(program);invalid['interactions'][0]['contact_object_ids']=contacts
            with self.assertRaisesRegex(ValueError,'contact_object_ids'):validate_program(invalid)
        program['interactions'][0].pop('contact_object_ids')
        self.assertEqual(validate_program(program),program)

    def test_external_force_trace_has_no_robot_columns_or_success_override(self):
        trace=[contact_observation(12,1/60,'baseline',[0,0,0],{'box':[0,.2,0]},[[0,0,0]],0),
               contact_observation(13,1/60,'force',[0,.1,0],{'box':[0,.24,0]},[[0,-3,0]],0)]
        self.assertEqual(trace[-1]['robot_contact_forces_N'],[])
        result=summarize_object_contacts(trace)['box']
        self.assertEqual(result['first_nonzero_contact_step'],13)
        self.assertEqual(result['peak_contact_force_N'],3)
        self.assertAlmostEqual(result['displacement_vector_m'][1],.04)
        self.assertNotIn('success',result)

    def test_multiple_static_colliders_are_summed_into_their_object_column(self):
        row=contact_observation(12,1/60,'force',[0,0,0],{'table':[0,0,0],'box':[0,1,0]},
            [[1,2,3],[-1,2,1],[0,-4,0]],0,{'table':2,'box':1})
        self.assertEqual(row['objects']['table']['force_on_target_N'],[0,4,4])
        self.assertEqual(row['objects']['box']['force_on_target_N'],[0,-4,0])
