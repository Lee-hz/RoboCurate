"""Workflow invariants: new tasks, retries, evidence, conflicts and real media I/O."""
import copy
from functools import partial
import json
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace
import urllib.request
import urllib.error

import pytest

from storage import Conflict
from taskflow import contracts
from taskflow.http import byte_range, get as workflow_get
from taskflow.service import TaskflowService
from taskflow.vlm import CompanyVLM


def spec(count=2):
    return contracts.task_spec(dict(task_name='把测试物体移入容器',task_goal='物体留在容器中',
        stages=[dict(id=f's{i}',name=f'动作{i}',goal=f'结果{i}',success_criteria=['对象状态可确认']) for i in range(count)]))


def row(stage,a,b,status='completed',frame='a'):
    return dict(stage_id=stage,start_s=a,end_s=b,reason='测试观察',evidence_frame_ids=[frame],
        criteria_results=[dict(criterion_index=0,status=status,reason='可见状态',evidence_frame_ids=[frame])])


def test_different_stage_counts_and_failed_retry_remain_separate():
    for n in (2,7):
        task=spec(n);frames=[dict(id='a',time_s=1),dict(id='b',time_s=3),dict(id='c',time_s=5)]
        parts=contracts.segments([row('s1',0,2,'not_completed'),row('s0',2,4,frame='b'),row('s1',4,6,frame='c')],task,0,6,frames,True)
        assert [s['stage_id'] for s in parts]==['s1','s0','s1']
        summary=contracts.apply_human_review(dict(segments=parts),{})['summary']
        assert summary==dict(segment_count=3,completed=2,not_completed=1,uncertain=0)


def test_missing_criterion_or_evidence_cannot_be_completed():
    task=spec();task['stages'][0]['success_criteria'].append('手已经离开物体')
    frames=[dict(id='a',time_s=1)]
    proposal=row('s0',0,2)
    out=contracts.segments([proposal],task,0,2,frames,True)
    assert out[0]['completion']=='uncertain'
    proposal['criteria_results'][0]['evidence_frame_ids']=[]
    assert contracts.segments([proposal],spec(),0,2,frames,True)[0]['completion']=='uncertain'
    proposal['criteria_results'][0]['status']='not_completed'
    proposal['criteria_results'][0]['evidence_frame_ids']=['a']
    assert contracts.segments([proposal],task,0,2,frames,True)[0]['completion']=='not_completed'


def test_reference_or_fabricated_frames_cannot_prove_target_success():
    for key in ('reference-only','fabricated'):
        with pytest.raises(ValueError,match='未提供'):
            contracts.segments([row('s0',0,2,frame=key)],spec(),0,2,[dict(id='a',time_s=1)],True)
    with pytest.raises(ValueError,match='观察范围'):
        contracts.segments([row('s0',0,2)],spec(),0,2,[dict(id='a',time_s=20)],True)


def test_gaps_stay_unknown_and_overlaps_or_invalid_times_are_rejected():
    frames=[dict(id='a',time_s=2)]
    out=contracts.segments([row('s0',1,3)],spec(),0,4,frames,True)
    assert [(r['start_s'],r['end_s']) for r in out]==[(0,1),(1,3),(3,4)]
    assert out[0]['completion']==out[2]['completion']=='uncertain'
    for rows in ([row('s0',0,3),row('s1',2,4)],[row('s0',0,float('nan'))],[row('s0',0,6)],[row('unknown',0,4)]):
        with pytest.raises(ValueError):contracts.segments(rows,spec(),0,4,frames)


@pytest.fixture
def flow(tmp_path):
    lib=SimpleNamespace(workspace=tmp_path,order=[])
    service=TaskflowService(lib)
    yield service
    service.close()


def video(path):
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=10',
        '-t','2','-c:v','mpeg4','-y',str(path)],check=True,timeout=20)
    return path


