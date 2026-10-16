import ast
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
torch=pytest.importorskip('torch',reason='Optional historical learning-model tests require torch')
from scipy.special import digamma
from curation.learning import ksg_local,BC
from curation.ranking import rank_scores,eligibility,choose_records,stratify

def curation_reference_root():
    bundled=Path(__file__).resolve().parent/'reference/curation_20260930'
    return bundled if bundled.is_dir() else Path(__file__).resolve().parents[2]/'research/curation_20260930'

def test_official_ksg_numeric_parity():
    source=curation_reference_root()/'upstream-deminf/scripts/quality/quality_estimators.py'
    if not source.is_file():pytest.skip('Optional upstream research snapshot is not distributed')
    tree=ast.parse(source.read_text());selected=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['_l2_dists','ksg_estimator']],type_ignores=[])
    namespace={'jnp':np,'digamma':digamma,'jax':SimpleNamespace(random=SimpleNamespace(split=lambda r:(0,1)))};exec(compile(selected,str(source),'exec'),namespace)
    rng=np.random.default_rng(5);s=rng.normal(size=(100,12));a=rng.normal(size=(100,6));alg=SimpleNamespace(predict=lambda state,batch,rng:state)
    expected=namespace['ksg_estimator']({},0,np.arange(5,8),alg,s,alg,a)
    np.testing.assert_allclose(ksg_local(s,a),expected,atol=1e-12)

def test_gradient_cosine_matches_autograd():
    torch.manual_seed(10);m=BC(5,3);x=torch.randn(2,5);target=torch.randn(2,3);grad=[]
    for i in range(2):
        g=torch.autograd.grad((m(x[i:i+1])-target[i:i+1]).square().sum(),tuple(m.head.parameters()))
        grad.append(torch.cat([v.flatten() for v in g]))
    expected=torch.nn.functional.cosine_similarity(*[g[None] for g in grad]).item()
    h=m.trunk(x);h=torch.cat([h,torch.ones(2,1)],1);err=m.head(h[:,:-1])-target
    actual=(torch.nn.functional.cosine_similarity(h[0:1],h[1:2])*torch.nn.functional.cosine_similarity(err[0:1],err[1:2])).item()
    assert abs(actual-expected)<1e-6

def test_ties_not_artificially_stretched():
    assert list(rank_scores([1,1,1]))==[5,5,5]
    assert rank_scores([0,1,1,2])[1]==rank_scores([0,1,1,2])[2]

def test_failure_not_admitted_by_high_score():
    row={'outcome':False,'task':{'completion':1,'score':10}}
    assert eligibility(row,'sim')[0]=='D'
    assert eligibility(row,'control')[0]=='U'

def test_unknown_and_incomplete_are_not_zero_or_success():
    assert eligibility({'outcome':None,'task':{}},'real')[0]=='R'
    assert eligibility({'outcome':True,'task':{'state':'incomplete_start'}},'sim')[0]=='E'

def test_selection_preserves_ties_and_task_boundaries():
    records=[dict(id='a',cohort='sim',grade='A',score=9),dict(id='b',cohort='sim',grade='A',score=9),dict(id='c',cohort='sim',grade='D',score=10),dict(id='d',cohort='real',grade='A',score=10),dict(id='e',cohort='sim',grade='A',score=10,duplicate_of='a')]
    assert choose_records(records,'sim',.25)==['a','b']

def test_single_candidate_cannot_be_called_top_quality():
    rows=[dict(id='a',outcome=True,task={'task_result':'completed'},motion={})]
    report={'scores':{'deminf':[1],'qoq':[1]},'seed_scores':{'deminf':[[1],[1],[1]]}}
    r=stratify(rows,'sim',report)['a'];assert r['score']==5 and r['grade']=='B' and r['external_quality_certified'] is False

def test_coverage_selector_represents_separated_groups():
    from curation.coverage import facility_select
    chosen,report=facility_select(np.array([[0.,0],[.01,0],[9.,9],[9.01,9]]),2)
    assert len(chosen)==len(set(chosen))==2
    assert any(i<2 for i in chosen) and any(i>=2 for i in chosen)
    assert 0<report['mean_representation']<=1

def test_completeness_values_never_affect_admission_or_rank():
    import copy
    rows=[dict(id=str(i),outcome=True,task={'task_result':'completed','completion':i/10,'score':i},motion={}) for i in range(3)]
    report={'scores':{'deminf':[1.,2.,3.],'qoq':[0.,0.,0.]},'seed_scores':{'deminf':[[1.,2.,3.]]*3}}
    before=stratify(rows,'sim',report)
    changed=copy.deepcopy(rows)
    for r in changed:r['task'].update(completion=0,score=-100)
    assert stratify(changed,'sim',report)==before

def test_original_workbench_has_only_one_quality_score():
    from curation.bridge import project_quality
    old=dict(score=99,rating={'score':99},grading={'grade':'A','metrics':{'coverage_fraction':1},'checks':[]})
    for grade in ['D','E','R','U']:
        q=project_quality(old,dict(grade=grade,score=9.99))
        assert q['score'] is None and q['rating']['score'] is None
        assert q['rating']['dimensions']==[] and q['grading']['grade']==grade
    q=project_quality(old,dict(grade='C',score=2.4))
    assert q['score']==2.4 and q['rating']['max_score']==10
    assert old['score']==99

def test_qualified_model_inputs_exclude_failed_incomplete_and_unknown():
    import json
    root=curation_reference_root()
    for domain,n in [('sim',21),('real',10)]:
        name=f'local-{domain}-qualified-v2'
        rows=json.loads((root/(name+'.json')).read_text())
        admission=json.loads((root/(name+'-admission.json')).read_text())
        arrays=np.load(root/(name+'.npz'))
        assert len(rows)==n and all(eligibility(r,domain)[0]=='candidate' for r in rows)
        assert set(arrays['owners'])==set(range(n))
        assert {r['id'] for r in rows}==set(admission['eligible'])
        assert not set(admission['eligible']) & {r['id'] for r in admission['excluded']}
