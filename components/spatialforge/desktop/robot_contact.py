"""Franka joint-driven contact within the existing desktop capture lifecycle."""
import math
import numpy as np
from isaacsim.core.prims import RigidPrim
from isaacsim.robot.manipulators.examples.franka import Franka, KinematicsSolver
from spatialforge.robot_contact import evaluate_robot_trajectory, evaluate_robot_visibility


class ContactRobot:
    def __init__(self, action, asset_root):
        self.path = '/World/Robots/'+action['robot_id']
        self.usd = str(asset_root/'Robots/Franka/franka.usd')
        self.robot = Franka(self.path, name=action['robot_id'], usd_path=self.usd,
                            position=np.asarray(action['robot_base_position']),
                            orientation=np.asarray(action.get('robot_base_orientation_wxyz',[1.,0.,0.,0.])))
        self.robot.set_joints_default_state(positions=np.array([0.,-.4,0.,-2.4,0.,2.,.8,0.,0.]))
        self.filters = [self.path+'/'+part for part in ['panda_hand','panda_leftfinger','panda_rightfinger']]

    def initialize(self):
        self.robot.initialize()
        self.robot.post_reset()
        self.robot.set_joint_positions(np.array([0.,-.4,0.,-2.4,0.,2.,.8,0.,0.]))
        self.controller = KinematicsSolver(self.robot)
        self.controller.get_kinematics_solver().set_robot_base_pose(*self.robot.get_world_pose())

    def view(self, action, entities):
        return RigidPrim(entities[action['object_id']]['prim_path'],name='robot_contact_'+action['id'],
                         reset_xform_properties=False,track_contact_forces=True,
                         contact_filter_prim_paths_expr=self.filters,max_contact_count=128)

    def run(self, action, view, witnesses, sim, dt, start_step, capture):
        step=start_step;phase='baseline';samples=[];ik_failures=0
        def record():
            p,q=view.get_world_poses()
            samples.append({'step':step,'timestamp_sim':step*dt,'phase':phase,
                'position':np.asarray(p)[0].tolist(),'orientation_wxyz':np.asarray(q)[0].tolist(),
                'linear_velocity_m_s':np.asarray(view.get_linear_velocities())[0].tolist(),
                'robot_contact_forces_N':np.asarray(view.get_contact_force_matrix(dt=dt))[0].tolist(),
                'witnesses':{key:np.asarray(v.get_world_poses()[0])[0].tolist() for key,v in witnesses.items()},
                'robot_joint_positions':np.asarray(self.robot.get_joint_positions()).tolist(),
                'robot_finger_position':np.asarray(self.robot.end_effector.get_world_pose()[0]).tolist(),
                'robot_ik_frame_position':np.asarray(self.controller.compute_end_effector_pose(position_only=True)[0]).tolist()})
        def advance():
            nonlocal step
            sim.step(render=False);step+=1
            if (step-start_step)%3==0:record()
        sim.play()
        for _ in range(round(1/dt)):advance()
        # Compare motion to the settled state immediately before approach.
        baseline=samples; samples=[]; record()
        sim.pause();before_image,before_visibility=capture('before');sim.play()
        orientation=np.asarray(action.get('end_effector_orientation_wxyz',[0.,1.,0.,0.]))
        for waypoint in action['waypoints']:
            # Interpolate in the same right_gripper frame that Lula targets.
            # Franka.end_effector is panda_rightfinger, a different physical frame.
            phase=waypoint['id'];start=np.asarray(self.controller.compute_end_effector_pose(position_only=True)[0])
            goal=np.asarray(waypoint['position']);steps=math.ceil(waypoint['duration_s']/dt)
            for i in range(steps):
                target=start+(goal-start)*((i+1)/steps)
                command,ok=self.controller.compute_inverse_kinematics(target_position=target,target_orientation=orientation)
                if ok:self.robot.get_articulation_controller().apply_action(command)
                else:ik_failures+=1
                advance()
        phase='settle_after'
        for _ in range(math.ceil(action.get('observe_seconds',1.5)/dt)):advance()
        if samples[-1]['step']!=step:record()
        sim.pause();after_image,after_visibility=capture('after')
        measured=evaluate_robot_visibility(evaluate_robot_trajectory(samples),before_visibility,after_visibility)
        # The control implementation never writes target poses or applies target forces.
        measured['checks'].update(no_target_force_or_pose_commands=True,before_after_images_present=True,completed=True)
        record={'schema':'spatialforge.interaction/v1','id':action['id'],'action':'robot_push','object_id':action['object_id'],
            'physics_backend':'Isaac PhysX','executor':'Franka articulation controller and Lula inverse kinematics',
            'parameters':action,'dt':dt,'baseline':baseline,'trajectory':samples,'metrics':measured,
            'robot':{'prim_path':self.path,'usd':self.usd,'contact_filter_paths':self.filters,'ik_failures':ik_failures,
                     'ik_frame':self.controller.get_end_effector_frame(),'observed_finger_prim_path':self.path+'/panda_rightfinger'},
            'object_direct_force_calls':0,'object_pose_writes_after_start':0,
            'before_image':before_image,'after_image':after_image,
            'visual_evidence':{'before':before_visibility,'after':after_visibility}}
        return record,step
