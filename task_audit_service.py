"""Read-only local task audit snapshots, independent of original recording paths."""
import io
import json
import math
from pathlib import Path
import re
from curation.bridge import project_quality
from storage import Store
from PIL import Image

class TaskAuditService:
    def __init__(self,root):self.root=Path(root)

    def catalog(self):
        path=self.root/'audit.json'
        if not path.is_file():return dict(episodes=[],message='尚未导入任务评分快照')
        result=json.loads(path.read_text())
        curation_path=self.root/'curation.json'
        curation=json.loads(curation_path.read_text()) if curation_path.is_file() else {}
        result['curation']={k:v for k,v in curation.items() if k!='episodes'}
        for row in result['episodes']:
            row['curation']=curation.get('episodes',{}).get(row['id'],dict(grade='U',grade_label='未纳入比较',score=None,reason='任务或状态动作数据尚未核实'))
            automatic=self.root/'episodes'/row['id']/'automatic_task.json'
            if row['domain']=='real' and automatic.is_file():
                row['visual_review']=row['task']
                row['task']=json.loads(automatic.read_text())
        return result

    def curation(self):
        path=self.root/'curation.json'
        return json.loads(path.read_text()) if path.is_file() else dict(episodes={})

    def workbench_records(self):
        path=self.root/'catalog.json'
        if not path.is_file():return []
        audit={r['id']:r for r in self.catalog()['episodes']};result=[]
        for original in json.loads(path.read_text())['episodes']:
            row=dict(original);entry=audit[row['id']];c=entry['curation'];directory=self.root/'episodes'/row['id']
            ready=(directory/'meta.json').is_file() and (directory/'series.bin').is_file()
            camera='ego_view' if entry['domain']=='sim' else 'head'
            row.update(snapshot=True,domain=entry['domain'],curation=c,task_admission=c.get('reason'),quality=project_quality(original.get('quality',{}),c),review=Store.empty(),review_stale=False,effective_grade=c.get('grade','U'),cache='ready' if ready else 'snapshot',cache_message='本机只读证据快照',head_camera_mode='mono',cameras={camera:dict(rate_hz=2,topic='本机缓存抽帧')} if entry['has_frames'] else {},readiness=dict(ready=False,blockers=['当前为本机证据快照，原始文件未导入，不能创建训练数据包']))
            result.append(row)
        return result

    def has_snapshot(self,ep):
        path=self.root/'catalog.json'
        return path.is_file() and any(r['id']==ep for r in json.loads(path.read_text())['episodes'])

    def signal_bytes(self,ep,kind):
        self.episode(ep)
        return (self.root/'episodes'/ep/('meta.json' if kind=='meta' else 'series.bin')).read_bytes()

    def episode(self,ep):
        if not re.fullmatch(r'[a-f0-9]{12}',ep):raise ValueError('记录 ID 无效')
        row=next((row for row in self.catalog()['episodes'] if row['id']==ep),None)
        if row is None:raise KeyError('任务记录不存在')
        return row

    def frame(self,ep,seconds):
        row=self.episode(ep)
        if not math.isfinite(seconds) or seconds<0 or seconds>row['duration_s']+.1:raise ValueError('时间超出记录范围')
        directory=self.root/'episodes'/ep
        detections=directory/'object_detections.json'
        exact=None
        if detections.is_file():
            for observation in json.loads(detections.read_text()).get('observations',[]):
                name=observation.get('file','')
                if abs(observation['time_s']-seconds)<=.02 and re.fullmatch(r'(frame_[0-9]{2}|frames/[0-9]{5})\.jpg',name):
                    exact=directory/name
                    break
        files=sorted((directory/'frames').glob('*.jpg'))
        if exact is not None:
            path=exact
        elif files:
            target=int(round(seconds*2))
            path=min(files,key=lambda p:abs(int(p.stem)-target))
        else:
            index=round(seconds/max(.001,row['duration_s']-.15)*8)
            path=directory/f'frame_{max(0,min(8,index)):02}.jpg'
        with Image.open(path) as im:
            if row['domain']!='sim':im=im.crop((0,0,im.width//2,im.height))
            im.thumbnail((960,640));out=io.BytesIO();im.convert('RGB').save(out,format='JPEG',quality=90)
            return out.getvalue()

    def curve(self,ep):
        self.episode(ep)
        path=self.root/'episodes'/ep/'warp.json'
        if not path.is_file():return dict(state='unavailable',reason='未生成当前任务的进度模型结果')
        return json.loads(path.read_text())

    def objects(self,ep):
        self.episode(ep)
        path=self.root/'episodes'/ep/'object_detections.json'
        return json.loads(path.read_text()) if path.is_file() else dict(observations=[])