def test_video_samples_and_changed_sources(flow,tmp_path):
    path=video(tmp_path/'synthetic.mp4');asset=flow.add_asset(dict(kind='video',path=str(path)))
    frames,coverage=flow.media.sample(asset,budget=5)
    assert len(frames)>=2 and coverage['timestamp_kind']=='ffmpeg_seek_position'
    assert all(Path(f['path']).is_file() for f in frames)
    flow.media.unchanged(asset)
    with path.open('ab') as file:file.write(b'changed')
    with pytest.raises(ValueError,match='已变化'):flow.media.unchanged(asset)


def test_native_playback_validates_asset_before_returning_frame_index(flow,monkeypatch):
    asset=flow.put('assets',dict(source=dict(kind='recording',id='native',snapshot=False)))
    events=[]
    monkeypatch.setattr(flow.media,'unchanged',lambda a:events.append(('validated',a['id'])))
    flow.library.frame_store=SimpleNamespace(public_index=lambda ep:events.append(('index',ep)) or {'token':'source-version'})
    handler=SimpleNamespace(library=SimpleNamespace(taskflow=flow),_json=lambda data,**kw:data)
    assert workflow_get(handler,'/api/taskflow/frame-index',{'id':[asset['id']]})=={'token':'source-version'}
    assert events==[('validated',asset['id']),('index','native')]
    def changed(a):raise ValueError('原视频或采集快照已变化')
    monkeypatch.setattr(flow.media,'unchanged',changed)
    with pytest.raises(ValueError,match='已变化'):
        workflow_get(handler,'/api/taskflow/frame-index',{'id':[asset['id']]})
    assert len(events)==2


def setup_run(flow):
    template=flow.put('templates',dict(name='测试',asset_id='1'*32,spec=spec(),reference_run_id='2'*32))
    parts=contracts.segments([row('s0',0,2)],spec(),0,2,[dict(id='a',time_s=1)],True)
    run=flow.put('runs',dict(name='测试记录',asset_id='1'*32,template_id=template['id'],template_revision=1,
        template_snapshot=spec(),result=dict(segments=parts),human_review={}))
    return template,run


def test_edits_require_revisions_and_never_overwrite_model_results(flow):
    template,run=setup_run(flow)
    body=dict(segment_id='segment-001',completion='not_completed',note='手动核对未入篮')
    with pytest.raises(ValueError):flow.review_segment(run['id'],body)
    output=flow.review_segment(run['id'],dict(body,revision=1))
    assert output['result']['segments'][0]['completion']=='completed'
    assert output['result']['segments'][0]['effective_completion']=='not_completed'
    with pytest.raises(Conflict):flow.review_segment(run['id'],dict(body,revision=1))
    with pytest.raises(ValueError):flow.update_template(template['id'],dict(spec=spec()))
    flow.update_template(template['id'],dict(spec=spec(7),revision=1))
    assert flow.public_run(run['id'])['template_stale']
    assert len(flow.get('runs',run['id'])['template_snapshot']['stages'])==2


def test_overview_distinguishes_model_prediction_from_manual_review(flow):
    _,run=setup_run(flow)
    run['result'].update(provider={'model':'HORIZON-MiniMax'},analysis_range={'start_s':0,'end_s':2})
    run=flow.put('runs',run)
    overview=flow.overview()['runs'][0]
    assert overview['model']=='HORIZON-MiniMax'
    assert overview['analysis_range']=={'start_s':0,'end_s':2}
    assert overview['summary']['completed']==1 and overview['reviewed_segments']==0
    flow.review_segment(run['id'],dict(revision=run['revision'],segment_id='segment-001',completion='uncertain',note='人工测试样例'))
    overview=flow.overview()['runs'][0]
    assert overview['reviewed_segments']==1 and overview['summary']['uncertain']==1


