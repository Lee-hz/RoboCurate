"""Local credential lifecycle; no real API calls or user credentials."""
import json
import stat
from types import SimpleNamespace

import pytest

from taskflow.service import TaskflowService
from taskflow.vlm import CompanyVLM
from taskflow.http import get, post

ENDPOINT='https://gateway.example.test/v1/chat/completions'
KEY='test-only-not-a-real-credential'


def test_private_persistence_and_public_redaction(tmp_path):
    vlm=CompanyVLM(tmp_path)
    assert not vlm.connection_settings()['configured']
    response=vlm.save_connection(dict(endpoint=ENDPOINT,api_key=KEY,model='HORIZON-OG-Astra'))
    assert response['model']=='HORIZON-MiniMax' and response['has_key']
    assert not response['tested'] and KEY not in json.dumps(response)
    assert stat.S_IMODE(vlm.local_path.stat().st_mode)==0o600
    restarted=CompanyVLM(tmp_path)
    config,key=restarted.configuration()
    assert key==KEY and config['allowed_models']==['HORIZON-MiniMax']
    restarted.save_connection(dict(endpoint=ENDPOINT,api_key=''))
    assert restarted.configuration()[1]==KEY
    with pytest.raises(ValueError,match='重新输入'):
        restarted.save_connection(dict(endpoint=ENDPOINT.replace('gateway','other'),api_key=''))
    assert restarted.configuration()[0]['endpoint']==ENDPOINT


def test_disconnect_never_falls_back_to_legacy_credentials(tmp_path):
    folder=tmp_path/'taskflow';folder.mkdir()
    legacy=folder/'company-vlm.json'
    legacy.write_text(json.dumps(dict(protocol='chat_completions',endpoint=ENDPOINT,model='HORIZON-MiniMax',requires_auth=False)))
    vlm=CompanyVLM(tmp_path)
    assert vlm.status()['configured']
    vlm.save_connection(dict(endpoint=ENDPOINT,api_key=KEY))
    assert not vlm.disconnect()['configured']
    assert KEY not in vlm.local_path.read_text() and legacy.exists()
    assert not CompanyVLM(tmp_path).status()['configured']


@pytest.mark.parametrize('endpoint',[
    'http://gateway.example.test/v1/chat/completions',
    'https://user:secret@gateway.example.test/v1/chat/completions',
    ENDPOINT+'?api_key=secret',ENDPOINT+'#secret',ENDPOINT+'\n',
    'https://gateway.example.test/v1',None,'https://gateway.example.test:wrong/v1/chat/completions'])
def test_invalid_endpoint_never_stored(tmp_path,endpoint):
    vlm=CompanyVLM(tmp_path)
    with pytest.raises(ValueError):vlm.save_connection(dict(endpoint=endpoint,api_key=KEY))
    assert not vlm.local_path.exists()


@pytest.mark.parametrize('key',['','line1\nline2','bad\rheader',None,'x'*8193])
def test_invalid_key_is_rejected_without_echo(tmp_path,key):
    with pytest.raises(ValueError) as err:
        CompanyVLM(tmp_path).save_connection(dict(endpoint=ENDPOINT,api_key=key))
    assert 'line1' not in str(err.value) and 'header' not in str(err.value)


def test_http_redaction_and_running_job_guard(tmp_path):
    flow=TaskflowService(SimpleNamespace(workspace=tmp_path))
    responses=[]
    handler=SimpleNamespace(library=SimpleNamespace(taskflow=flow),_json=lambda data,**kw:responses.append((data,kw)) or data)
    post(handler,'/api/taskflow/connection',dict(action='save',endpoint=ENDPOINT,api_key=KEY))
    get(handler,'/api/taskflow/connection',{})
    assert KEY not in json.dumps(responses)
    assert all(kw['cache']=='no-store' for _,kw in responses)
    job=flow.put('jobs',dict(state='running',cancel_requested=True))
    with pytest.raises(ValueError,match='尚未结束'):
        post(handler,'/api/taskflow/connection',dict(action='disconnect'))
    job['state']='cancelled';flow.put('jobs',job)
    assert not post(handler,'/api/taskflow/connection',dict(action='disconnect'))['configured']
    flow.close()


def test_new_key_does_not_inherit_old_connection_verification(tmp_path):
    vlm=CompanyVLM(tmp_path)
    vlm.save_connection(dict(endpoint=ENDPOINT,api_key=KEY))
    import hashlib
    (tmp_path/'taskflow/last-call.json').write_text(json.dumps(dict(passed=True,provider=vlm.provenance(),credential_digest=hashlib.sha256(KEY.encode()).hexdigest())))
    assert vlm.status()['tested']
    vlm.save_connection(dict(endpoint=ENDPOINT,api_key=KEY+'-new'))
    assert not vlm.status()['tested']


def test_backend_rejects_non_minimax_before_creating_job(tmp_path,monkeypatch):
    flow=TaskflowService(SimpleNamespace(workspace=tmp_path))
    monkeypatch.setattr(flow.vlm,'configuration',lambda:({'model':'HORIZON-OG-Astra'},''))
    with pytest.raises(ValueError,match='仅支持 HORIZON-MiniMax'):
        flow.submit(dict(kind='reference',asset_id='0'*32))
    assert not flow.list('jobs')
    flow.close()
