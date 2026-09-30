"""Graph truth and equivalent-path scoring, including unreachable goals."""
import heapq
import math
from .geometry_tasks import result


def adjacency(graph, feasible=False, avoid=()):
    adj={n:[] for n in graph['nodes'] if n not in avoid}
    for e in graph['edges']:
        if e['a'] not in adj or e['b'] not in adj:continue
        if feasible and (not e['open'] or e['width']<graph['body_width']):continue
        adj[e['a']].append((e['b'],e['cost']))
        if not graph['directed']:adj[e['b']].append((e['a'],e['cost']))
    return adj


def shortest(graph,start=None,goal=None,feasible=True,avoid=()):
    start=start or graph['start'];goal=goal or graph['goal'];adj=adjacency(graph,feasible,avoid)
    if start not in adj or goal not in adj:return None,None
    queue=[(0,[start])];best={start:0}
    while queue:
        cost,path=heapq.heappop(queue);node=path[-1]
        if node==goal:return path,cost
        if cost>best[node]:continue
        for n,weight in adj[node]:
            candidate=cost+weight
            if candidate<best.get(n,math.inf):
                best[n]=candidate;heapq.heappush(queue,(candidate,path+[n]))
    return None,None


def path_cost(graph,path,feasible=True):
    if not isinstance(path,list) or not path:return None
    adj=adjacency(graph,feasible);total=0
    for a,b in zip(path,path[1:]):
        candidates=[weight for n,weight in adj.get(a,[]) if n==b]
        if not candidates:return None
        total+=min(candidates)
    return total


def reachable(graph,start,feasible=False):
    adj=adjacency(graph,feasible);seen=set();todo=[start]
    while todo:
        node=todo.pop()
        if node in seen:continue
        seen.add(node);todo.extend(n for n,_ in adj[node])
    return sorted(seen)


def task(scene,nid,op):
    g=scene['graph'];start,goal=g['start'],g['goal'];adj=adjacency(g);route,cost=shortest(g)
    edge_list=sorted([e['a'],e['b']] for e in g['edges'])
    inputs={'directed':g['directed'],'start':start,'goal':goal,'body_width':g['body_width'],'budget':g['budget']}
    if nid=='N17':
        # Distributed local observations are provided separately. Never supply
        # the already integrated graph as this capability's input.
        inputs['visits']=[{'node':node,'outgoing':[{'to':n,'cost':c} for n,c in adj[node]]} for node in reversed(g['nodes'])]
        components=[];remaining=set(g['nodes'])
        while remaining:
            group=reachable(g,min(remaining));components.append(group);remaining-=set(group)
        plain_route,plain_cost=shortest(g,feasible=False)
        values={'edges':('Integrate visits and return directed pairs (undirected edges once in sorted order).',edge_list),
          'adjacency':('Return {node: sorted neighboring IDs} from the visits.',{n:sorted(v for v,_ in links) for n,links in adj.items()}),
          'neighbors':(f'Which nodes are directly reachable from {start}?',sorted(n for n,_ in adj[start])),
          'degree':(f'How many outgoing neighbors does {start} have?',len(adj[start])),
          'components':('Return reachability groups by repeatedly taking the lowest unseen node and all nodes it can reach.',components),
          'reachable':(f'Give all nodes reachable from {start}, including itself.',reachable(g,start)),
          'shortest_cost':('What is minimum start-goal cost, ignoring body width? null if unreachable.',plain_cost),
          'cycle':('Does the integrated graph contain a directed cycle, or an undirected cycle for undirected input?',has_cycle(g)),
          'has_edge':(f'Is there a direct edge from {start} to {goal}?',any(n==goal for n,_ in adj[start])),
          'missing_link':(f'Which nodes other than {start} have no outgoing edge from {start}?',sorted(set(g['nodes'])-{start}-{n for n,_ in adj[start]})),
          'route':('Return minimum-cost start-goal route, ignoring body width; null if unreachable.',plain_route),
          'integrated_map':('Return integrated weighted adjacency {node:[[neighbor,cost],...]}, sorting neighbors.',{n:sorted([v,c] for v,c in links) for n,links in adj.items()})}
        text,answer=values[op]
        return result(text,answer,'path' if op=='route' else 'exact',inputs=inputs,
                      path_rule={'feasible':False,'start':start,'goal':goal,'optimal_cost':plain_cost} if op=='route' else None)
    inputs['map']=g
    blocked=[[e['a'],e['b']] for e in g['edges'] if not e['open'] or e['width']<g['body_width']]
    plain_cost=shortest(g,feasible=False)[1]
    rules={'feasible':True,'start':start,'goal':goal,'optimal_cost':cost}
    values={'route':('Return a shortest feasible route; null if no route exists.',route),
        'cost':('Return minimum feasible route cost; null if unreachable.',cost),
        'reachable':('Is the goal reachable by this body?',route is not None),
        'blocked_edges':('List blocked or too-narrow edges as sorted endpoint pairs.',sorted(blocked)),
        'detour':('Return feasible minimum cost minus unconstrained minimum cost; null if either is unreachable.',cost-plain_cost if cost is not None and plain_cost is not None else None),
        'alternate_optimum':('Return any shortest feasible route. Equivalent shortest paths are accepted.',route),
        'feasible_subgraph':('List all traversable edges as sorted endpoint pairs.',sorted([e['a'],e['b']] for e in g['edges'] if e['open'] and e['width']>=g['body_width']))}
    if op=='waypoint':
        a,ca=shortest(g,goal=g['waypoint']);b,cb=shortest(g,start=g['waypoint'])
        answer=a+b[1:] if a is not None and b is not None else None
        rules.update(waypoint=g['waypoint'],optimal_cost=ca+cb if answer else None)
        values[op]=(f'Return a minimum feasible route via {g["waypoint"]}, or null.',answer)
    elif op=='avoid_node':
        avoid=g['nodes'][1];answer,c=shortest(g,avoid=[avoid]);rules.update(avoid=[avoid],optimal_cost=c)
        values[op]=(f'Return minimum feasible route avoiding {avoid}, or null.',answer)
    elif op=='budget_route':
        values[op]=('Return a shortest feasible route only if cost fits the given budget; otherwise null.',route if cost is not None and cost<=g['budget'] else None)
        rules['budget']=g['budget']
    elif op=='reverse_route':
        answer,c=shortest(g,start=goal,goal=start);rules.update(start=goal,goal=start,optimal_cost=c)
        values[op]=('Return shortest feasible route from goal back to start, or null.',answer)
    elif op=='replan':
        modified={**g,'edges':[dict(e) for e in g['edges']]};modified['edges'][0]['open']=False
        inputs['map']=modified;answer,c=shortest(modified);rules.update(optimal_cost=c)
        values[op]=('The map includes an observed closed edge. Replan a minimum feasible route.',answer)
    text,answer=values[op]
    kind='path' if op in ['route','alternate_optimum','waypoint','avoid_node','budget_route','reverse_route','replan'] else 'exact'
    return result(text,answer,kind,inputs=inputs,path_rule=rules if kind=='path' else None)


def has_cycle(g):
    adj=adjacency(g);visited=set();active=set()
    def visit(node,parent=None):
        visited.add(node);active.add(node)
        for other,_ in adj[node]:
            if not g['directed'] and other==parent:continue
            if other in active:return True
            if other not in visited and visit(other,node):return True
        active.remove(node);return False
    return any(n not in visited and visit(n) for n in g['nodes'])
