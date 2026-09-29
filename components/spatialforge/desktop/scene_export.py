"""Export the composed scene and its image/MDL resources beside the entry."""
import os
from pathlib import Path
import re
import shutil
from pxr import Ar, Sdf, UsdUtils


IMAGE_SUFFIXES={'.png','.jpg','.jpeg','.hdr','.exr','.tif','.tiff','.webp','.bmp','.dds','.tga','.tx'}


def export_scene(stage, output):
    root=stage.GetRootLayer()
    exported=stage.Flatten()
    resources={};unresolved=[]

    def localize(asset_path, anchor=None):
        suffix=Path(asset_path).suffix.lower()
        if suffix not in IMAGE_SUFFIXES | {'.mdl'}:return asset_path
        anchored=str(anchor/asset_path) if anchor else Sdf.ComputeAssetPathRelativeToLayer(root,asset_path)
        resolved=str(Ar.GetResolver().Resolve(anchored))
        if not resolved or not Path(resolved).is_file():
            if asset_path not in unresolved:unresolved.append(asset_path)
            return asset_path
        source=Path(resolved).resolve();key=os.path.normcase(str(source))
        if key not in resources:
            name=f'scene_resource_{len(resources):03d}{suffix}'
            resources[key]={'file':name,'source':str(source)}
            if suffix=='.mdl':
                text=source.read_text(encoding='utf8')
                # Native Office MDL modules import local symbols and contain
                # texture defaults outside USD's asset dependency graph.
                def module_import(match):
                    path=match[2].replace('::','/')+'.mdl'
                    name=localize(path,source.parent)
                    return match[1]+Path(name).stem+match[3]
                text=re.sub(r'(using\s+\.::)([\w:]+)(\s+import)',module_import,text)
                def texture(match):
                    return match[1]+localize(match[2],source.parent)+match[3] if match[2] else match[0]
                text=re.sub(r'(texture_2d\(\s*")([^"]*)(")',texture,text)
                (output/name).write_text(text,encoding='utf8')
            else:
                shutil.copy2(source,output/name)
        return resources[key]['file']

    # Flatten resolves referenced USD geometry without modifying the live stage.
    # USD handles resource defaults, arrays and time samples in the composed copy.
    UsdUtils.ModifyAssetPaths(exported,localize)
    exported.Export(str(output/'scene.usdc'))
    entry=Sdf.Layer.CreateNew(str(output/'scene.usda'))
    for key in exported.pseudoRoot.ListInfoKeys():
        if key not in {'subLayers','subLayerOffsets'}:
            entry.pseudoRoot.SetInfo(key,exported.pseudoRoot.GetInfo(key))
    entry.subLayerPaths=['scene.usdc']
    entry.Save()
    return {'scene_file':'scene.usda','scene_payload':'scene.usdc','scene_format':'usdc',
            'scene_resources':list(resources.values()),'scene_resources_unresolved':unresolved,
            'scene_resource_scope':'composed USD; images and local MDL using-imports/texture_2d defaults',
            'scene_runtime_requirements':['MDL renderer and standard modules', 'Isaac/PhysX for simulation']}
