"""P2b fail-closed inter-component *evidence dependency* assessment.

This is NOT an assume-guarantee composition theorem. Components are independently
checked finite abstract models. Edges say that a consumer relies on a declared
provider property. No executable wiring, interleaving or refinement is checked.
A 'Ready' outcome explicitly means readiness for integration, not correctness
of a composite executable or a production release.
"""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import json
import re

from .checker import obligations
from .evolution import property_fingerprints
from .lang import AxError, digest, parse, validate

VERSION = 'ax-evidence-dependencies/0.1'
NAME = re.compile(r'^[A-Za-z_][A-Za-z_0-9]{0,79}$')


def _canonical_component_id(x):
    if not isinstance(x, str) or not NAME.fullmatch(x):
        raise AxError('E_COMPOSE_ID', 'invalid component/property identifier')
    return x


def load_manifest(path):
    """Load a declarative manifest with exact schema and confined spec paths."""
    path = Path(path)
    manifest = json.loads(path.read_text(encoding='utf8'))
    if not isinstance(manifest, dict) or set(manifest) != {'schema', 'components', 'dependencies'}:
        raise AxError('E_COMPOSE_SCHEMA', 'unexpected manifest fields')
    if manifest['schema'] != VERSION:
        raise AxError('E_COMPOSE_SCHEMA', 'unsupported manifest version')
    components = manifest['components']
    dependencies = manifest['dependencies']
    if not isinstance(components,list) or not 1 <= len(components) <= 64:
        raise AxError('E_COMPOSE_SIZE','expected 1..64 components')
    if not isinstance(dependencies,list) or len(dependencies)>256:
        raise AxError('E_COMPOSE_SIZE','too many dependency edges')
    specs={}
    exports={}
    basedir=path.resolve().parent
    for component in components:
        if not isinstance(component,dict) or set(component) != {'id','spec','exports'}:
            raise AxError('E_COMPOSE_SCHEMA','invalid component fields')
        cid=_canonical_component_id(component['id'])
        if cid in specs:raise AxError('E_COMPOSE_DUPLICATE',cid)
        rel=component['spec']
        if not isinstance(rel,str) or not rel.endswith('.ax') or Path(rel).is_absolute():
            raise AxError('E_COMPOSE_PATH','spec must be a local .ax path')
        candidate=basedir/rel
        filename=candidate.resolve()
        if not filename.is_relative_to(basedir) or candidate.is_symlink():
            raise AxError('E_COMPOSE_PATH','spec outside manifest root')
        raw_exports=component['exports']
        if not isinstance(raw_exports,list) or not raw_exports or len(raw_exports)!=len(set(raw_exports)):
            raise AxError('E_COMPOSE_EXPORT','exports must be a nonempty unique list')
        for prop in raw_exports:_canonical_component_id(prop)
        ir=validate(parse(filename.read_text(encoding='utf8')))
        if ir['model']!=cid:
            raise AxError('E_COMPOSE_MODEL','component id must match model name')
        present=set(property_fingerprints(ir))
        if not set(raw_exports).issubset(present):
            raise AxError('E_COMPOSE_EXPORT','property not defined in model')
        specs[cid]=ir
        exports[cid]=sorted(raw_exports)
    edges=set()
    for link in dependencies:
        if not isinstance(link,dict) or set(link)!={'consumer','provider','property'}:
            raise AxError('E_COMPOSE_SCHEMA','invalid dependency fields')
        consumer=_canonical_component_id(link['consumer'])
        provider=_canonical_component_id(link['provider'])
        prop=_canonical_component_id(link['property'])
        if consumer not in specs or provider not in specs:
            raise AxError('E_COMPOSE_REFERENCE','unknown component in dependency')
        if consumer==provider:
            raise AxError('E_COMPOSE_CYCLE','self dependency')
        if prop not in exports[provider]:
            raise AxError('E_COMPOSE_EXPORT','required guarantee not exported')
        edge=(consumer,provider,prop)
        if edge in edges: raise AxError('E_COMPOSE_DUPLICATE','duplicate dependency edge')
        edges.add(edge)
    # Explicitly reject cyclic evidence dependencies rather than guessing a fixpoint.
    indegree={k:0 for k in specs}; reverse=defaultdict(set)
    for consumer,provider,_ in edges:
        if consumer not in reverse[provider]:
            reverse[provider].add(consumer);indegree[consumer]+=1
    queue=deque(sorted(k for k,v in indegree.items() if v==0));order=[]
    while queue:
        n=queue.popleft();order.append(n)
        for dependent in sorted(reverse[n]):
            indegree[dependent]-=1
            if indegree[dependent]==0:queue.append(dependent)
    if len(order)!=len(specs):raise AxError('E_COMPOSE_CYCLE','cyclic dependency graph')
    normalized={
        'schema':VERSION,
        'components':[{'id':cid, 'spec_digest':digest(specs[cid]),
                       'exports':exports[cid],
                       'export_fingerprints':{k:property_fingerprints(specs[cid])[k] for k in exports[cid]}}
                      for cid in sorted(specs)],
        'dependencies':[{'consumer':c,'provider':p,'property':t} for c,p,t in sorted(edges)],
        'order':order
    }
    return specs,normalized


def assess_composition(workspace,manifest_path):
    specs,manifest=load_manifest(manifest_path)
    evidence={}; reasons=[]
    # Intentionally require each local model's ALL obligations to be met: a verified
    # exported invariant with an invalid action relation is not a valid guarantee.
    for cid in manifest['order']:
        ir=specs[cid]
        gate=workspace.gate_model_evolved(ir)
        evidence[cid]={
            'model_digest':digest(ir),
            'local_gate_decision':gate['decision'],
            'covered_by_run':gate['covered_by_run'],
            'missing_obligations':gate['missing_obligations'],
            'required_obligation_count':len(obligations(ir)),
            'assurance':'Bounded' if gate['decision']=='Approved' else 'None'
        }
        if gate['decision']!='Approved':
            reasons.append({'code':'MISSING_LOCAL_MODEL_EVIDENCE','component':cid,
                            'missing':gate['missing_obligations']})
    for link in manifest['dependencies']:
        provider=link['provider'];prop=link['property']
        obligation=f'{provider}/model/property/{prop}'
        if obligation not in evidence[provider]['covered_by_run']:
            reasons.append({'code':'UNSATISFIED_PROVIDER_GUARANTEE',**link})
    report={'schema':'ax-composition-assessment/0.1',
            'manifest_digest':workspace.put(manifest),
            'decision':'Ready' if not reasons else 'Blocked',
            'target':'abstract-model-evidence-integration-readiness',
            'scope':'Independent finite abstract model checks and declared acyclic evidence dependencies only; '
                    'no assume-guarantee proof, no cross-component runtime behavior, '
                    'no C++ refinement, no sandbox and no production release',
            'components':evidence,'dependencies':manifest['dependencies'],
            'reasons':reasons}
    report['assessment_digest']=workspace.put(report)
    return report
