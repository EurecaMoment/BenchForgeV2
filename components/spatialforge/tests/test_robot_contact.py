import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'desktop')]
from spatialforge.robot_contact import evaluate_robot_trajectory
from spatialforge.contracts import validate_program
from scene_runtime import interaction_plan

class RobotContactTest(unittest.TestCase):
    def test_robot_declaration_and_unchanged_force(self):
        p={'schema':'spatialforge.scene/v1','scene_id':'robot_test','title':'Robot test','assumptions':[],
           'objects':[{'id':'can','label':'can','kind':'cylinder','size':[.08,.08,.16],'xy':[.52,0],
                       'support':'ground','base_z':0,'dynamic':True,'mass_kg':.15}],
           'cameras':[{'id':'view','position':[1,-1,1],'target':[.5,0,.1],'focal_length_mm':30}],
           'interactions':[{'id':'push','action':'robot_push','object_id':'can','robot_id':'franka',
                'robot_base_position':[0,0,0],'waypoints':[{'id':'push','position':[.52,.1,.05],'duration_s':4}]}]}
        validate_program(p)
        self.assertTrue(interaction_plan(p)[0]['supported'])
        p['interactions'][0]['recording']={'every_steps':4}
        self.assertEqual(validate_program(p)['interactions'][0]['recording'],{'every_steps':4})
        p['interactions']=[{'id':'force','action':'apply_force','object_id':'can','force_newtons':[.5,0,0]}]
        validate_program(p)
        plan=interaction_plan(p)[0]
        self.assertEqual((plan['duration_steps'],plan['observe_steps'],plan['min_displacement_m']),(30,90,.02))
        p['interactions'][0]['recording']={}
        self.assertEqual(validate_program(p)['interactions'][0]['recording'],{})
        p['interactions'][0]['recording']={'every_steps':0}
        with self.assertRaisesRegex(ValueError,'positive integer'):validate_program(p)

    def test_contact_and_falling_outcomes(self):
        def row(step,y,force=0,q=None):
            return {'step':step,'position':[0,y,.1],'orientation_wxyz':q or [1,0,0,0],
                    'robot_contact_forces_N':[[0,force,0]],'witnesses':{'still':[1,0,.1]}}
        samples=[row(0,0),row(3,0,.1),row(6,.02,.1),row(9,.06,.1),row(12,.07)]
        self.assertTrue(evaluate_robot_trajectory(samples)['success'])
        samples[-1]['orientation_wxyz']=[.707106781,.707106781,0,0]
        self.assertFalse(evaluate_robot_trajectory(samples)['success'])
        samples[-1]['orientation_wxyz']=[1,0,0,0]
        for r in samples:r['robot_contact_forces_N']=[[0,0,0]]
        self.assertFalse(evaluate_robot_trajectory(samples)['success'])

if __name__=='__main__':unittest.main()