def test_cancel_after_last_verification_cannot_publish_result(flow,monkeypatch):
    asset=dict(id='1'*32,name='测试',duration_s=2,source=dict(source_fingerprint='test'))
    job=flow.put('jobs',dict(kind='reference',asset_id=asset['id'],state='queued',progress=0,instruction='',provider={},cancel_requested=False))
    frames=[dict(id='a',time_s=0),dict(id='b',time_s=2)]
    monkeypatch.setattr(flow.media,'unchanged',lambda a:None)
    monkeypatch.setattr(flow.media,'sample',lambda *a,**kw:(frames,{}))
    monkeypatch.setattr(flow,'_complete',lambda *a:dict(task={**spec(),'origin':'human_edited'},segments=[row('s0',0,2)]))
    def verify(*args):
        flow.cancel(job['id'])
        return [],[],[]
    monkeypatch.setattr(flow,'_verify',verify)
    flow._run(job['id'],asset,None)
    assert flow.get('jobs',job['id'])['state']=='cancelled'
    assert not flow.list('runs') and not flow.list('templates')


def test_worker_saves_model_proposal_as_model_origin(flow,monkeypatch):
    asset=dict(id='1'*32,name='测试',duration_s=2,source=dict(source_fingerprint='test'))
    job=flow.put('jobs',dict(kind='reference',asset_id=asset['id'],state='queued',progress=0,instruction='',provider={},cancel_requested=False))
    frames=[dict(id='a',time_s=0),dict(id='b',time_s=2)]
    monkeypatch.setattr(flow.media,'unchanged',lambda a:None)
    monkeypatch.setattr(flow.media,'sample',lambda *a,**kw:(frames,{}))
    monkeypatch.setattr(flow,'_complete',lambda *a:dict(task={**spec(),'origin':'human_edited'},segments=[row('s0',0,2)]))
    flow._run(job['id'],asset,None)
    assert flow.get('jobs',job['id'])['state']=='completed'
    assert flow.list('templates')[0]['spec']['origin']=='vlm_proposal'


@pytest.mark.parametrize('header,expected',[(None,(0,9,False)),('bytes=0-3',(0,3,True)),('bytes=6-',(6,9,True)),('bytes=-3',(7,9,True)),('bytes=0-99',(0,9,True))])
def test_video_range(header,expected):assert byte_range(header,10)==expected


@pytest.mark.parametrize('header',['bytes=15-','bytes=2-1','bytes=-0','bytes=0-1,4-6','other=0-2'])
def test_bad_ranges(header):
    with pytest.raises(ValueError):byte_range(header,10)


