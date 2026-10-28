"""P2 conservative typed semantic impact and bounded-evidence reuse.

Invariant: no dependency heuristic may grant reuse. A proof-like claim is reused
only for an identical canonical transition system, identical property and
verified historical bounded evidence under the current checker. Otherwise fail
closed. This is *model-level* reuse, never a C++ implementation guarantee.
"""
from __future__ import annotations
from collections import defaultdict, deque
from .lang import digest, validate
from .checker import obligations

GRAPH_VERSION = 'ax-impact-graph/0.1'
POLICY_VERSION = 'ax-p2-model-reuse/0.1'
CORE_FIELDS = ('schema_version', 'semantics_version', 'model', 'types', 'state', 'init', 'actions', 'observe')


def behavior_core(ir):
    validate(ir)
    return {k: ir[k] for k in CORE_FIELDS}


def behavior_digest(ir):
    return digest(behavior_core(ir))


def property_fingerprints(ir):
    return {p['name']: digest({'kind': p['kind'], 'expr': p['expr']}) for p in ir['properties']}


def _refs(expr):
    if expr['op'] in ('ref', 'post'):
        return {expr['name']}
    out = set()
    for child in expr.get('args', []):
        out.update(_refs(child))
    return out


def typed_graph(ir):
    """Trace/explanation graph (conservative). Not an independent reuse oracle."""
    validate(ir)
    nodes = {}
    edges = set()

    def add(node_id, kind, fingerprint):
        nodes[node_id] = {'kind': kind, 'fingerprint': fingerprint}

    def dep(target, source):
        if target not in nodes or source not in nodes:
            raise ValueError('E_GRAPH_NODE: unknown endpoint')
        edges.add((source, target))  # changed source potentially affects target

    for name, ty in ir['types'].items():
        add('type/' + name, 'type', digest(ty))
    for name, ty in ir['state'].items():
        add('state/' + name, 'state', digest({'name':name,'type':ty}))
    add('init', 'initial-condition', digest(ir['init']))
    add('observation', 'observation', digest(ir['observe']))
    for name, ty in ir['state'].items():
        if ty in ir['types']: dep('state/' + name, 'type/' + ty)
    for name in _refs(ir['init']):
        if 'state/' + name in nodes: dep('init', 'state/' + name)
    for action in ir['actions']:
        key = 'action/' + action['name']
        add(key, 'transition-relation', digest(action))
        for state in ir['state']:
            # Conservative: any action can affect reachable states and thus every invariant.
            dep(key, 'state/' + state)
        for name in action['inputs']:
            ty = action['inputs'][name]
            if 'type/' + ty in nodes:dep(key, 'type/' + ty)
    for prop in ir['properties']:
        key = 'property/' + prop['name']
        add(key, 'invariant', property_fingerprints(ir)[prop['name']])
        dep(key, 'init')
        for a in ir['actions']: dep(key, 'action/' + a['name'])
        for name in _refs(prop['expr']):
            if 'state/' + name in nodes: dep(key, 'state/' + name)
    return {'version': GRAPH_VERSION, 'model':ir['model'], 'model_digest': digest(ir),
            'behavior_digest': behavior_digest(ir),
            'nodes':nodes,
            'edges':[{'source':src, 'target':tgt, 'kind':'may-affect'} for src,tgt in sorted(edges)]}


def impact(old, new):
    """Return typed change and conservative affected nodes. Does not grant reuse."""
    oldgraph, newgraph = typed_graph(old), typed_graph(new)
    oldnodes, newnodes = oldgraph['nodes'],newgraph['nodes']
    keys=set(oldnodes)|set(newnodes)
    direct=sorted(k for k in keys if oldnodes.get(k)!=newnodes.get(k))
    links=defaultdict(set)
    for g in (oldgraph,newgraph):
        for edge in g['edges']:
            links[edge['source']].add(edge['target'])
    changed=set(direct)
    queue=deque(direct)
    while queue:
        for child in links[queue.popleft()]:
            if child not in changed:
                changed.add(child);queue.append(child)
    old_props=property_fingerprints(old)
    new_props=property_fingerprints(new)
    compatible=behavior_digest(old)==behavior_digest(new)
    reuse_names=sorted(k for k,h in new_props.items() if compatible and old_props.get(k)==h)
    must_check=sorted(set(new_props)-set(reuse_names))
    return {'policy_version':POLICY_VERSION,'old_spec_digest':digest(old),'new_spec_digest':digest(new),
            'old_core_digest':behavior_digest(old), 'new_core_digest':behavior_digest(new),
            'behavior_unchanged':compatible, 'direct_changed_nodes':direct,'affected_nodes':sorted(changed),
            'potentially_reusable_properties':reuse_names,
            'requires_new_property_evidence':must_check,
            'scope':'Conservative model-level analysis; no C++ evidence reuse and no proof of change equivalence'}


def model_obligation_fingerprint(ir, oid):
    """Stable semantic dependency: all action obligations rely on entire behavior core."""
    prefix=f"{ir['model']}/model/property/"
    if oid.startswith(prefix):
        name=oid[len(prefix):]
        p=property_fingerprints(ir)
        return digest({'behavior': behavior_digest(ir), 'name':name, 'property':p[name]}) if name in p else None
    if oid in {x['id'] for x in obligations(ir)}:
        return digest({'behavior':behavior_digest(ir),'obligation':oid})
    return None
