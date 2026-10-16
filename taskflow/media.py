"""Read-only video/MCAP/snapshot adapters with traceable sampled images."""
import bisect
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import uuid

from PIL import Image

VIDEO_EXTENSIONS={'.mp4','.mov','.mkv','.webm','.avi','.m4v'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class Media:
    def __init__(self,library,root):
        self.library=library;self.root=Path(root);self.frame_root=self.root/'frames';self.frame_root.mkdir(parents=True,exist_ok=True)

    def describe(self,source):
        if not isinstance(source,dict):raise ValueError('请选择范本视频或已有采集记录')
        if source.get('kind')=='video':
            path=Path(str(source.get('path',''))).expanduser().resolve()
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:raise ValueError('视频路径无效，支持MP4、MOV、MKV、WebM、AVI')
            try:
                process=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                    'format=duration:stream=width,height,avg_frame_rate,duration','-of','json',str(path)],
                    capture_output=True,timeout=25,check=True)
                info=json.loads(process.stdout);stream=info['streams'][0]
                duration=float(info.get('format',{}).get('duration') or stream['duration'])
            except (OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError):
                raise ValueError('无法读取视频信息，请检查文件格式和ffprobe') from None
            if not math.isfinite(duration) or not .2<=duration<=3600:raise ValueError('首版支持0.2秒至60分钟的视频；长视频请按任务拆分')
            st=path.stat();fp=digest(dict(path=str(path),size=st.st_size,mtime_ns=st.st_mtime_ns))
            return dict(kind='video',path=str(path),name=path.name,duration_s=duration,width=stream['width'],height=stream['height'],
                        source_fingerprint=fp,camera='video',timing='ffmpeg_seek_position',crop='full')
        if source.get('kind')!='recording':raise ValueError('未知媒体来源')
        ep=str(source.get('id',''));camera=str(source.get('camera',''))
        lib=self.library
        if ep in lib.order:
            ref=lib.ref(ep);info=lib.info(ref)
            if info.get('error'):raise ValueError('当前采集记录不可读取')
            camera=camera or ('head' if 'head' in info['cameras'] else next(iter(info['cameras']),''))
            if camera not in info['cameras']:raise ValueError('采集记录中没有所选相机')
            index=lib.frame_store.index(ep)
            if not index['cameras'][camera]['times']:raise ValueError('当前相机没有图像')
            return dict(kind='recording',id=ep,name=ref.episode_id or ref.name,camera=camera,duration_s=info['duration_s'],
                        source_fingerprint=digest(dict(file=lib.fingerprint(ref),camera=camera)),snapshot=False,
                        crop='left' if camera=='head' and info.get('head_camera_mode')=='stereo_sbs' else 'full',timing='mcap_log_time')
        row=lib.task_audit.episode(ep);folder=lib.task_audit.root/'episodes'/ep
        meta=json.loads((folder/'meta.json').read_text());images=self.snapshot_images(folder,row['duration_s'])
        if not images:raise ValueError('快照没有可分析画面')
        fp=digest(dict(meta_sha=hashlib.sha256((folder/'meta.json').read_bytes()).hexdigest(),
                       images=[(p.name,p.stat().st_size,p.stat().st_mtime_ns) for _,p in images]))
        return dict(kind='recording',id=ep,name=row['name'],camera='ego_view' if row['domain']=='sim' else 'head',
                    duration_s=row['duration_s'],source_fingerprint=fp,snapshot=True,
                    crop='full' if row['domain']=='sim' else 'left',timing='cached_sample_time',cached_frames=len(images))

    @staticmethod
    def snapshot_images(folder,duration):
        files=sorted((folder/'frames').glob('*.jpg'))
        result=[(int(p.stem)*.5,p) for p in files if p.stem.isdigit()]
        if result:return result
        files=sorted(folder.glob('frame_*.jpg'))
        return [(i/max(1,len(files)-1)*max(0,duration-.15),p) for i,p in enumerate(files)]

    def unchanged(self,asset):
        current=self.describe(asset['source'])
        if current['source_fingerprint']!=asset['source']['source_fingerprint']:
            raise ValueError('原视频或采集快照已变化，请重新导入后分析')

    def camera_names(self,asset):
        source=asset['source']
        if source['kind']=='recording' and not source.get('snapshot'):
            return list(self.library.frame_store.index(source['id'])['cameras'])
        return [source['camera']]

    def frame(self,asset,seconds,camera=None):
        source=dict(asset['source']);seconds=float(seconds)
        camera=camera or source['camera']
        if camera!=source['camera']:
            if camera not in self.camera_names(asset):raise ValueError('录像中没有该相机')
            source['camera']=camera;source['crop']='left' if camera=='head' and self.library.info(self.library.ref(source['id'])).get('head_camera_mode')=='stereo_sbs' else 'full'
        if not math.isfinite(seconds) or not 0<=seconds<=source['duration_s']:raise ValueError('图像时间超出视频范围')
        actual=seconds;payload=None
        if source['kind']=='recording' and source.get('snapshot'):
            folder=self.library.task_audit.root/'episodes'/source['id']
            images=self.snapshot_images(folder,source['duration_s']);actual,path=min(images,key=lambda x:abs(x[0]-seconds))
            payload=path.read_bytes()
        elif source['kind']=='recording':
            index=self.library.frame_store.index(source['id']);times=index['cameras'][source['camera']]['times']
            target=index['start_ns']+round(seconds*1e9);i=bisect.bisect_left(times,target);i=min(i,len(times)-1)
            if i and abs(times[i-1]-target)<abs(times[i]-target):i-=1
            header,images=self.library.frame_store.batch(source['id'],source['camera'],i,1,index['token'])
            actual=header['frames'][0]['time_s'];payload=images[0]
        else:
            actual=min(seconds,max(0,source['duration_s']-.05))
        identity=dict(asset=asset['id'],source=source['source_fingerprint'],time=round(actual,6),crop=source['crop'],size=640)
        if camera!=asset['source']['camera']:identity['camera']=camera
        key=digest(identity)[:32]
        path=self.frame_root/(key+'.jpg')
        if not path.exists():
            if payload is None:
                try:
                    r=subprocess.run(['ffmpeg','-v','error','-ss',f'{actual:.6f}','-i',source['path'],
                        '-frames:v','1','-vf','scale=640:640:force_original_aspect_ratio=decrease','-f','image2pipe','-vcodec','mjpeg','pipe:1'],
                        capture_output=True,timeout=25,check=True)
                    payload=r.stdout
                except (OSError,subprocess.SubprocessError):raise ValueError('视频抽帧失败') from None
            try:
                with Image.open(io.BytesIO(payload)) as im:
                    if source['crop']=='left':im=im.crop((0,0,im.width//2,im.height))
                    im.thumbnail((640,640));out=io.BytesIO();im.convert('RGB').save(out,'JPEG',quality=85)
                tmp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');tmp.write_bytes(out.getvalue());tmp.replace(path)
            except (ValueError,OSError):raise ValueError('当前时刻图像无法解码') from None
        return dict(id=key,time_s=round(actual,6),path=str(path),url='/api/taskflow/frame?id='+key,
                    timestamp_kind=source['timing'],role='target',camera=camera)

    def sample(self,asset,start=0.,end=None,budget=48,fps=1.):
        source=asset['source'];end=source['duration_s'] if end is None else float(end);start=float(start)
        if not 0<=start<end<=source['duration_s']+.0001:raise ValueError('分析范围超出视频')
        n=min(int(budget),max(2,int(math.ceil((end-start)*fps))+1));frames=[];seen=set();missing=[]
        for i in range(n):
            time=start+(end-start)*i/max(1,n-1)
            try:
                f=self.frame(asset,min(time,source['duration_s']))
                if f['id'] not in seen:frames.append(f);seen.add(f['id'])
            except ValueError:missing.append(round(time,3))
        if len(frames)<2:raise ValueError('可解码画面不足，无法分析完整动作过程')
        return frames,dict(requested=n,provided=len(frames),unreadable_times_s=missing,
                           max_sample_gap_s=round(max(b['time_s']-a['time_s'] for a,b in zip(frames,frames[1:])),4),
                           start_s=start,end_s=end,timestamp_kind=source['timing'])

    def sample_guided(self,asset,evidence,start=0.,end=None,budget=16,core=None):
        end=asset['duration_s'] if end is None else min(float(end),asset['duration_s'])
        if not evidence.available:
            frames,coverage=self.sample(asset,start,end,budget=budget,fps=4. if core else 1.)
            coverage.update(strategy='uniform_no_state',state_reason=evidence.reason)
            return frames,coverage
        cameras=self.camera_names(asset);primary=asset['source']['camera']
        other=[c for c in cameras if c!=primary]
        side_energy={side:sum(e['magnitude'] for e in evidence.events if e.get('side')==side and e['start_s']<end and e['end_s']>start) for side in ('left','right')}
        other.sort(key=lambda c:-side_energy.get(c.split('_')[0],0))
        secondary_budget=min(4,budget//3) if other else 0
        times=evidence.key_times(start,end,budget-secondary_budget,core)
        requested=[(primary,t) for t in times]
        anchors=evidence.key_times(start,end,max(2,secondary_budget),core)
        for i in range(secondary_budget):requested.append((other[0] if i<secondary_budget-1 or len(other)==1 else other[1],anchors[min(i,len(anchors)-1)]))
        frames=[];seen=set();missing=[]
        for camera,t in requested:
            try:
                frame=self.frame(asset,min(end,max(start,t)),camera)
                if not start-.001<=frame['time_s']<=end+.001:continue
                if frame['id'] not in seen:
                    frame['view_label']=camera;frame['selection']='state_guided';frames.append(frame);seen.add(frame['id'])
            except ValueError:missing.append(dict(camera=camera,time_s=round(t,3)))
        if len(frames)<2:raise ValueError('可解码画面不足，无法分析动作过程')
        primary_times=sorted(f['time_s'] for f in frames if f['camera']==primary)
        coverage=dict(strategy='state_guided_multiview',requested=len(requested),provided=len(frames),unreadable_times_s=missing,
            start_s=start,end_s=end,max_sample_gap_s=round(max((b-a for a,b in zip(primary_times,primary_times[1:])),default=end-start),4),
            cameras=sorted(set(f['camera'] for f in frames)),timestamp_kind=asset['source']['timing'],primary_camera=primary,
            observation_tail_s=round(max(0,end-max(f['time_s'] for f in frames)),3),state_version=evidence.summary(start,end)['version'])
        return sorted(frames,key=lambda f:(f['time_s'],f['camera'])),coverage