def test_http_upload_preview_and_range_are_real(flow,tmp_path):
    import server
    from studio import Handler
    flow.library.taskflow=flow
    http=server.ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,library=flow.library,robot=None))
    threading.Thread(target=http.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{http.server_address[1]}'
    try:
        data=video(tmp_path/'upload.mp4').read_bytes()
        req=urllib.request.Request(url+'/api/taskflow/upload?name=demo.mp4',data=data,headers={'Content-Type':'application/octet-stream'},method='POST')
        with urllib.request.urlopen(req) as response:asset=json.load(response)
        assert asset['name']=='demo.mp4'
        req=urllib.request.Request(url+'/api/taskflow/video?id='+asset['id'],headers={'Range':'bytes=0-15'})
        with urllib.request.urlopen(req) as response:
            assert response.status==206 and response.read()==data[:16]
        with urllib.request.urlopen(url+'/api/taskflow/preview?id='+asset['id']+'&t=0.5') as response:
            assert response.read().startswith(b'\xff\xd8')
        req=urllib.request.Request(url+'/api/taskflow/assets',data=b'{}',headers={'Origin':'https://foreign.example','Content-Type':'application/json'},method='POST')
        with pytest.raises(urllib.error.HTTPError) as err:urllib.request.urlopen(req)
        assert err.value.code==403
    finally:http.shutdown();http.server_close()


def test_manual_resegmentation_resets_outcomes_and_keeps_original(flow):
    template,run=setup_run(flow)
    flow.put('assets',dict(id='1'*32,duration_s=2))
    out=flow.edit_segments(run['id'],dict(revision=1,note='抓取和释放应分开',segments=[dict(stage_id='s0',start_s=0,end_s=1),dict(stage_id='s1',start_s=1,end_s=2)]))
    assert out['result']['summary']==dict(segment_count=2,completed=0,not_completed=0,uncertain=2)
    assert out['model_result']['segments'][0]['completion']=='completed'
    flow.review_segment(run['id'],dict(revision=out['revision'],segment_id='segment-002',completion='not_completed',note='释放未成功'))
    assert flow.public_run(run['id'])['result']['summary']['not_completed']==1


def test_artificial_window_boundary_does_not_create_failed_attempt(flow,monkeypatch):
    job=flow.put('jobs',dict(state='queued',cancel_requested=False));frames=[dict(id='a',time_s=1),dict(id='b',time_s=8)]
    monkeypatch.setattr(flow.media,'sample',lambda *a,**kw:(frames,{}))
    responses=iter([dict(segments=[row('s0',0,6,'not_completed')]),dict(segments=[row('s0',6,12,frame='b')]),dict(segments=[row('s0',0,12,frame='b')])])
    monkeypatch.setattr(flow,'_complete',lambda *a:next(responses))
    result,_,_=flow._verify(job['id'],dict(duration_s=12),spec(),[dict(stage_id='s0',start_s=0,end_s=6),dict(stage_id='s0',start_s=6,end_s=12)],[])
    assert len(result)==1 and result[0]['completion']=='completed' and result[0]['end_s']==12


def test_analysis_windows_group_short_adjacent_phases_without_changing_their_proposals():
    coarse=[dict(stage_id='s0',start_s=0,end_s=2),dict(stage_id='s1',start_s=2,end_s=6),dict(stage_id='s0',start_s=6,end_s=12)]
    original=copy.deepcopy(coarse)
    windows=TaskflowService.analysis_windows(coarse)
    assert [(w['start_s'],w['end_s']) for w in windows]==[(0,6),(6,12)]
    assert len(windows[0]['candidates'])==2 and coarse==original


def test_continuation_merge_keeps_failure_and_explicit_retry():
    frames=[dict(id='a',time_s=1),dict(id='b',time_s=3)]
    rows=[row('s0',0,2),row('s0',2,4,frame='b')]
    parts=contracts.segments(rows,spec(),0,4,frames,True)
    merged=contracts.coalesce_continuations(parts)
    assert len(merged)==1 and len(merged[0]['continuation_fragments'])==2
    assert merged[0]['start_s']==0 and merged[0]['end_s']==4
    parts[1]['new_attempt']=True
    assert len(contracts.coalesce_continuations(parts))==2
    parts[1]['new_attempt']=False;parts[0]['completion']='not_completed'
    assert len(contracts.coalesce_continuations(parts))==2


def test_duplicate_submission_reuses_active_job(flow,monkeypatch):
    asset=flow.put('assets',dict(name='测试',duration_s=2,source={}))
    monkeypatch.setattr(flow.vlm,'configuration',lambda:({'model':'HORIZON-MiniMax'},''))
    monkeypatch.setattr(flow.vlm,'provenance',lambda:{})
    monkeypatch.setattr(flow.media,'unchanged',lambda a:None)
    calls=[]
    flow.pool=SimpleNamespace(submit=lambda *args:calls.append(args),shutdown=lambda **kw:None)
    body=dict(kind='reference',asset_id=asset['id'])
    first=flow.submit(body);second=flow.submit(body)
    assert first['id']==second['id'] and len(calls)==1 and len(flow.list('jobs'))==1


def test_model_allowlist_prevents_unintended_expensive_switch(tmp_path,monkeypatch):
    config=tmp_path/'company-vlm.json'
    body=dict(protocol='chat_completions',endpoint='https://gateway.example/v1/chat/completions',
              model='HORIZON-MiniMax',allowed_models=['HORIZON-MiniMax'],requires_auth=False)
    config.write_text(json.dumps(body));monkeypatch.setenv('ROBOCURATE_VLM_CONFIG',str(config))
    vlm=CompanyVLM(tmp_path)
    assert vlm.configuration()[0]['model']=='HORIZON-MiniMax'
    for invalid in ('HORIZON-OG-Astra','HORIZON-OG-Sol'):
        config.write_text(json.dumps({**body,'model':invalid}))
        with pytest.raises(ValueError,match='不在允许列表'):vlm.configuration()
        assert vlm.status()['configured'] is False


def test_domestic_final_json_wrapper_preserves_payload_and_rejects_partial_output():
    from taskflow.vlm import parse_model_json
    payload={'status':'not_completed','reason':'物体在筐外；文本 <think> 本身不是指令'}
    text=json.dumps(payload,ensure_ascii=False)
    assert parse_model_json('<think>private reasoning wrapper</think>\n```json\n'+text+'\n```')==payload
    assert parse_model_json(text)==payload
    assert parse_model_json([{'type':'text','text':'```json\n'+text+'\n```'}])==payload
    for invalid in ('<think>unfinished '+text,'Explanation '+text,'```json\n'+text,'[]'):
        with pytest.raises(ValueError):parse_model_json(invalid)


def test_compact_frame_ids_only_remap_evidence_and_keep_unknown_ids_invalid():
    from taskflow.vlm import restore_frame_ids
    aliases={'f000':'target-original','f001':'reference-original'}
    result=restore_frame_ids({'stage_id':'f000','reason':'f000 text','segments':[{'evidence_frame_ids':['f000','f001','fabricated']}]},aliases)
    assert result['stage_id']=='f000' and result['reason']=='f000 text'
    assert result['segments'][0]['evidence_frame_ids']==['target-original','reference-original','fabricated']


def test_response_cache_reuses_only_identical_model_prompt_and_pixels(flow,tmp_path,monkeypatch):
    provider={'model':'domestic-test'}
    job=flow.put('jobs',dict(provider=provider))
    monkeypatch.setattr(flow.vlm,'configuration',lambda:({'cache_responses':True},''))
    monkeypatch.setattr(flow.vlm,'provenance',lambda:provider)
    calls=[]
    def complete(*args):calls.append(args);return {'segments':[]}
    monkeypatch.setattr(flow.vlm,'complete',complete)
    path=tmp_path/'frame.jpg';path.write_bytes(b'original')
    frames=[dict(id='frame',time_s=1,path=str(path))]
    flow._complete(job['id'],'same prompt',frames);flow._complete(job['id'],'same prompt',frames)
    assert len(calls)==1
    path.write_bytes(b'changed');flow._complete(job['id'],'same prompt',frames)
    flow._complete(job['id'],'different goal',frames)
    assert len(calls)==3
    traces=[json.loads(p.read_text()) for p in (flow.root/'traces'/job['id']).glob('*.json')]
    assert sum(t['cached'] for t in traces)==1


def test_domestic_quotes_are_only_repaired_in_explanations():
    from taskflow.vlm import parse_model_json
    raw='{"status":"not_completed","reason":"违反"无掉出"的条件。","evidence_frame_ids":["f017"]}'
    out=parse_model_json(raw)
    assert out=={'status':'not_completed','reason':'违反"无掉出"的条件。','evidence_frame_ids':['f017']}
    assert parse_model_json(json.dumps(out,ensure_ascii=False))==out
    for raw in ('{"status":completed,"reason":"观察"不到"。"}', '{"end_s":wrong,"reason":"观察"不到"。"}'):
        with pytest.raises(ValueError):parse_model_json(raw)


def test_continuing_goal_that_later_fails_is_not_split_into_a_false_success():
    frames=[dict(id='a',time_s=1),dict(id='b',time_s=3)]
    parts=contracts.segments([row('s0',0,2),row('s0',2,4,'not_completed',frame='b')],spec(),0,4,frames,True)
    result=contracts.coalesce_continuations(parts)
    assert len(result)==1 and result[0]['completion']=='not_completed'
    assert len(result[0]['continuation_fragments'])==2
    parts[1]['new_attempt']=True
    assert len(contracts.coalesce_continuations(parts))==2


def test_model_inputs_read_archived_payload_not_current_segment_summary(flow):
    run=flow.put('runs',dict(result={'state_evidence':{'facts':['current summary must not leak']}}))
    job=flow.put('jobs',dict(result_id=run['id']))
    other=flow.put('jobs',dict(result_id='f'*32))
    state=dict(available=True,start_s=1,end_s=4,facts=[dict(track='right_hand',min_value=.2)])
    folder=flow.root/'traces'/job['id'];folder.mkdir(parents=True)
    trace=dict(at='2026-10-16',prompt='待检查区间：{"start_s":2,"end_s":3}\n反馈观测（不可当作目标成功标签）：'+json.dumps(state)+'\nadditional rules',
        provider=dict(model='HORIZON-MiniMax',api_key='never expose'),frames=[dict(id='a',time_s=2,role='target',path='/private/path')],response={'private':'unused'})
    (folder/('a'*32+'.json')).write_text(json.dumps(trace))
    other_folder=flow.root/'traces'/other['id'];other_folder.mkdir(parents=True)
    (other_folder/('b'*32+'.json')).write_text(json.dumps(trace))
    out=flow.model_inputs(run['id']);assert len(out['requests'])==1
    request=out['requests'][0]
    assert request['state']==state and request['range']==dict(start_s=2,end_s=3)
    assert request['kind']=='verify' and request['model']=='HORIZON-MiniMax'
    assert 'never expose' not in json.dumps(out) and '/private/path' not in json.dumps(out)
    assert 'current summary' not in json.dumps(out) and 'response' not in request


def test_model_inputs_distinguish_visual_missing_and_unreadable_archives(flow):
    run=flow.put('runs',dict(result={}))
    assert not flow.model_inputs(run['id'])['available']
    job=flow.put('jobs',dict(result_id=run['id']))
    folder=flow.root/'traces'/job['id'];folder.mkdir(parents=True)
    (folder/'visual.json').write_text(json.dumps(dict(prompt='视频范围：{"start_s":0,"end_s":4}',frames=[],cached=True)))
    (folder/'broken.json').write_text('{')
    (folder/'bad-state.json').write_text(json.dumps(dict(prompt='反馈观测（不可当作目标成功标签）：bad',frames=[])))
    out=flow.model_inputs(run['id'])
    assert out['available'] and out['unreadable']==2
    assert out['requests'][0]['state'] is None and out['requests'][0]['cached']


def test_feedback_prepares_fresh_record_before_loading_state(flow,monkeypatch):
    events=[]
    job=flow.put('jobs',dict(state='running',cancel_requested=False))
    flow.library.prepare=lambda ep:events.append(('prepare',ep)) or dict(state='building',message='读取中')
    flow.library.state=lambda ep:events.append(('ready',ep)) or dict(state='ready')
    monkeypatch.setattr('taskflow.service.time.sleep',lambda _:None)
    flow._prepare_feedback(job['id'],dict(source=dict(kind='recording',id='fresh')))
    assert events==[('prepare','fresh'),('ready','fresh')]
    assert flow.get('jobs',job['id'])['progress']==6


def test_feedback_parse_failure_stops_analysis(flow):
    job=flow.put('jobs',dict(state='running',cancel_requested=False))
    flow.library.prepare=lambda ep:dict(state='error',message='损坏的MCAP')
    with pytest.raises(ValueError,match='机器人反馈解析失败'):
        flow._prepare_feedback(job['id'],dict(source=dict(kind='recording',id='broken')))


def test_feedback_preparation_can_be_cancelled(flow,monkeypatch):
    from taskflow.service import Cancelled
    job=flow.put('jobs',dict(state='running',cancel_requested=False))
    flow.library.prepare=lambda ep:dict(state='building')
    flow.library.state=lambda ep:dict(state='building')
    monkeypatch.setattr('taskflow.service.time.sleep',lambda _:flow.cancel(job['id']))
    with pytest.raises(Cancelled):
        flow._prepare_feedback(job['id'],dict(source=dict(kind='recording',id='fresh')))


def test_video_and_snapshot_do_not_require_native_cache(flow):
    for source in [dict(kind='video'),dict(kind='recording',snapshot=True)]:
        flow._prepare_feedback('unused',dict(source=source))
