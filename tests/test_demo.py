"""Portable MCAP-to-review-to-export coverage; uses no laboratory recordings."""
import io,json,hashlib,zipfile
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from scripts.create_demo import create_demo
from studio import StudioLibrary
from exporter import build_bundle

@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    folder=tmp_path_factory.mktemp('public-demo')
    path=create_demo(folder/'recordings')
    lib=StudioLibrary(folder/'workspace');lib.add_root(path)
    ep=lib.order[0];lib.build_now(ep)
    yield lib,ep,path
    lib.progress_service.close();lib.pool.shutdown();lib.export_pool.shutdown()

def test_demo_is_labelled_synthetic_and_has_no_success_claim(demo):
    lib,ep,path=demo;row=lib.record(lib.ref(ep))
    meta=json.loads((path.parent.parent/'episode_meta.json').read_text())
    assert meta['synthetic'] is True and meta['generated_by']=='robocurate-synthetic-v1'
    assert row['outcome'] is None and '合成' in row['source_instruction']
    assert len(row['cameras'])==3 and row['quality']['rating']['max_score']==10
    assert row['quality']['rating']['score'] is None  # Synthetic motion is not a task acceptance result.
    assert row['quality']['suggested_grade']=='U'
    with Image.open(io.BytesIO(lib.frame_at(ep,'head',1))) as image:assert image.size==(640,360)

def test_demo_detects_known_motion_offset_and_camera_gap(demo):
    lib,ep,_=demo;events=lib.diagnostics(ep)['events']
    assert any(e['kind']=='tracking' and e['joint_index']==19 and 1.7<e['start_s']<1.9 for e in events)
    assert any(e['kind']=='gap' and 2.9<e['start_s']<3.1 and e['end_s']>=3.4 for e in events)

def test_demo_review_export_roundtrip_keeps_ten_point_scale(demo,monkeypatch):
    lib,ep,path=demo;before=hashlib.sha256(path.read_bytes()).hexdigest()
    review=lib.validate_review(ep,dict(revision=0,grade='B',instruction='将黄色方块从左桌移至右侧容器，合成演示。',
        segments=[dict(start=.5,end=1.5,label='合成样例中的有效片段')]))
    lib.store.save_many([(ep,review)])
    # Exercise the legacy exporter with explicit test-only admission. Neither a
    # synthetic recording nor a human grade alone creates an automatic score.
    with pytest.raises(ValueError,match='未通过任务准入'):
        build_bundle(lib,[lib.record(lib.ref(ep))],dict(kind='dataset'),lib.export_root,{'id':'blocked_export'})
    monkeypatch.setattr(lib.task_audit,'curation',lambda:dict(episodes={ep:dict(grade='B',score=5,reason='synthetic test fixture')}))
    job={'id':'synthetic_export','state':'running'}
    result=build_bundle(lib,[lib.record(lib.ref(ep))],dict(kind='dataset',fps=30,validation_ratio=0,seed=42),lib.export_root,job)
    with zipfile.ZipFile(lib.export_root/result['file']) as archive:
        record=json.loads(archive.read('manifest.json'))['episodes'][0]
        assert record['quality']['rating']['max_score']==10
        assert 0<=record['quality']['score']<=10
        assert archive.read('README.txt').decode().startswith('RoboCurate')
        clip=record['clips'][0]
        with np.load(io.BytesIO(archive.read(clip['path']+'/samples.npz')),allow_pickle=False) as values:
            assert values['action'].shape==(30,41) and values['valid'].all()
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before

def test_demo_generator_refuses_unidentified_existing_recording(tmp_path):
    path=tmp_path/'synthetic_pick_place/episode_000001/mcap/demo.mcap'
    path.parent.mkdir(parents=True);path.write_bytes(b'original')
    with pytest.raises(FileExistsError):create_demo(tmp_path)
    assert path.read_bytes()==b'original'
