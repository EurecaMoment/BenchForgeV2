"""Trusted generic SceneProgram executor. Run only with desktop Isaac python.bat."""
import argparse
import os
import json
import math
from pathlib import Path
import sys
import traceback

parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--output',required=True)
args=parser.parse_args(); output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
job=json.loads(Path(args.request).read_text(encoding='utf8'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from spatialforge.contracts import validate_program, ASSETS
from spatialforge.scene_preflight import preflight_scene
from spatialforge.support_graph import objects_in_support_order
from spatialforge.material_catalog import load_native_materials
from scene_runtime import render_options, room_metadata, light_specs, material_for, part_material_for, interaction_plan, select_interaction_camera, evaluate_force_trajectory, transform_mesh_geometry
from camera_controls import camera_matrix, apply_camera_optics, camera_evidence
from primitive_geometry import define_textured_primitive
from spatialforge.environment_catalog import apply_environment_texture
from spatialforge.mesh_geometry import transform_mesh_normals
from spatialforge.capture_scope import capture_scope
program=validate_program(job['program']);settings=job['capture']
report={'schema':'spatialforge.capture/v1','token':job['token'],'task_id':job['task_id'],'revision':job['revision'],'status':'failed','errors':[]}
scope=capture_scope(program,job.get('capture_options'))
report['capture_scope']=scope
scene_preflight=preflight_scene(program)
report['scene_preflight']=scene_preflight
if not scene_preflight['passed']:
    report['errors'].append('scene preflight failed; inspect scene_preflight.errors')
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    raise SystemExit(2)
from isaacsim import SimulationApp
hybrid_rendering=any(o['kind']=='mesh' and o.get('render_representation')!='mesh'
                     and (Path(job['asset_paths'][o['asset_id']]).parent/'gaussian.npz').is_file()
                     for o in program['objects'])
render_config=render_options(program,settings,has_gaussians=hybrid_rendering)
has_robot=any(a.get('action')=='robot_push' for a in program.get('interactions',program.get('affordances',[])))
# Articulated scenes also use Fabric with UJITSO geometry: the legacy geometry
# path can crash Isaac 6.0.1 when synthetic-data instance annotation starts.
hybrid_args=['--/app/useFabricSceneDelegate=true','--/UJITSO/geometry=true'] if hybrid_rendering or has_robot else []
if has_robot:
    hybrid_args+=['--enable','isaacsim.robot.manipulators.examples']
    settings={**settings,'dt':1/120}
app=SimulationApp({'extra_args':hybrid_args,'headless':True,'width':settings['width'],'height':settings['height'],'renderer':render_config['renderer'],'multi_gpu':False})
code=1
try:
    import carb
    import numpy as np
    import omni.usd
    import omni.replicator.core as rep
    if hybrid_rendering:
        from isaacsim.core.utils.extensions import enable_extension
        enable_extension('omni.usd.schema.usd_particle_field');enable_extension('omni.rtx.spg')
    from PIL import Image
    from pxr import Usd, UsdGeom, UsdPhysics, UsdLux, UsdShade, Gf, Sdf, Semantics, Vt
    from isaacsim.core.api import SimulationContext
    from native_appearance import apply_native_appearance
    from imported_appearance import bind_imported_materials
    from material_controls import apply_dielectric_controls,apply_texture_tint
    from light_geometry import apply_light_geometry
    from capture_images import read_rgb_bounded, object_visibility, instance_region
    from render_quality import assess_view
    from scene_export import export_scene
    carb.settings.get_settings().set('/physics/updateToUsd',True)
    renderer_settings=carb.settings.get_settings()
    if 'samples_per_pixel' in render_config and render_config['renderer']=='PathTracing':
        renderer_settings.set('/rtx/pathtracing/spp',render_config['samples_per_pixel'])
        renderer_settings.set('/rtx/pathtracing/totalSpp',render_config['samples_per_pixel'])
    if 'exposure' in render_config:
        # Manual exposure in stops, with the renderer's ISO convention (100 = 0 EV).
        renderer_settings.set('/rtx/post/histogram/enabled',False)
        renderer_settings.set('/rtx/post/tonemap/filmIso',100.*2.**render_config['exposure'])
    report['render_settings']={**render_config,'exposure_implementation':'camera exposure:iso=100*2^EV plus renderer filmIso',
                              'pathtracing_spp':renderer_settings.get('/rtx/pathtracing/spp'),
                              'film_iso':renderer_settings.get('/rtx/post/tonemap/filmIso'),
                              'product_lifecycle':'one persistent product, camera and annotators; camera pose and optics change across views'}
    actions=interaction_plan(program)
    omni.usd.get_context().new_stage()
    stage=omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z);UsdGeom.SetStageMetersPerUnit(stage,1.0)
    world=UsdGeom.Xform.Define(stage,'/World');stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Xform.Define(stage,'/World/Objects')
    UsdGeom.Scope.Define(stage,'/World/Materials')
    # Lighting is declarative and remains independent of geometry.  Isaac's
    # light schemas differ slightly by kind, so only common physically
    # meaningful attributes are authored here.
    environment_dependencies=[]
    report['light_receipts']=[]
    for light_spec in light_specs(program):
        kind=light_spec['kind'];lid=light_spec['id'];light_path='/World/Lights/'+lid
        light_types={'dome':UsdLux.DomeLight,'distant':UsdLux.DistantLight,'rect':UsdLux.RectLight,'disk':UsdLux.DiskLight,'sphere':UsdLux.SphereLight}
        light=light_types[kind].Define(stage,light_path)
        light.CreateIntensityAttr(float(light_spec.get('intensity',600)))
        light.CreateColorAttr(Gf.Vec3f(*light_spec.get('color',[1,1,1])))
        if light_spec.get('environment_id'):
            environment_dependencies.append(apply_environment_texture(light,light_spec['environment_id'],Path(os.environ['SPATIALFORGE_ISAAC_ASSET_ROOT']),light_spec.get('direction')))
        if 'temperature' in light_spec:
            light.CreateEnableColorTemperatureAttr(True)
            if hasattr(light,'CreateColorTemperatureAttr'):light.CreateColorTemperatureAttr(float(light_spec['temperature']))
            elif hasattr(light,'CreateTemperatureAttr'):light.CreateTemperatureAttr(float(light_spec['temperature']))
        report['light_receipts'].append(apply_light_geometry(light,light_spec))
        xform=UsdGeom.Xformable(light)
        if 'position' in light_spec:xform.AddTranslateOp().Set(Gf.Vec3d(*light_spec['position']))
        if 'direction' in light_spec and not light_spec.get('environment_id'):
            rotation=Gf.Rotation(Gf.Vec3d(0,0,-1),Gf.Vec3d(*light_spec['direction']).GetNormalized())
            xform.AddOrientOp().Set(Gf.Quatf(rotation.GetQuat()))
        if light_spec.get('source_kind')=='spot':
            outer=float(light_spec.get('outer_cone_deg',45));inner=float(light_spec.get('inner_cone_deg',0))
            shaping=UsdLux.ShapingAPI.Apply(light.GetPrim())
            shaping.CreateShapingConeAngleAttr(outer)
            shaping.CreateShapingConeSoftnessAttr(1-inner/outer)
        if 'cast_shadows' in light_spec:
            UsdLux.ShadowAPI.Apply(light.GetPrim()).CreateShadowEnableAttr(light_spec['cast_shadows'])

    def shape(path,kind,size,color,offset=(0,0,0),collision=True,rotation_deg_xyz=(0,0,0)):
        if kind=='box':
            mesh=UsdGeom.Cube.Define(stage,path);mesh.CreateSizeAttr(1);scale=size
        elif kind=='sphere':
            mesh=UsdGeom.Sphere.Define(stage,path);mesh.CreateRadiusAttr(.5);scale=size
        elif kind=='cylinder':
            mesh=UsdGeom.Cylinder.Define(stage,path);mesh.CreateRadiusAttr(.5);mesh.CreateHeightAttr(1);mesh.CreateAxisAttr('Z');scale=size
        x=UsdGeom.Xformable(mesh);x.AddTranslateOp().Set(Gf.Vec3d(*offset))
        if any(rotation_deg_xyz):x.AddRotateXYZOp().Set(Gf.Vec3f(*rotation_deg_xyz))
        x.AddScaleOp().Set(Gf.Vec3f(*scale))
        mesh.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        if collision:UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
        return mesh

    # Rooms are metadata only.  A portal cannot be represented by an
    # automatically sealed box; walls, floors, doors and windows must be
    # explicit scene objects supplied by the proposal.
    room_dependencies=room_metadata(program)
    material_catalog=load_native_materials()
    material_dependencies=[]
    isaac_asset_root=Path(os.environ['SPATIALFORGE_ISAAC_ASSET_ROOT'])

    def textured_shape(path, kind, size, color, uv_scale_m, offset=(0,0,0), rotation_deg_xyz=(0,0,0)):
        return define_textured_primitive(stage,path,kind,size,color,uv_scale_m,offset,rotation_deg_xyz)

    def visual_material(prim, name, appearance, color=None, vertex_colors=False):
        texture_id=appearance.get('texture_id')
        texture_record=material_catalog.get(texture_id,{})
        material=UsdShade.Material.Define(stage,'/World/Materials/'+name)
        shader=UsdShade.Shader.Define(stage,str(material.GetPath())+'/Surface')
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(float(appearance.get('roughness',texture_record.get('roughness',.55))))
        shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(float(appearance.get('metallic',texture_record.get('metallic',0.))))
        dielectric=apply_dielectric_controls(shader,appearance)
        if dielectric['applied']:
            material_dependencies.append({'prim_path':str(prim.GetPath()),'kind':'dielectric_controls',**dielectric})
        if texture_id:
            if not texture_record:raise ValueError('unregistered native texture ID: '+texture_id)
            reader=UsdShade.Shader.Define(stage,str(material.GetPath())+'/UVReader');reader.CreateIdAttr('UsdPrimvarReader_float2')
            reader.CreateInput('varname',Sdf.ValueTypeNames.Token).Set('st')
            paths={}
            for slot,relative in texture_record['textures'].items():
                texture_path=(isaac_asset_root/relative).resolve()
                if not texture_path.is_relative_to(isaac_asset_root.resolve()) or not texture_path.is_file():
                    raise ValueError('registered native texture is missing or outside asset root: '+texture_id)
                paths[slot]=str(texture_path)
                texture=UsdShade.Shader.Define(stage,str(material.GetPath())+'/'+slot);texture.CreateIdAttr('UsdUVTexture')
                texture.CreateInput('file',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(texture_path)))
                texture.CreateInput('st',Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(),'result')
                texture.CreateInput('sourceColorSpace',Sdf.ValueTypeNames.Token).Set('sRGB' if slot=='base_color' else 'raw')
                texture.CreateInput('wrapS',Sdf.ValueTypeNames.Token).Set('repeat');texture.CreateInput('wrapT',Sdf.ValueTypeNames.Token).Set('repeat')
                if slot=='normal':
                    texture.CreateInput('scale',Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(2,2,2,1))
                    texture.CreateInput('bias',Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(-1,-1,-1,0))
                    shader.CreateInput('normal',Sdf.ValueTypeNames.Normal3f).ConnectToSource(texture.ConnectableAPI(),'rgb')
                else:
                    tint=apply_texture_tint(texture,appearance)
                    shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(),'rgb')
            material_dependencies.append({'prim_path':str(prim.GetPath()),'texture_id':texture_id,'paths':paths,'texture_tint':tint,
                                          'uv_scale_m':appearance.get('uv_scale_m',[1,1]),'uv_mapping':prim.GetCustomDataByKey('spatialforge_uv_mapping'),
                                          'source':texture_record.get('source'),'calibration':texture_record.get('calibration'),
                                          'normal_convention':texture_record.get('normal_convention'),'portability':'SceneProgram rebuild requires the Isaac texture library; exported USD resource copies and unresolved paths are recorded in report.scene_resources and report.scene_resources_unresolved'})
        elif vertex_colors:
            reader=UsdShade.Shader.Define(stage,str(material.GetPath())+'/Color')
            reader.CreateIdAttr('UsdPrimvarReader_float3')
            reader.CreateInput('varname',Sdf.ValueTypeNames.Token).Set('displayColor')
            shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).ConnectToSource(reader.ConnectableAPI(),'result')
        elif color is not None:shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)

    def add_missing_colliders(node, approximation):
        created=[]
        for child in Usd.PrimRange(node):
            if child.IsA(UsdGeom.Mesh):
                UsdPhysics.CollisionAPI.Apply(child)
                UsdPhysics.MeshCollisionAPI.Apply(child).CreateApproximationAttr(approximation)
                created.append(str(child.GetPath()))
        if not created:raise ValueError('asset has no mesh geometry for automatic collision preparation')
        return {'origin':'generated_collision_approximation','approximation':approximation,'paths':created,
                'cavity_preservation':{'convexDecomposition':'convex decomposition approximates cavities; no contact calibration','convexHull':'convex hull fills concavities','none':'static triangle mesh retains authored concavities'}.get(approximation,'unmeasured'),
                'calibrated':False}

    def generated_mesh(path, object_record):
        asset_id=object_record['asset_id']
        mesh_path=Path(job.get('asset_paths',{}).get(asset_id,''))
        if not mesh_path.is_file():raise ValueError('generated asset was not downloaded: '+asset_id)
        mesh_record=json.loads(mesh_path.read_text(encoding='utf8'))
        vertices=np.asarray(mesh_record['vertices'],dtype=np.float64)
        faces=np.asarray(mesh_record['faces'],dtype=np.int64)
        colors=np.asarray(mesh_record['colors'],dtype=np.float32)
        # Bind source factors and texture maps to their original face subsets.
        pbr=mesh_record.get('materials',[])
        if vertices.ndim!=2 or vertices.shape[1]!=3 or not np.isfinite(vertices).all():raise ValueError('invalid generated vertices')
        if faces.ndim!=2 or faces.shape[1]!=3 or not len(faces) or faces.min()<0 or faces.max()>=len(vertices):raise ValueError('invalid generated faces')
        if colors.shape!=vertices.shape or not np.isfinite(colors).all():raise ValueError('invalid generated vertex colors')
        frame=mesh_record.get('coordinate_frame')
        vertices,normalization=transform_mesh_geometry(vertices,object_record['size'],frame,object_record.get('mesh_transform'))
        actual_size=np.asarray(normalization['actual_size_m'])
        mesh=UsdGeom.Mesh.Define(stage,path+'/Geometry')
        mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(vertices.astype(np.float32)))
        mesh.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(np.full(len(faces),3,dtype=np.int32)))
        mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(faces.astype(np.int32).ravel()))
        mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        mesh.CreateDoubleSidedAttr(True)
        if mesh_record.get('normals'):
            normals=transform_mesh_normals(mesh_record['normals'],normalization['T_local_from_source'])
            mesh.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(normals.astype(np.float32)))
            mesh.SetNormalsInterpolation(mesh_record['normals_interpolation'])
        mesh.CreateExtentAttr([Gf.Vec3f(*(-actual_size/2)),Gf.Vec3f(*(actual_size/2))])
        mesh.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex).Set(Vt.Vec3fArray.FromNumpy(np.clip(colors,0,1)))
        material_receipt_start=len(material_dependencies)
        visual_material(mesh.GetPrim(),object_record['id']+'_surface',object_record.get('appearance',{}),vertex_colors=True)
        imported_appearance=bind_imported_materials(stage,mesh,mesh_record,mesh_path.parent,object_record['id'],object_record.get('appearance',{}))
        colliders=add_missing_colliders(mesh.GetPrim(),object_record.get('physics',{}).get('collider','convexDecomposition'))
        from spatialforge.gaussian_asset import render_representation
        representation=render_representation(object_record,mesh_record)
        gaussian_receipt=None
        if representation=='gaussian':
            from gaussian_visual import define_gaussian_visual
            gaussian_receipt=define_gaussian_visual(stage,path,mesh_path.parent/mesh_record['gaussian']['file'],mesh_record['gaussian'],normalization)
            mesh.MakeInvisible()
        appearance_scope={'visible_surface':'gaussian_radiance' if representation=='gaussian' else 'mesh_material',
                          'mesh_material_visibility':'hidden' if representation=='gaussian' else 'visible'}
        for receipt in imported_appearance['appearance_overrides']+material_dependencies[material_receipt_start:]:
            receipt['appearance_scope']=appearance_scope
        metadata_path=mesh_path.parent/'asset.json'
        metadata=json.loads(metadata_path.read_text(encoding='utf8')) if metadata_path.is_file() else {}
        return colliders,{'render_representation':representation,'gaussian':gaussian_receipt,'kind':'generated_mesh','asset_id':asset_id,'source_mesh':str(mesh_path),
                         'embedded_geometry':True,'vertices':len(vertices),'triangles':len(faces),
                         'source_frame':frame,'world_frame':'z_up',**normalization,
                         'source_watertight':mesh_record.get('watertight'),
                         'appearance':gaussian_receipt['appearance'] if gaussian_receipt else 'source material factors and PBR maps; vertex colors where present',
                         'appearance_scope':appearance_scope,
                         'transported_materials':len(pbr),'transported_uvs':len(mesh_record.get('texcoords',[]))==len(vertices),
                         'shading_normals':{'interpolation':mesh.GetNormalsInterpolation() if mesh_record.get('normals') else None,
                                            'count':len(mesh_record.get('normals',[])),
                                            'sources':mesh_record.get('normal_sources',[])},
                         **imported_appearance,
                         'generation_provenance':metadata}

    def physics_material(obj, object_record):
        p=object_record.get('physics',{})
        material=UsdShade.Material.Define(stage,'/World/Materials/'+object_record['id']+'_physics')
        physical=UsdPhysics.MaterialAPI.Apply(material.GetPrim())
        values={'static_friction':float(p.get('static_friction',.6)),
                'dynamic_friction':float(p.get('dynamic_friction',.5)),
                'restitution':float(p.get('restitution',.05))}
        physical.CreateStaticFrictionAttr(values['static_friction'])
        physical.CreateDynamicFrictionAttr(values['dynamic_friction'])
        physical.CreateRestitutionAttr(values['restitution'])
        UsdShade.MaterialBindingAPI.Apply(obj).Bind(material,UsdShade.Tokens.strongerThanDescendants,'physics')
        return {**values,'mass_kg':object_record['mass_kg'] if object_record['dynamic'] else None,
                'mass_source':'synthetic_prior','requested_mass_source':p.get('mass_source','synthetic_prior'),
                'material_source':'synthetic_prior','calibrated':False}

    # Ground is a placement origin. Visible and collidable terrain comes from
    # authored objects, including floors below zero and outdoor terrain.
    entities={};tops={};dynamic=[];dependencies=[]
    asset_root=isaac_asset_root/'Props'
    for o in objects_in_support_order(program['objects']):
        eid=o['id'];size=o['size'];base=o['base_z']+(tops[o['support']] if o['support']!='ground' else 0)
        center=[*o['xy'],base+size[2]/2]
        path='/World/Objects/'+eid
        obj=UsdGeom.Xform.Define(stage,path);xf=UsdGeom.Xformable(obj)
        yaw=o.get('yaw_deg',0)
        placement=xf.AddTranslateOp();placement.Set(Gf.Vec3d(*center));xf.AddRotateZOp().Set(yaw)
        sem=Semantics.SemanticsAPI.Apply(obj.GetPrim(),'Semantics');sem.CreateSemanticTypeAttr().Set('class');sem.CreateSemanticDataAttr().Set(eid)
        collider={'origin':'analytic_primitive','calibrated':False};dependency=None;part_materials=[]
        material=material_for(program,o);render_object={**o,'appearance':material['appearance'],'color':material['color']}
        if o['kind'] in {'box','sphere','cylinder'}:
            if material['appearance'].get('texture_id'):
                textured_shape(path+'/Geometry',o['kind'],size,material['color'],material['appearance'].get('uv_scale_m',[1,1]))
                collider={'origin':'textured_box_analytic_collider' if o['kind']=='box' else 'textured_primitive_convex_hull','calibrated':False}
            else:shape(path+'/Geometry',o['kind'],size,material['color'])
        elif o['kind']=='container':
            x,y,z=size;t=min(.015,x/8,y/8,z/8)
            parts=[([x,y,t],[0,0,-z/2+t/2]),([t,y,z],[-x/2+t/2,0,0]),([t,y,z],[x/2-t/2,0,0]),([x-2*t,t,z],[0,-y/2+t/2,0]),([x-2*t,t,z],[0,y/2-t/2,0])]
            for i,(s,off) in enumerate(parts):
                if material['appearance'].get('texture_id'):
                    textured_shape(path+f'/wall{i}','box',s,material['color'],material['appearance'].get('uv_scale_m',[1,1]),off)
                else:shape(path+f'/wall{i}','box',s,material['color'],off)
            if material['appearance'].get('texture_id'):
                collider={'origin':'textured_container_analytic_box_walls','calibrated':False}
        elif o['kind']=='composite':
            for i,p in enumerate(o['parts']):
                part_material=part_material_for(program,material,p);part_materials.append(part_material)
                appearance=part_material['appearance'];color=part_material['color']
                if appearance.get('texture_id'):
                    node=textured_shape(path+f'/part{i}',p['shape'],p['size'],color,appearance.get('uv_scale_m',[1,1]),p['offset'],p.get('rotation_deg_xyz',[0,0,0]))
                else:node=shape(path+f'/part{i}',p['shape'],p['size'],color,p['offset'],rotation_deg_xyz=p.get('rotation_deg_xyz',[0,0,0]))
                visual_material(node.GetPrim(),eid+'_surface_'+str(i+1),appearance,color)
            if any(m['appearance'].get('texture_id') for m in part_materials):
                collider={'origin':'analytic_primitives_and_textured_curved_part_convex_hulls','calibrated':False}
        elif o['kind']=='mesh':
            collider,dependency=generated_mesh(path,render_object)
            size=dependency['actual_size_m'];center=[*o['xy'],base+size[2]/2]
            placement.Set(Gf.Vec3d(*center))
        else:
            asset_spec=ASSETS[o['kind']]
            asset=(asset_root.parent if asset_spec.get('root')=='isaac' else asset_root)/asset_spec['path']
            if not asset.is_file():raise ValueError('registered desktop asset missing: '+o['kind'])
            node=UsdGeom.Xform.Define(stage,path+'/AssetNormalization')
            reference=UsdGeom.Xform.Define(stage,path+'/AssetNormalization/Source')
            reference.GetPrim().GetReferences().AddReference(str(asset))
            if asset_spec.get('source_up_axis','Z')=='Y':
                UsdGeom.Xformable(reference).AddRotateXOp(opSuffix='sourceUpAxis').Set(90.)
            cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render])
            bound=cache.ComputeLocalBound(node.GetPrim()).ComputeAlignedBox();ext=bound.GetSize();mid=(bound.GetMin()+bound.GetMax())/2
            if min(ext)<=1e-8:raise ValueError('registered asset has degenerate bounds')
            ratios=[size[i]/ext[i] for i in range(3)]
            nx=UsdGeom.Xformable(node);nx.AddTranslateOp().Set(Gf.Vec3d(*[-mid[i]*ratios[i] for i in range(3)]));nx.AddScaleOp().Set(Gf.Vec3f(*ratios))
            # Native asset colliders remain; remove nested body ownership and semantic labels.
            for child in Usd.PrimRange(node.GetPrim()):
                if child.HasAPI(UsdPhysics.RigidBodyAPI): child.RemoveAPI(UsdPhysics.RigidBodyAPI)
                for applied in list(child.GetAppliedSchemas()):
                    if applied.startswith('SemanticsAPI:'): child.RemoveAPI(Semantics.SemanticsAPI,applied.split(':',1)[1])
            native=[str(p.GetPath()) for p in Usd.PrimRange(node.GetPrim()) if p.HasAPI(UsdPhysics.CollisionAPI)]
            collider={'origin':'asset_native','paths':native,'calibrated':False} if native else add_missing_colliders(node.GetPrim(),'convexDecomposition' if o['dynamic'] else 'none')
            dependency={'kind':'registered_usd','asset_kind':o['kind'],'path':str(asset),'native_colliders_preserved':bool(native),
                        'source_up_axis':asset_spec.get('source_up_axis','Z'),'normalization_scale_xyz':ratios,'normalization':'centered and independently scaled to declared meter dimensions',
                        'portability':'SceneProgram rebuild requires the Isaac asset tree; exported USD contains composed geometry, with resource copies and unresolved paths recorded in report.scene_resources and report.scene_resources_unresolved'}
        if o['kind'] in ASSETS:
            overrides=apply_native_appearance(stage,obj.GetPrim(),material['appearance'])
            dependency['appearance_overrides']=overrides
            material_dependencies.extend({'entity_id':eid,'kind':'native_gloss_override',**item} for item in overrides)
        elif o['kind'] not in {'mesh','composite'}:
            for index,child in enumerate(Usd.PrimRange(obj.GetPrim())):
                if child.IsA(UsdGeom.Gprim):
                    display=UsdGeom.Gprim(child).GetDisplayColorAttr().Get()
                    color=list(display[0]) if display else material['color']
                    visual_material(child,eid+'_surface_'+str(index),material['appearance'],color)
        from object_shadows import apply_object_shadows
        shadow_settings=apply_object_shadows(obj.GetPrim(),o.get('cast_shadows'))
        physical=physics_material(obj.GetPrim(),render_object)
        if o['dynamic']:
            UsdPhysics.RigidBodyAPI.Apply(obj.GetPrim()).CreateRigidBodyEnabledAttr(True)
            UsdPhysics.MassAPI.Apply(obj.GetPrim()).CreateMassAttr(o['mass_kg']);dynamic.append(eid)
        tops[eid]=base+size[2]
        if dependency:dependencies.append({'entity_id':eid,**dependency})
        entities[eid]={'id':eid,'label':o['label'],'prim_path':path,'size':size,'requested_size':o['size'],'declared_yaw_deg':yaw,'initial_center':center,'support':o['support'],'dynamic':o['dynamic'],'parameter_origin':'synthetic_prior','kind':o['kind'],'physics':physical,'collision':collider,'appearance':material['appearance']}

        if shadow_settings:entities[eid]['shadow_settings']=shadow_settings
        if o['kind']=='mesh':
            entities[eid]['render_representation']=dependency['render_representation']
            entities[eid]['appearance_scope']=dependency['appearance_scope']
        if o['kind']=='composite':
            entities[eid]['geometry_parts']={
                'source':'executed_primitive_construction',
                'coordinate_frame':'entity_local_meters',
                'parts':[{'prim_path':path+f'/part{i}',
                          'usd_type':str(stage.GetPrimAtPath(path+f'/part{i}').GetTypeName()),
                          'appearance':part_materials[i]['appearance'],'color':part_materials[i]['color'],
                          'material_id':part_materials[i]['id'],
                          **{key:p[key] for key in ('shape','size','offset','rotation_deg_xyz') if key in p}}
                         for i,p in enumerate(o['parts'])]}

    def pose(e):
        matrix=UsdGeom.XformCache().GetLocalToWorldTransform(stage.GetPrimAtPath(e['prim_path']))
        p=matrix.ExtractTranslation();return [float(v) for v in p]

    def define_camera(path,c):
        camera=UsdGeom.Camera.Define(stage,path)
        matrix=camera_matrix(c)
        UsdGeom.Xformable(camera).AddTransformOp().Set(matrix)
        apply_camera_optics(camera,c);camera.CreateClippingRangeAttr(Gf.Vec2f(.01,100))
        if 'exposure' in render_config:
            camera.GetPrim().AddAppliedSchema('OmniRtxCameraExposureAPI_1')
            camera.GetPrim().CreateAttribute('exposure:iso',Sdf.ValueTypeNames.Float).Set(100.*2.**render_config['exposure'])
        return camera,matrix

    def capture_rgb(name,render_steps=5):
        def retain_rejected(rgb,diagnostic):
            if rgb is not None:
                image_path=output/name
                Image.fromarray(rgb.astype(np.uint8)).save(image_path.with_name('rejected_'+image_path.name))
        def reinitialize_rgb():
            # Isaac 6.0.1 can keep initial LdrColor all zero indefinitely until
            # a camera pose change dirties the render product. Prime once at a
            # temporary 1mm offset, then restore before any RGB/GT is sampled.
            original=Gf.Matrix4d(capture_camera_transform.Get())
            temporary=Gf.Matrix4d(original)
            temporary.SetTranslateOnly(original.ExtractTranslation()+Gf.Vec3d(.001,0,0))
            try:
                capture_camera_transform.Set(temporary)
                rep.orchestrator.step(rt_subframes=4,delta_time=0.,pause_timeline=True)
            finally:capture_camera_transform.Set(original)
        rgb,diagnostic=read_rgb_bounded(annot['rgb'].get_data,
            lambda:rep.orchestrator.step(rt_subframes=4,delta_time=0.,pause_timeline=True),
            (settings['height'],settings['width']),retain_rejected,reinitialize=reinitialize_rgb,render_steps=render_steps)
        diagnostic['temporary_camera_offset_m']=.001 if diagnostic['render_reinitialized'] else 0.
        report.setdefault('image_diagnostics',{})[name]=diagnostic
        if rgb is None:raise RuntimeError(f'{name}: invalid RGB buffer after bounded render warmup; see image_diagnostics')
        return rgb,diagnostic

    def interaction_rgb(name,object_id):
        rgb,diagnostic=capture_rgb(name)
        Image.fromarray(rgb.astype(np.uint8)).save(output/name)
        if not diagnostic['valid_rgb']:raise RuntimeError(f'{name}: RGB remains all zero after bounded render warmup; interaction evidence unavailable')
        visibility=object_visibility(annot['instance_segmentation'].get_data(),object_id,entities[object_id]['prim_path'],(settings['height'],settings['width']))
        return name,visibility

    def recording_for(index, action):
        if 'recording' not in action:return None
        from interaction_recording import InteractionRecording
        def frame(name):
            # Rendering freezes simulation time; resume the existing context
            # after saving this state, without replaying or moving the target.
            sim.pause()
            # The before image has initialized this persistent camera/product.
            # One complete rendering step samples the current physics state;
            # repeating startup warmup for every video frame wastes renders.
            rgb,_=capture_rgb(name,render_steps=1)
            Image.fromarray(rgb.astype(np.uint8)).save(output/name)
            sim.play()
        return InteractionRecording(output,index,action['recording'],settings['dt'],frame)

    rigid_views={};robots={};robot_views={};robot_witnesses={}
    if has_robot:
        from robot_contact import ContactRobot
        from isaacsim.core.prims import RigidPrim
        for action in actions:
            if action['action']!='robot_push':continue
            rid=action['robot_id']
            if rid not in robots:
                robots[rid]=ContactRobot(action,isaac_asset_root)
                dependencies.append({'kind':'robot_usd','robot_id':rid,'path':robots[rid].usd,
                                     'portability':'SceneProgram rebuild requires official Franka USD and resources; exported USD contains composed geometry, with resource copies and unresolved paths recorded in report.scene_resources and report.scene_resources_unresolved'})
            robot_views[action['id']]=robots[rid].view(action,entities)
            robot_witnesses[action['id']]={eid:RigidPrim(entities[eid]['prim_path'],name=action['id']+'_witness_'+eid,reset_xform_properties=False)
                                           for eid in action.get('witness_object_ids',[])}
    if any(action['supported'] for action in actions):
        from isaacsim.core.prims import RigidPrim
        for action in actions:
            if action['supported'] and action['action']=='apply_force' and action['object_id'] not in rigid_views:
                eid=action['object_id']
                rigid_views[eid]=RigidPrim(prim_paths_expr=entities[eid]['prim_path'],name='interaction_'+eid,reset_xform_properties=False)
    sim=SimulationContext(physics_dt=settings['dt'],rendering_dt=settings['dt'],stage_units_in_meters=1.)
    sim.initialize_physics();sim.play()
    for robot in robots.values():robot.initialize()
    for view in robot_views.values():view.initialize()
    for witnesses in robot_witnesses.values():
        for view in witnesses.values():view.initialize()
    for view in rigid_views.values():
        view.initialize()
        if not view.is_physics_handle_valid():raise RuntimeError('interaction rigid body physics handle unavailable')
    before={eid:pose(e) for eid,e in entities.items()}
    for _ in range(settings['steps']):sim.step(render=False)
    after={eid:pose(e) for eid,e in entities.items()}
    sim.pause()
    movement={eid:float(np.linalg.norm(np.array(before[eid])-np.array(after[eid]))) for eid in dynamic}
    report['physics']={'steps':settings['steps'],'dt':settings['dt'],'dynamic_entities':dynamic,'before':before,'after':after,'translation_m':movement,'stable':max(movement.values(),default=0)<.08,'test_kind':'dynamic_settling' if dynamic else 'static_scene','limitations':['settling check is separate from per-action interaction evidence','mass and contact material values are synthetic priors, not measured properties','convex decomposition can alter cavities and thin geometry; contact behavior requires task-specific calibration']}
    for eid in entities:entities[eid]['settled_center']=after[eid]
    simulation_step=settings['steps'];action_results=[]
    # Keep a single Hydra texture and annotator graph alive. Destroying and
    # recreating a product between interaction RGB and multimodal capture in
    # Isaac 6.0.1 can leave the LdrColor host buffer at zero while depth remains valid.
    capture_camera,_=define_camera('/World/CaptureCamera',program['cameras'][0])
    capture_camera_transform=UsdGeom.Xformable(capture_camera).GetOrderedXformOps()[0]
    product=rep.create.render_product(str(capture_camera.GetPath()),(settings['width'],settings['height']))
    annot={name:rep.AnnotatorRegistry.get_annotator(name) for name in ('rgb','distance_to_image_plane','semantic_segmentation','instance_segmentation')}
    for a in annot.values():a.attach([product])
    for ai,action in enumerate(actions):
        if not action['supported']:
            action_results.append({'id':action['id'],'action':action['action'],'status':'unsupported','success':False,'reason':action['reason']})
            continue
        if action['action']=='robot_push':
            center=robot_views[action['id']].get_world_poses()[0][0]
            action_camera=select_interaction_camera(program['cameras'],action,center)
            capture_camera_transform.Set(camera_matrix(action_camera));apply_camera_optics(capture_camera,action_camera)
            record,simulation_step=robots[action['robot_id']].run(action,robot_views[action['id']],robot_witnesses[action['id']],
                sim,settings['dt'],simulation_step,lambda phase:interaction_rgb(f'interaction_{ai}_{phase}.png',action['object_id']),
                recording=recording_for(ai,action),
                contact_positions=(lambda:{eid:pose(entities[eid]) for eid in action['contact_object_ids']}) if action.get('contact_object_ids') else None)
            record['visual_evidence'].update(camera={**action_camera,**camera_evidence(capture_camera,action_camera,camera_matrix(action_camera))},
                                              selection='explicit' if 'camera_id' in action else 'closest_view_direction')
            name=f'interaction_{ai}_trajectory.json'
            (output/name).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
            measured=record['metrics'];trajectory=record['trajectory']
            action_results.append({'id':action['id'],'action':'robot_push','object_id':action['object_id'],
                'status':'succeeded' if measured['success'] else 'failed',**measured,
                'before':trajectory[0],'after':trajectory[-1],'sample_count':len(trajectory),'trajectory_file':name,
                'before_image':record['before_image'],'after_image':record['after_image'],'visual_evidence':record['visual_evidence'],
                'robot':record['robot'],**({'recording':record['recording']} if 'recording' in record else {}),
                **({'object_contacts':{k:v for k,v in record['object_contacts'].items() if k!='trace'}} if 'object_contacts' in record else {})})
            continue
        view=rigid_views[action['object_id']]
        def record_state(force):
            positions,orientations=view.get_world_poses()
            return {'step':simulation_step,'timestamp_sim':simulation_step*settings['dt'],
                    'position':np.asarray(positions)[0].tolist(),'orientation_wxyz':np.asarray(orientations)[0].tolist(),
                    'linear_velocity_m_s':np.asarray(view.get_linear_velocities())[0].tolist(),
                    'applied_force_newtons':list(force)}
        # Observe unforced drift immediately before each action; do not reset poses or velocities.
        baseline=[record_state([0.,0.,0.])];sim.play()
        for _ in range(12):
            sim.step(render=False);simulation_step+=1;baseline.append(record_state([0.,0.,0.]))
        sim.pause()
        drift=max(float(np.linalg.norm(np.asarray(row['position'])-baseline[0]['position'])) for row in baseline)
        action_camera=select_interaction_camera(program['cameras'],action,baseline[-1]['position'])
        capture_camera_transform.Set(camera_matrix(action_camera))
        apply_camera_optics(capture_camera,action_camera)
        before_image,before_visibility=interaction_rgb(f'interaction_{ai}_before.png',action['object_id'])
        trajectory=[record_state([0.,0.,0.])];sim.play()
        recording=recording_for(ai,action)
        if recording:recording.sample(simulation_step,'before',{'position':trajectory[-1]['position']})
        for step in range(action['duration_steps']+action['observe_steps']):
            force=action['force_newtons'] if step<action['duration_steps'] else [0.,0.,0.]
            view.apply_forces(np.asarray([force],dtype=np.float32),is_global=True)
            sim.step(render=False);simulation_step+=1;trajectory.append(record_state(force))
            if recording:recording.sample(simulation_step,'force' if step<action['duration_steps'] else 'settle_after',{'position':trajectory[-1]['position']})
        sim.pause()
        measured=evaluate_force_trajectory(action,trajectory,drift)
        after_image,after_visibility=interaction_rgb(f'interaction_{ai}_after.png',action['object_id'])
        visual_evidence={'camera':{**action_camera,**camera_evidence(capture_camera,action_camera,camera_matrix(action_camera))},'selection':'explicit' if 'camera_id' in action else 'closest_view_direction',
                         'before':before_visibility,'after':after_visibility}
        trajectory_name=f'interaction_{ai}_trajectory.json'
        record={'schema':'spatialforge.interaction/v1','id':action['id'],'action':'apply_force','object_id':action['object_id'],
                'physics_backend':'Isaac PhysX','executor':'isaacsim.core.prims.RigidPrim.apply_forces',
                'force_frame':'world','force_application':'center of mass','dt':settings['dt'],
                'parameters':action,'baseline':baseline,'trajectory':trajectory,'metrics':measured,
                'before_image':before_image,'after_image':after_image,'visual_evidence':visual_evidence}
        if recording:record['recording']=recording.finish(simulation_step)
        (output/trajectory_name).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
        action_results.append({'id':action['id'],'action':'apply_force','object_id':action['object_id'],
                               'status':'succeeded' if measured['success'] else 'failed',**measured,
                               'before':trajectory[0],'after':trajectory[-1],'sample_count':len(trajectory),
                               'trajectory_file':trajectory_name,'before_image':before_image,'after_image':after_image,
                               'visual_evidence':visual_evidence,**({'recording':record['recording']} if recording else {})})
    interaction={'validated':bool(action_results) and all(row['success'] for row in action_results),
                 'test_kind':'external_force_response','action_results':action_results,
                 'evidence_source':'Isaac physics states and rendered before/after images',
                 'limitations':['external force response; no robot, grasp or contact-manipulation success is claimed',
                                'synthetic contact parameters are uncalibrated; sim2real gap is not measured']}
    if not actions:interaction['reason']='no executable interaction requested'
    if has_robot:
        interaction['test_kind']='robot_contact' if all(a['action']=='robot_push' for a in actions) else 'mixed_physics_actions'
        interaction['limitations']=['Franka joint-driven contact; no grasp or calibrated real-world dynamics claim',
                                   'synthetic mass/friction and mesh collision approximation; sim2real gap is not measured']
    report['interaction']=interaction;report['physics']['total_steps']=simulation_step
    # Measure final geometry once, after interactions. Declared local dimensions
    # alone cannot describe a rotated object's world footprint or clearances.
    final_xforms=UsdGeom.XformCache(Usd.TimeCode.Default())
    final_bounds=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render])
    for entity in entities.values():
        prim=stage.GetPrimAtPath(entity['prim_path'])
        transform=final_xforms.GetLocalToWorldTransform(prim)
        rotation=transform.ExtractRotationQuat().GetNormalized()
        box=final_bounds.ComputeWorldBound(prim).ComputeAlignedBox()
        entity.update(final_center=[float(v) for v in transform.ExtractTranslation()],
                      world_transform=[[float(value) for value in row] for row in transform],
                      world_transform_convention='USD row-vector matrix; translation in last row; local to world meters',
                      orientation_wxyz=[float(rotation.GetReal()),*[float(v) for v in rotation.GetImaginary()]],
                      world_aabb={'min':[float(v) for v in box.GetMin()],'max':[float(v) for v in box.GetMax()],
                                  'extent':[float(v) for v in box.GetSize()],'kind':'conservative_geometry_extent',
                                  'limitations':'AABB overlap does not prove mesh intersection; clearance is not contact-tested'},
                      spatial_evidence_step=simulation_step)
    captures=[]
    for ci in scope['view_indices']:
        c=program['cameras'][ci]
        # Keep the camera target identity unchanged too. On this Isaac build,
        # switching Product.camera targets can invalidate only the RGB buffer.
        matrix=camera_matrix(c);capture_camera_transform.Set(matrix);apply_camera_optics(capture_camera,c)
        rgb,_=capture_rgb(f'view_{ci}.png')
        depth=np.asarray(annot['distance_to_image_plane'].get_data()).squeeze()
        semantic=annot['semantic_segmentation'].get_data();inst=annot['instance_segmentation'].get_data()
        masks=np.asarray(semantic['data']);masks=masks.view(np.uint32).reshape((settings['height'],settings['width'])) if masks.dtype==np.uint8 else masks.squeeze()
        info=semantic.get('info',{});mapping=info.get('idToLabels',{})
        name=f'view_{ci}';Image.fromarray(rgb.astype(np.uint8)).save(output/f'{name}.png')
        np.save(output/f'{name}_depth.npy',depth);np.save(output/f'{name}_semantic.npy',masks)
        np.save(output/f'{name}_instance.npy',np.asarray(inst['data']))
        objects=[]
        for eid,e in entities.items():
            region=instance_region(inst,e['prim_path'],(settings['height'],settings['width']));ys,xs=np.where(region)
            if len(xs)<30:continue
            z=depth[region];z=z[np.isfinite(z)&(z>0)]
            objects.append({'object_id':eid,'label':e['label'],'bbox_2d':{'xyxy':[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]},'mask':{'area_px':len(xs)},'confidence':{'value':1.},'valid_for_question_generation':True,'depth_z_median':float(np.median(z)) if len(z) else None})
        quality=assess_view(rgb,depth,objects)
        meta={'frame_id':name,'image':f'{name}.png','step_id':simulation_step,'timestamp_sim':simulation_step*settings['dt'],'image_size':{'width':settings['width'],'height':settings['height']},'objects':objects,'camera':camera_evidence(capture_camera,c,matrix),'semantic_info':info,'instance_info':inst.get('info',{}),'depth_kind':'optical_axis_z_m','rgb_std':quality['rgb_std'],'quality':quality}
        (output/f'{name}.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8');captures.append(meta)
    for a in annot.values():a.detach([product])
    product.destroy()
    if scope['scene_export_requested']:
        report.update(export_scene(stage,output))
    (output/'program.json').write_text(json.dumps(program,ensure_ascii=False,indent=2),encoding='utf8')
    evidence={'schema':'spatialforge.evidence/v1','truth_domain':'synthetic_world','origin':'isaac_native','entities':entities,'frames':captures,'token':job['token'],'physics':report['physics'],'asset_dependencies':dependencies,'material_dependencies':material_dependencies,'space_dependencies':room_dependencies,'declared_interaction':program.get('interactions',program.get('affordances',[])),'interaction':interaction,'render_settings':report['render_settings'],'realism':{'mass_and_contact_properties':'uncalibrated synthetic priors','appearance':'native texture appearance priors, native materials or generated colors; reflectance is not measured','sim2real_gap':'not measured'}}
    evidence['environment_dependencies']=environment_dependencies
    evidence['light_receipts']=report['light_receipts']
    evidence['capture_scope']=scope
    (output/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    report.update(status='captured',frames=len(captures),visible_counts=[len(f['objects']) for f in captures],renderable=all(f['quality']['passed'] for f in captures),render_qa={'passed':all(f['quality']['passed'] for f in captures),'failed_views':[{'frame_id':f['frame_id'],'reasons':f['quality']['reasons']} for f in captures if not f['quality']['passed']]},source_fidelity='not_applicable_programmatic_composition',asset_dependencies=dependencies,material_dependencies=material_dependencies,environment_dependencies=environment_dependencies,realism=evidence['realism'])
    report['render_qa']['assessed']=bool(captures)
    if not captures:
        report['renderable']=None
        report['render_qa']['passed']=None
    code=0
except Exception as exc:
    report['errors'].append(repr(exc));traceback.print_exc()
finally:
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    app.close()
raise SystemExit(code)
