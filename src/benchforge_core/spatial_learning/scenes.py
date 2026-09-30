"""Shared world state for rendering, questions, oracles and interactive episodes."""
import math
import random

COLORS={'red':'#c94842','blue':'#356bb1','green':'#438763','orange':'#d88a30','purple':'#815b9d','teal':'#32898e','brown':'#967047','pink':'#c5779c','black':'#333333'}
SHAPES=['rectangle','ellipse','triangle','pentagon','hexagon','cross','ring','arrow']


def rotate(p, degrees):
    a=math.radians(degrees);c,s=math.cos(a),math.sin(a)
    return [c*p[0]-s*p[1],s*p[0]+c*p[1]]


def bbox(o):
    x,y=o['position'];w,h=o['size']
    return [x-w/2,y-h/2,x+w/2,y+h/2]


def create_scene(template, seed, difficulty=1, group=None):
    rng=random.Random(seed);profile=template['scene_profile'];family=template['scene_family']
    count=min(8,4+difficulty+rng.randrange(2))
    objects=[];shape_order=rng.sample(SHAPES,len(SHAPES));color_order=rng.sample(list(COLORS),len(COLORS))
    for i in range(count):
        if profile=='grid':pos=[1.5+(i%3)*3.2,2+(i//3)*3]
        elif profile=='ring':pos=[5+3.4*math.cos(i*2*math.pi/count),5+3.4*math.sin(i*2*math.pi/count)]
        elif profile=='clusters':pos=[(2.5 if i%2 else 7.5)+rng.uniform(-1,1),2+i/(count-1)*6]
        elif profile=='corridor':pos=[2+i/(count-1)*6,5+rng.uniform(-.4,.4)]
        elif profile=='row':pos=[1+i/(count-1)*8,4+(i%2)*1.8]
        elif profile=='staircase':pos=[1.2+i/(count-1)*7.5,1.3+i/(count-1)*7.3]
        else:pos=[rng.uniform(1,9),rng.uniform(1,9)]
        size=[rng.uniform(.45,1.15),rng.uniform(.45,1.15)]
        objects.append({'id':f'object_{i}','label':f'{color_order[i%8]} {shape_order[i%8]}',
            'color':color_order[i%8],'shape':shape_order[i%8],'position':pos,'size':size,
            'heading':rng.choice([0,30,45,60,90,120,180,225,270,315]),'mass':round(rng.uniform(.2,3),2)})
    if profile=='nested':
        objects[0].update(position=[5,5],size=[4,4]);objects[1].update(position=[5.3,5.2],size=[.8,.8])
    if profile=='touching':
        objects[0].update(position=[3,4],size=[2,2]);objects[1].update(position=[5,4],size=[2,2])
    if profile=='distractors':
        for i in range(2,len(objects)):objects[i]['shape']='rectangle'
    # Profile topology stays recognizable while metric layout, labels and query
    # roles vary independently. A template cannot memorize object_0 at a corner.
    scale=rng.uniform(.55,.85);shift=[rng.uniform(-.5,.5),rng.uniform(-.5,.5)]
    mirror=[rng.choice([-1,1]),rng.choice([-1,1])]
    for obj in objects:
        obj['position']=[5+mirror[j]*scale*(obj['position'][j]-5)+shift[j] for j in range(2)]
        obj['size']=[s*scale for s in obj['size']]
        if rng.random()<.35:obj['shape']=rng.choice(SHAPES)
    rng.shuffle(objects)
    for i,obj in enumerate(objects):
        obj['id']=f'object_{i}';obj['label']=obj['color']+' '+obj['shape']
    nid=template['primary_capabilities'][0]
    if nid in ['N01','N02','N03','N04','N05','N06','N07','N09','N10','N11','N14','N18']:
        # Pack large silhouettes first, selecting the nearest free position.
        # Full-shape questions cannot depend on hidden geometry.
        placed=[]
        for obj in sorted(objects,key=lambda o:o['size'][0]*o['size'][1],reverse=True):
            w,h=obj['size'];original=obj['position']
            candidates=[original]+sorted([[.5+w/2+x*(9-w)/18,.5+h/2+y*(9-h)/18] for x in range(19) for y in range(19)],key=lambda p:math.dist(p,original))
            obj['position']=next(p for p in candidates if all(abs(p[0]-other['position'][0])>=(w+other['size'][0])/2+.2 or abs(p[1]-other['position'][1])>=(h+other['size'][1])/2+.2 for other in placed))
            placed.append(obj)
    # Balance pair relations by construction, independent of the surrounding
    # scene profile. Full rectangular silhouettes remain observable.
    pair_case=seed%5
    if template['primary_capabilities'][0] in ['N08','N12','N13','N16','N20']:
        first,second=objects[:2];first['shape']=second['shape']='rectangle'
        first['position']=[rng.uniform(3,6),rng.uniform(3,6)]
        if pair_case==0:
            second['position']=[first['position'][0]+3,first['position'][1]+2]
        elif pair_case==1:
            second['position']=[first['position'][0]+(first['size'][0]+second['size'][0])/2,first['position'][1]]
        elif pair_case==2:
            second['position']=[first['position'][0]+first['size'][0]*.4,first['position'][1]]
        elif pair_case==3:
            second['position']=first['position'][:];second['size']=[s*2.5 for s in first['size']]
        else:
            second['position']=first['position'][:];second['size']=[s*.3 for s in first['size']]
    if template['primary_capabilities'][0]=='N07':
        objects[1]['heading']=(objects[0]['heading']+rng.choice([0,90,180,270,30,60]))%360
    if template['primary_capabilities'][0]=='N03' and rng.random()<.5:objects[1]['shape']=objects[0]['shape']
    if nid in ['N04','N05','N14','N18']:
        # Moving foreground stays in the central band; static references are
        # visible around it, so later frames cannot hide the tracked target.
        for i,obj in enumerate(objects[1:]):
            obj['position']=[1.1+i*1.1,1.0];obj['size']=[.45,.45]
        objects[0]['size']=[.55,.55]
    p=[rng.uniform(1.5,4),rng.uniform(1.5,4)];v=[rng.uniform(.25,.65),rng.uniform(-.4,.4)]
    a=[rng.uniform(-.12,.12),rng.uniform(-.12,.12)]
    if profile=='accelerating':a=[.12,.08]
    if profile=='decelerating':a=[-v[0]/6,-v[1]/6]
    # Predictive tasks receive the physical law explicitly. Profiles vary the
    # law's parameters and boundary conditions as well as the rendered path.
    if profile=='linear':a=[0,0]
    elif profile=='turning':v=[0,abs(v[0])]
    elif profile=='reversal':v=[-abs(v[0]),v[1]];a=[.25,0]
    elif profile=='stop_start':v=[0,0]
    elif profile=='orbit':v=[-.5,.5];a=[-.1,-.1]
    elif profile=='zigzag':v=[v[0],-abs(v[1])]
    elif profile=='camera_motion':p=[p[1],p[0]];a=[0,0]
    elif profile=='two_targets':v=[-v[0],-v[1]]
    start=rng.randint(0,4);interval=rng.choice([.5,1,1.5]);times=[start+i*interval for i in range(3+difficulty+rng.randrange(2))]
    positions=[]
    for t in times:
        point=[p[j]+t*v[j]+.5*a[j]*t*t for j in range(2)]
        if profile=='reversal' and t>1.5:point=[p[j]+(3-t)*v[j] for j in range(2)]
        if profile=='stop_start' and t in [1,2]:point=[p[j]+v[j] for j in range(2)]
        if profile=='orbit':point=[5+2*math.cos(t*.4),5+2*math.sin(t*.4)]
        if profile=='zigzag':point[1]+=(-1)**len(positions)*.5
        if profile=='turning' and t>1:point=[p[0]+v[0],p[1]+v[1]+(t-1)*abs(v[0])]
        positions.append(point)
    # Apply an independently sampled sequence treatment, so event questions
    # cannot infer the answer from a profile name or a fixed motion direction.
    if rng.random()<.5:positions.reverse()
    if rng.random()<.25:
        mid=len(positions)//2
        positions=positions[:mid+1]+[positions[max(0,mid-i-1)][:] for i in range(len(positions)-mid-1)]
    if rng.random()<.18:positions=[positions[0][:] for _ in positions]
    elif rng.random()<.25:positions[1]=positions[0][:]
    for axis in range(2):
        lo=min(p[axis] for p in positions);hi=max(p[axis] for p in positions)
        if hi-lo>4:
            for point in positions:point[axis]=3+4*(point[axis]-lo)/(hi-lo)
        else:
            translation=rng.uniform(3-lo,7-hi)
            for point in positions:point[axis]+=translation
    node_count=5+difficulty
    graph_profile=profile
    if family=='execution':graph_profile={'reliable':'chain','rotation_failure':'ring','grasp_failure':'star','blocked_route':'disconnected',
        'reordered_goals':'directed','limited_budget':'weighted_detour','symmetry':'diamond','distractor':'grid','delayed_feedback':'tree','multi_stage':'bridge'}[profile]
    nodes=[f'P{i}' for i in range(node_count)];pairs=[]
    if graph_profile=='star':pairs=[(0,i) for i in range(1,node_count)]
    elif graph_profile=='tree':pairs=[((i-1)//2,i) for i in range(1,node_count)]
    elif graph_profile=='grid':pairs=[(i,j) for i in range(node_count) for j in range(i+1,node_count) if j-i==3 or j-i==1 and i//3==j//3]
    elif graph_profile=='diamond':pairs=[(0,1),(0,2),(1,3),(2,3)]+[(i,i+1) for i in range(3,node_count-1)]
    elif graph_profile=='disconnected':pairs=[(i,i+1) for i in range(node_count-2)]
    else:pairs=[(i,i+1) for i in range(node_count-1)]
    if graph_profile in ['ring','weighted_detour','bridge']:pairs.append((0,node_count-1))
    if rng.random()<.5 and (0,node_count-1) not in pairs:pairs.append((0,node_count-1))
    elif rng.random()<.3 and len(pairs)>node_count-1:pairs.pop()
    edges=[{'a':nodes[i],'b':nodes[j],'cost':rng.randint(1,6),'width':rng.choice([.45,.65,.9,1.2]),'open':True} for i,j in pairs]
    if graph_profile=='weighted_detour':edges[-1].update(cost=1,width=.45)
    if graph_profile=='diamond':
        for e in edges:e.update(cost=2,width=1.2)
    start_node,goal_node=rng.sample(nodes,2)
    camera_translation=[rng.uniform(-.2,.2),rng.uniform(-.2,.2)];camera_rotation=rng.choice([-10,-5,5,10])
    camera_law='constant'
    if profile=='linear':camera_rotation=0
    elif profile=='accelerating':camera_law='accelerating'
    elif profile=='decelerating':camera_law='decelerating'
    elif profile=='turning':camera_translation=[0,0]
    elif profile=='reversal':camera_law='reversal'
    elif profile=='stop_start':camera_law='stop_start'
    elif profile=='orbit':camera_translation=[0,0];camera_rotation*=2
    elif profile=='zigzag':camera_law='zigzag'
    elif profile=='camera_motion':camera_rotation=-camera_rotation
    elif profile=='two_targets':camera_translation=[camera_translation[1],camera_translation[0]]
    camera_poses=[]
    for i,t in enumerate(times):
        f=(t-times[0]);duration=times[-1]-times[0]
        if camera_law=='accelerating':f=f*f/duration
        elif camera_law=='decelerating':f=2*f-f*f/duration
        elif camera_law=='reversal':f=min(f,duration-f)
        elif camera_law=='stop_start':f=max(0,f-duration/3)
        x,y=[f*v for v in camera_translation]
        if camera_law=='zigzag':y+=(i%2)*.2
        camera_poses.append([x,y,f*camera_rotation])
    # Preserve each graph family but vary endpoint roles and metric constraints.
    # A disconnected graph can still contain a reachable queried pair.
    # Structure and source seed are explicit. All questions about a base world
    # share this group, even when renderer, query, or language changes.
    return {'schema':'benchforge.spatial_world/v1','group':group or f'{family}/{profile}/{seed}',
        'seed':seed,'profile':profile,'difficulty':difficulty,'extent':[10,10],
        'pixel_size':[640,640],'objects':objects,'target_id':'object_0','reference_id':'object_1','category':rng.choice(SHAPES),
        'motion':{'times':times,'positions':positions,'initial':p,'velocity':v,'acceleration':a,
                  'camera_translation':camera_translation,'camera_rotation':camera_rotation,'camera_poses':camera_poses,'prediction_t':rng.choice([2,3,4]),'law':profile},
        'transform':{'angle':rng.choice([-135,-90,-45,30,60,90,135]),'origin':[rng.uniform(-2,2),rng.uniform(-2,2)]},
        'gravity_angle':rng.choice([-120,-90,-60,-30,0,30,60,90,120,150,180]),
        'graph':{'nodes':nodes,'edges':edges,'directed':graph_profile=='directed','start':start_node,'goal':goal_node,
                 'body_width':.6,'budget':12,'waypoint':nodes[min(2,node_count-1)]},
        'episode':{'profile':profile,'part_position':[1,0],'slot_position':[2,0],
                   'part_angle':rng.choice([30,60,90,120,180]),'slot_angle':0,'symmetry':180 if profile=='symmetry' else 360,
                   'budget':18+2*difficulty,'failure':profile if 'failure' in profile else None}}


def render(scene, path, frame=None, hide_labels=False):
    """Metric synthetic diagram. Geometry is private; pixels are the observation."""
    from PIL import Image,ImageDraw
    image=Image.new('RGB',scene['pixel_size'],'#f4f2ed');d=ImageDraw.Draw(image)
    scale=60;offset=20
    for i in range(11):
        x=offset+i*scale;d.line((x,offset,x,620),fill='#dfdcd5');d.line((offset,x,620,x),fill='#dfdcd5')
        d.text((x+2,4),str(i),fill='#554f49');d.text((2,x),str(i),fill='#554f49')
    if frame is not None:d.text((25,625),f't = {scene["motion"]["times"][frame]} s',fill='#222222')
    for i,obj in enumerate(scene['objects']):
        o=dict(obj)
        if frame is not None and i==0:o['position']=scene['motion']['positions'][frame]
        x0,y0,x1,y1=[offset+x*scale for x in bbox(o)]
        color=COLORS[o['color']];cx,cy=(x0+x1)/2,(y0+y1)/2;rx,ry=(x1-x0)/2,(y1-y0)/2
        shape=o['shape']
        if shape=='rectangle':d.rectangle((x0,y0,x1,y1),fill=color,outline='#292722',width=2)
        elif shape in ['ellipse','ring']:
            d.ellipse((x0,y0,x1,y1),fill=color,outline='#292722',width=2)
            if shape=='ring':d.ellipse((cx-rx*.55,cy-ry*.55,cx+rx*.55,cy+ry*.55),fill='#f4f2ed')
        elif shape in ['triangle','pentagon','hexagon','diamond']:
            n={'triangle':3,'pentagon':5,'hexagon':6,'diamond':4}[shape]
            vertices=[(math.cos(k*2*math.pi/n-math.pi/2),math.sin(k*2*math.pi/n-math.pi/2)) for k in range(n)]
            lo=[min(v[j] for v in vertices) for j in range(2)];hi=[max(v[j] for v in vertices) for j in range(2)]
            d.polygon([(x0+(x-lo[0])/(hi[0]-lo[0])*(x1-x0),y0+(y-lo[1])/(hi[1]-lo[1])*(y1-y0)) for x,y in vertices],fill=color,outline='#292722')
        elif shape=='cross':
            d.rectangle((cx-rx*.3,y0,cx+rx*.3,y1),fill=color);d.rectangle((x0,cy-ry*.3,x1,cy+ry*.3),fill=color)
        else:
            points=[(-1,-.38),(.2,-.38),(.2,-1),(1,0),(.2,1),(.2,.38),(-1,.38)]
            d.polygon([(cx+x*rx,cy+y*ry) for x,y in points],fill=color)
        # An explicit heading marker makes otherwise symmetric objects observable.
        dx,dy=rotate([min(rx,ry)*.8,0],o['heading'])
        d.line((cx,cy,cx+dx,cy+dy),fill='white',width=3);d.ellipse((cx+dx-2,cy+dy-2,cx+dx+2,cy+dy+2),fill='black')
    # Labeled wireframes make every queried bounding rectangle observable even
    # in containment scenes. Labels belong to the rectangle, not its draw order.
    if not hide_labels:
        for i,obj in enumerate(scene['objects']):
            x0,y0,x1,y1=[offset+x*scale for x in bbox(obj)]
            if scene.get('show_bounds'):d.rectangle((x0,y0,x1,y1),outline=COLORS[obj['color']],width=1)
            label=str(i);lx=x0;ly=max(20,y0-13)
            d.rectangle((lx-1,ly-1,lx+9,ly+11),fill='white')
            d.text((lx,ly),label,fill='#222222')
    if scene.get('show_gravity'):
        dx,dy=rotate([0,45],scene['gravity_angle']);d.line((565,75,565+dx,75+dy),fill='#222222',width=3)
        d.ellipse((561,71,569,79),fill='#222222');d.ellipse((558+dx,68+dy,572+dx,82+dy),fill='#9b8042')
        d.text((485,20),'fixed pin + plumb bob',fill='#222222')
    image.save(path)
    return image
