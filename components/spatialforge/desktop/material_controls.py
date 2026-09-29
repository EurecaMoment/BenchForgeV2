"""Scene dielectric controls for USD PreviewSurface's metallic workflow."""
import math
from pxr import Gf,Sdf


def apply_texture_tint(texture, appearance):
    """Tint decoded base color only; leave the source texture intact."""
    tint=list(appearance.get('texture_tint',[1.,1.,1.]))
    if 'texture_tint' in appearance:
        texture.CreateInput('scale',Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*tint,1.))
    return tint


def apply_dielectric_controls(shader, appearance):
    requested={key:appearance[key] for key in ('ior','specular') if key in appearance}
    if not requested:return {'applied':[],'skipped':[]}
    source=shader.GetInput('ior')
    workflow=shader.GetInput('useSpecularWorkflow')
    if (source and source.HasConnectedSource()) or (workflow and workflow.Get()==1):
        return {'applied':[], 'skipped':[{'field':key,'reason':'native connected IOR or specular-color workflow preserved'} for key in requested]}
    source_ior=source.Get() if source else None
    ior=float(appearance.get('ior',source_ior if source_ior is not None else 1.5))
    level=float(appearance.get('specular',.5))
    f0=((ior-1)/(ior+1))**2 * (2*level)
    effective_ior=ior if level==.5 else (1+math.sqrt(f0))/(1-math.sqrt(f0))
    shader.CreateInput('ior',Sdf.ValueTypeNames.Float).Set(effective_ior)
    return {'applied':[{'field':key,'value':value,'input':'ior','authored_ior':effective_ior,
                       'dielectric_f0':f0,'reference_ior':ior,'specular_level':level,
                       'origin':'scene_appearance','shader':str(shader.GetPath()),
                       'meaning':'dielectric Fresnel F0 scaled by 2*specular; metallic workflow retained'}
                      for key,value in requested.items()], 'skipped':[]}
