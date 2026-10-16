#!/usr/bin/env python3
"""RoboCurate — localhost curation app, built on the supplied MCAP viewer."""
import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import math
import os
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import uuid

import numpy as np
from mcap.reader import make_reader
import server as viewer
from extract import CACHE_VERSION
from quality import probe, assess, DEFAULT_RULES, RULE_LABELS
from storage import Store, Conflict, now
from exporter import build_bundle, preflight, concrete_instruction
from diagnostics import build_diagnostics, VERSION as DIAGNOSTICS_VERSION, CACHE_SCHEMA_VERSION
from frames import FrameStore
from quality_evidence import native_reference_checks, VERSION as REFERENCE_CHECK_VERSION
from trajectories import build_trajectories, VERSION as TRAJECTORY_VERSION
from progress_service import ProgressService
from task_audit_service import TaskAuditService
from curation.bridge import project_quality
from execution_quality import ExecutionQualityService
from taskflow.service import TaskflowService
from taskflow import http as taskflow_http

APP=Path(__file__).resolve().parent


class StudioLibrary(viewer.Library):
    def __init__(self, workspace):
        workspace.mkdir(parents=True, exist_ok=True)
        super().__init__(workspace/'cache',100)
        self.workspace=workspace
        self.store=Store(workspace/'reviews.sqlite3')
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='decode')
        self.export_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='export')
        self.export_jobs={}
        self.probes={}; self.qcs={}; self.frames=OrderedDict(); self.frame_lock=threading.Lock()
        self.export_root=workspace/'exports';self.export_root.mkdir(exist_ok=True)
        self.diagnostics_memo={}
        self.diagnostics_lock=threading.Lock()
        self.frame_store=FrameStore(self)
        self.reference_memo={}
        self.trajectory_memo=OrderedDict()
        self.trajectory_lock=threading.Lock()
        self.progress_service=ProgressService(self)
        self.task_audit=TaskAuditService(self.workspace/'task-audit')
        self.execution_quality=ExecutionQualityService(self)
        self.taskflow=TaskflowService(self)

    def trajectories(self,ep,robot):
        if robot is None:raise ValueError('缺少机器人结构描述')
        ref=self.ref(ep)
        if self.state(ep)['state']!='ready':raise ValueError('请先完成该记录的解析')
        cache=self.cache_dir(ref)
        def signature():
            return (TRAJECTORY_VERSION,robot.etag,(cache/'meta.json').stat().st_mtime_ns,
                    (cache/'native.npz').stat().st_mtime_ns,json.dumps(self.fingerprint(ref),sort_keys=True))
        key=signature()
        with self.trajectory_lock:
            hit=self.trajectory_memo.get(ep)
            if hit and hit[0]==key:return hit[1]
            meta=json.loads((cache/'meta.json').read_text())
            with np.load(cache/'native.npz',allow_pickle=False) as native:
                result=build_trajectories(native,meta,robot.desc)
            if key!=signature():raise Conflict('数据已变化，请重新读取轨迹')
            result['source']=self.fingerprint(ref)
            self.trajectory_memo[ep]=(key,result)
            while len(self.trajectory_memo)>4:self.trajectory_memo.popitem(last=False)
            return result

    def rules(self):
        return {**DEFAULT_RULES,**self.store.setting('rules',{})}

    def diagnostics(self,ep):
        ref=self.ref(ep)
        if self.state(ep)['state']!='ready':
            raise ValueError('请先完成该记录的深度解析')
        cache=self.cache_dir(ref);rules=self.rules()
        import hashlib
        key=hashlib.sha256(json.dumps(dict(rules=rules,version=DIAGNOSTICS_VERSION,schema=CACHE_SCHEMA_VERSION,
                                          meta_mtime=(cache/'meta.json').stat().st_mtime_ns),sort_keys=True).encode()).hexdigest()[:16]
        with self.diagnostics_lock:
            hit=self.diagnostics_memo.get(ep)
            if hit and hit[0]==key:return hit[1]
            path=cache/('diagnostics-'+key+'.json')
            if path.exists():
                result=json.loads(path.read_text())
            else:
                result=build_diagnostics(cache,rules)
                tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False));tmp.replace(path)
            self.diagnostics_memo[ep]=(key,result)
            return result

    def info(self, ref):
        try:
            stat=ref.path.stat(); fingerprint=(stat.st_size,stat.st_mtime_ns)
        except OSError:
            fingerprint=(0,0)
        hit=self.probes.get(ref.id)
        if not hit or hit[0]!=fingerprint:
            hit=(fingerprint,probe(ref));self.probes[ref.id]=hit
        return hit[1]

    def reference_checks(self,ep):
        ref=self.ref(ep)
        if self.state(ep)['state']!='ready':raise ValueError('请先完成深度质检')
        cache=self.cache_dir(ref)
        key=(REFERENCE_CHECK_VERSION,(cache/'meta.json').stat().st_mtime_ns,json.dumps(self.fingerprint(ref),sort_keys=True))
        hit=self.reference_memo.get(ep)
        if hit and hit[0]==key:return hit[1]
        meta=json.loads((cache/'meta.json').read_text())
        with np.load(cache/'native.npz',allow_pickle=False) as native:result=native_reference_checks(native,meta)
        if key!=(REFERENCE_CHECK_VERSION,(cache/'meta.json').stat().st_mtime_ns,json.dumps(self.fingerprint(ref),sort_keys=True)):
            raise Conflict('源数据或解析结果已变化，请重新载入参考检查')
        self.reference_memo[ep]=(key,result)
        return result

    def fingerprint(self,ref):
        s=ref.path.stat();return dict(size=s.st_size,mtime_ns=s.st_mtime_ns)

    def state(self, ep_id):
        state=super().state(ep_id)
        if state['state']=='ready':
            ref=self.ref(ep_id);cache=self.cache_dir(ref)
            try:
                m=json.loads((cache/'meta.json').read_text());s=ref.path.stat()
                if m['cache_version']!=CACHE_VERSION or m['source'].get('mtime_ns')!=s.st_mtime_ns or m['source']['size_bytes']!=s.st_size or not (cache/'native.npz').exists():
                    return dict(state='absent',message='源文件或缓存版本已改变，需要重新解析')
            except (OSError,ValueError,KeyError):
                return dict(state='absent',message='缓存不可用，需要重新解析')
        return state

    def prepare(self,ep_id,rebuild=False):
        ref=self.ref(ep_id)
        with self._lock:
            if self.jobs.get(ep_id,{}).get('state')=='building':return dict(self.jobs[ep_id])
        if not rebuild and self.state(ep_id)['state']=='ready':return dict(state='ready',message='')
        with self._lock:
            if self.jobs.get(ep_id,{}).get('state')=='building':return dict(self.jobs[ep_id])
            job=dict(state='building',message='排队等待解析',started=time.time())
            self.jobs[ep_id]=job
            self.pool.submit(self._build,ref,job)
        return dict(job)

    def _build(self,ref,job):
        self.resident.pop(ref.id,None)
        super()._build(ref,job)
        self.qcs.pop(ref.id,None)
        self.diagnostics_memo.pop(ref.id,None)

    def episode(self,ep_id):
        state=self.state(ep_id)
        if state['state']!='ready':
            self.resident.pop(ep_id,None)
            raise viewer.NotReady({**state,'ep':ep_id})
        return super().episode(ep_id)

    def record(self,ref,reviews=None):
        info=self.info(ref);cache=self.cache_dir(ref);state=self.state(ref.id)
        rules=self.rules()
        stamp=(cache/'meta.json').stat().st_mtime_ns if (cache/'meta.json').exists() and state['state']=='ready' else 0
        key=(json.dumps(rules,sort_keys=True),stamp,self.probes[ref.id][0])
        hit=self.qcs.get(ref.id)
        if not hit or hit[0]!=key:
            # An old or still-building cache must not be advertised as fresh QC.
            qc=assess(ref,info,cache if stamp else cache/'not-ready',rules)
            hit=(key,qc);self.qcs[ref.id]=hit
        curation=self.task_audit.curation().get('episodes',{}).get(ref.id)
        quality=project_quality(hit[1],curation)
        review=(reviews if reviews is not None else self.store.all()).get(ref.id,Store.empty())
        stale=bool(review['grade'] and review.get('source_fingerprint')!=dict(zip(['size','mtime_ns'],self.probes[ref.id][0])))
        blockers=[]
        if not review['grade']:blockers.append('待人工分级')
        elif review['grade'] not in ('A','B'):blockers.append('人工等级未纳入训练')
        if not concrete_instruction(review.get('instruction') or info.get('source_instruction')):blockers.append('待补任务指令')
        if state['state']!='ready':blockers.append('待深度解析')
        if stale:blockers.append('源文件变更，待重新审核')
        if hit[1]['grading']['grade']=='D':blockers.append('自动数据等级 D，当前数据不可用')
        if quality['grading']['grade'] not in ('A','B','C'):blockers.append('未通过当前任务准入，不能作为完整演示入选')
        return {**ref.to_json(),**info,'curation':curation,'quality':quality,'review':review,'review_stale':stale,
                'readiness':dict(ready=not blockers,blockers=blockers),
                'cache':state['state'],'cache_message':state.get('message',''),
                'effective_grade':review['grade'] or quality['suggested_grade']}

    def catalog(self):
        reviews=self.store.all()
        with self._lock: ids=list(self.order)
        episodes=[self.record(self.ref(ep),reviews) for ep in ids]
        episodes.extend(r for r in self.task_audit.workbench_records() if r['id'] not in ids)
        return dict(episodes=episodes,curation={k:v for k,v in self.task_audit.curation().items() if k!='episodes'},roots=[str(p) for p in self.roots],workspace=str(self.workspace),
                    counts=dict(total=len(episodes),reviewed=sum(bool(e['review']['grade']) for e in episodes),
                                ready=sum(e['cache']=='ready' for e in episodes),success=sum(e['outcome'] is True for e in episodes)))

    def rescan(self):
        """Re-read every known root so recordings written since startup appear.

        `add_root` is idempotent, so re-scanning merges new files; episodes whose
        file has since been deleted are dropped so the list keeps matching disk.
        """
        before=set(self.refs);missing=[]
        for path in list(self.roots):
            try:self.add_root(path)
            except OSError as e:missing.append(f'{path}：{e}')
        with self._lock:
            gone=[ep for ep,ref in self.refs.items() if not ref.path.exists()]
            for ep in gone:
                for memo in (self.refs,self.resident,self.probes,self.qcs,
                             self.diagnostics_memo,self.reference_memo,self.trajectory_memo):
                    memo.pop(ep,None)
            if gone:self.order=[ep for ep in self.order if ep not in set(gone)]
            if self.default_id not in self.refs:self.default_id=self.order[0] if self.order else None
        return dict(added=len(set(self.refs)-before),removed=len(gone),missing=missing,total=len(self.order))

    def frame_at(self,ep,cam,seconds):
        ref=self.ref(ep);info=self.info(ref)
        desc=info['cameras'].get(cam)
        if not desc: raise KeyError('相机通道不存在')
        ts=info['start_ns']+int(seconds*1e9)
        key=(ep,cam,round(seconds,3),self.probes[ep][0])
        with self.frame_lock:
            if key in self.frames:return self.frames[key]
        with ref.path.open('rb') as f:
            messages=list(make_reader(f).iter_messages(topics=[desc['topic']],start_time=max(info['start_ns'],ts-150_000_000),end_time=min(info['end_ns']+1,ts+150_000_001)))
        if not messages: raise KeyError('此时刻附近没有图像帧')
        msg=min(messages,key=lambda m:abs(m[2].log_time-ts))[2]
        payload=viewer._jpeg_payload(msg.data)
        if not payload:raise ValueError('相机帧不是有效 JPEG')
        with self.frame_lock:
            self.frames[key]=payload
            while len(self.frames)>80:self.frames.popitem(last=False)
        return payload

    def capture_event_evidence(self,ep,decisions,trusted_evidence=None):
        previous=self.store.all().get(ep,Store.empty()).get('event_evidence',{})
        known={**previous,**(trusted_evidence or {})}
        evidence={key:known[key] for key in decisions if key in known}
        missing=[key for key in decisions if key not in evidence or evidence[key].get('unresolved')]
        if missing and self.state(ep)['state']=='ready':
            diagnostics=self.diagnostics(ep)
            by_id={event['id']:event for event in diagnostics['events']}
            for key in missing:
                if key in by_id:
                    evidence[key]=dict(event=by_id[key],rules=diagnostics['rules'],signature=diagnostics['signature'],
                                       diagnostics_version=diagnostics['version'],source=diagnostics['source'])
        for key in decisions:
            if key not in evidence:
                evidence[key]=dict(unresolved=True,reason='未找到对应版本的事件证据；仅保留人工判断，不推断依据。')
        # A browser draft can outlive a rule edit. Recover its exact historical
        # basis from our derived cache instead of assigning today's thresholds.
        missing={key for key in decisions if evidence[key].get('unresolved')}
        if missing:
            cache=self.cache_dir(self.ref(ep))
            for path in sorted(cache.glob('diagnostics-*.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True):
                try:
                    historical=json.loads(path.read_text())
                    source=historical.get('source')
                    if not source:continue
                    for event in historical.get('events',[]):
                        key=event['id']
                        if key not in missing:continue
                        evidence[key]=dict(event=event,rules=historical['rules'],signature=historical['signature'],
                                           diagnostics_version=historical['version'],source=source)
                        missing.remove(key)
                    if not missing:break
                except (ValueError,OSError,KeyError):continue
        return evidence

    def validate_review(self,ep,body,*,trusted_evidence=None):
        self.ref(ep)
        if not isinstance(body,dict):raise ValueError('标注格式错误')
        if not isinstance(body.get('revision'),int) or isinstance(body['revision'],bool):raise ValueError('缺少标注版本号')
        patch={'revision':body['revision']}
        if 'grade' in body:
            if body['grade'] not in ('','A','B','C','D'):raise ValueError('分级无效')
            patch['grade']=body['grade']
        for field,limit in [('note',10000),('instruction',2000)]:
            if field in body:
                if not isinstance(body[field],str) or len(body[field])>limit:raise ValueError('文本字段过长或格式错误')
                patch[field]=body[field].strip()
        if 'tags' in body:
            if not isinstance(body['tags'],list) or len(body['tags'])>30 or any(not isinstance(t,str) or len(t)>80 for t in body['tags']):raise ValueError('问题标签格式错误')
            patch['tags']=list(dict.fromkeys(body['tags']))
        if 'event_decisions' in body:
            decisions=body['event_decisions']
            if not isinstance(decisions,dict) or len(decisions)>2000:
                raise ValueError('问题复核记录格式错误')
            for key,value in decisions.items():
                if not isinstance(key,str) or len(key)!=20 or any(c not in '0123456789abcdef' for c in key) or value not in ('confirmed','accepted'):
                    raise ValueError('问题复核状态无效')
            patch['event_decisions']=decisions
            # Evidence is captured by the server, never trusted from a browser
            # payload. A history restore may use its own saved server snapshot.
            patch['event_evidence']=self.capture_event_evidence(ep,decisions,trusted_evidence)
        if 'segments' in body:
            segments=body['segments'];duration=self.info(self.ref(ep))['duration_s']
            if not isinstance(segments,list) or len(segments)>100:raise ValueError('片段数超限')
            clean=[]
            for s in segments:
                if not isinstance(s,dict):raise ValueError('片段格式错误')
                a=float(s['start']);b=float(s['end'])
                if not math.isfinite(a+b) or not 0<=a<b<=duration+0.0001 or b-a<0.1:raise ValueError('片段必须位于记录内，且至少 0.1 秒')
                label=s.get('label','可用片段');grade=s.get('grade',body.get('grade','B') or 'B')
                if not isinstance(label,str) or len(label)>200 or grade not in ('A','B','C','D'):raise ValueError('片段标签或等级无效')
                clean.append(dict(start=a,end=min(b,duration),label=label,grade=grade))
            clean.sort(key=lambda s:s['start'])
            if any(b['start']<a['end'] for a,b in zip(clean,clean[1:])):raise ValueError('保留片段不能相互重叠')
            patch['segments']=clean
        patch['source_fingerprint']=self.fingerprint(self.ref(ep))
        return patch

    def export_records(self,body):
        ids=body.get('ids',[])
        if not isinstance(ids,list) or not ids or len(ids)>2000:raise ValueError('请先选择要导出的记录')
        return [self.record(self.ref(ep)) for ep in dict.fromkeys(ids)]

    def preflight(self,body):
        return preflight(self,self.export_records(body),body)

    def restore_review(self,body):
        ep=body['ep'];revision=body['revision'];seq=body['seq']
        entry=next((r for r in self.store.history(ep) if r['seq']==seq),None)
        if entry is None:raise ValueError('审核历史不存在')
        snapshot={**Store.empty(),**entry['after']}
        if snapshot['grade'] and snapshot.get('source_fingerprint')!=self.fingerprint(self.ref(ep)):
            raise ValueError('历史标注对应的源文件已变化，不能自动恢复分级')
        patch=self.validate_review(ep,{**snapshot,'revision':revision},trusted_evidence=snapshot.get('event_evidence',{}))
        return self.store.save_many([(ep,patch)])

    def persist_job(self,job):
        path=self.export_root/(job['id']+'.json')
        tmp=path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(job,ensure_ascii=False));tmp.replace(path)

    def recover_jobs(self):
        for path in self.export_root.glob('export_*.json'):
            try:
                job=json.loads(path.read_text())
                if job.get('state') not in ('queued','running'):continue
                pid=job.get('owner_pid')
                if pid:
                    try:os.kill(int(pid),0);continue
                    except ProcessLookupError:pass
                    except PermissionError:continue
                job.update(state='error',message='上次导出被中断；原始数据与标注保持完整，请重新创建导出任务。')
                self.persist_job(job)
            except (ValueError,OSError):continue

    def export(self,body):
        records=self.export_records(body)
        options={k:body[k] for k in ['kind','fps','validation_ratio','seed'] if k in body}
        if options.get('kind') not in ('manifest','dataset'):raise ValueError('请选择导出格式')
        report=preflight(self,records,options)
        if not report['ready']:
            raise ValueError('导出预检未通过：'+'；'.join(r['name']+'：'+'、'.join(r['blockers']) for r in report['records'] if r['blockers']))
        if options['kind']=='dataset':
            if any(r['review_stale'] for r in records):raise ValueError('源文件发生变化，请重新审核后再导出')
            if any(r['review']['grade'] not in ('A','B') for r in records):raise ValueError('训练包仅允许人工审核为 A / B 的记录；其他记录可以导出筛选清单')
            if any(r['cache']!='ready' for r in records):raise ValueError('请先完成所选记录的深度质检')
        job=dict(id='export_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6],state='queued',progress=0,message='等待导出',created_at=now(),owner_pid=os.getpid(),kind=options['kind'])
        self.export_jobs[job['id']]=job
        self.persist_job(job)
        def work():
            try:
                job['state']='running';self.persist_job(job);result=build_bundle(self,records,options,self.export_root,job)
                job.update(state='done',progress=100,message='导出完成',**result)
            except Exception as e:
                job.update(state='error',message=str(e))
            finally:
                self.persist_job(job)
        self.export_pool.submit(work)
        return dict(job)

    def exports(self):
        result={}
        for p in self.export_root.glob('export_*.json'):
            try:
                d=json.loads(p.read_text());result[d['id']]=d
            except (ValueError,OSError):pass
        result.update(self.export_jobs)
        return sorted(result.values(),key=lambda j:j['id'],reverse=True)


class Handler(viewer.Handler):
    def end_headers(self):
        if not urlparse(self.path).path.startswith('/api/'):
            self.send_header('Cache-Control','no-cache')
        super().end_headers()

    def _body_json(self):
        length=int(self.headers.get('Content-Length') or 0)
        if not 0<length<=2_000_000:raise ValueError('请求内容为空或超过 2MB')
        data=json.loads(self.rfile.read(length))
        if not isinstance(data,dict):raise ValueError('请求应为 JSON 对象')
        return data

    def _local(self):
        host=self.headers.get('Host','').split(':')[0]
        origin=self.headers.get('Origin')
        if host not in ('127.0.0.1','localhost') or (origin and urlparse(origin).netloc!=self.headers.get('Host')):
            self._json({'error':'仅允许本地同源访问'},status=403);return False
        return True

    def do_POST(self):
        if not self._local():return
        try:
            parsed=urlparse(self.path);route=parsed.path;lib=self.library
            if route=='/api/taskflow/upload':return taskflow_http.upload(self,parse_qs(parsed.query))
            body=self._body_json()
            if route.startswith('/api/taskflow/'):return taskflow_http.post(self,route,body)
            if route=='/api/roots':
                path=Path(str(body.get('path',''))).expanduser()
                if not str(body.get('path','')).strip():raise ValueError('请输入本机数据目录')
                found=lib.add_root(path)
                lib.store.set_setting('roots',[str(p) for p in lib.roots])
                return self._json(dict(**lib.to_json(),added=len(found)))
            if route=='/api/roots/rescan':
                if not lib.roots:raise ValueError('还没有添加数据目录')
                result=lib.rescan()
                if result['missing'] and len(result['missing'])==len(lib.roots):
                    raise ValueError('；'.join(result['missing']))
                return self._json(dict(**result,roots=[str(p) for p in lib.roots]))
            if route=='/api/prepare':
                ep=body.get('ep') or lib.default_id
                return self._json(dict(**lib.prepare(ep,rebuild=bool(body.get('rebuild'))),ep=ep))
            if route=='/api/analyze':
                ids=body.get('ids') or list(lib.order)
                if not isinstance(ids,list):raise ValueError('记录列表无效')
                for ep in ids:lib.ref(ep)
                return self._json(dict(jobs={ep:lib.prepare(ep,rebuild=bool(body.get('rebuild'))) for ep in ids}))
            if route=='/api/reviews':
                changes=body.get('changes',[])
                if not isinstance(changes,list) or not changes:raise ValueError('没有要保存的标注')
                if len({c['id'] for c in changes})!=len(changes):raise ValueError('记录重复')
                patches=[(c['id'],lib.validate_review(c['id'],c['review'])) for c in changes]
                return self._json(dict(reviews=lib.store.save_many(patches)))
            if route=='/api/reviews/restore':return self._json(dict(reviews=lib.restore_review(body)))
            if route=='/api/preflight':return self._json(lib.preflight(body))
            if route=='/api/execution-quality/review':return self._json(lib.execution_quality.save(body))
            if route=='/api/progress/jobs':return self._json(lib.progress_service.start(body.get('ep'),body.get('model_id')),status=202)
            if route=='/api/progress/cancel':return self._json(lib.progress_service.cancel(body.get('id')))
            if route=='/api/rules':
                rules=body.get('rules')
                if not isinstance(rules,dict) or set(rules)!=set(DEFAULT_RULES):raise ValueError('质检规则字段不完整')
                rules={k:float(v) for k,v in rules.items()}
                if any(not math.isfinite(v) or v<=0 or v>100000 for v in rules.values()):raise ValueError('阈值需为有效的正数')
                lib.store.set_setting('rules',rules);lib.qcs.clear();lib.diagnostics_memo.clear()
                return self._json(dict(rules=rules))
            if route=='/api/exports':return self._json(lib.export(body),status=202)
            return self._json({'error':'未知请求'},status=404)
        except Conflict as e:self._json({'error':str(e)},status=409)
        except (ValueError,KeyError,TypeError,OSError) as e:self._json({'error':str(e)},status=400)
        except Exception as e:
            import traceback;traceback.print_exc();self._json({'error':str(e)},status=500)

    def do_GET(self):
        if not self._local():return
        try:
            parsed=urlparse(self.path);route=parsed.path;qs=parse_qs(parsed.query);lib=self.library
            if route=='/api/taskflow' or route.startswith('/api/taskflow/'):return taskflow_http.get(self,route,qs)
            if route=='/api/health':return self._json(dict(ok=True,app='RoboCurate',workspace=str(lib.workspace),episodes=len(lib.order)))
            if route=='/api/sim-demo':
                root=lib.workspace/'sim-demo'
                index=json.loads((root/'index.json').read_text())
                ep=qs.get('ep',[''])[0]
                if not ep:return self._json(index,cache='no-store')
                if not any(r['id']==ep for r in index['records']):raise KeyError('没有该仿真演示记录')
                return self._json(json.loads((root/(ep+'.json')).read_text()),cache='no-store')
            if route=='/task-audit.html':
                self.send_response(302);self.send_header('Location','/#library');self.send_header('Content-Length','0');self.end_headers();return
            if route in ('/api/meta','/api/series') and lib.task_audit.has_snapshot(qs.get('ep',[''])[0]) and qs.get('ep',[''])[0] not in lib.order:
                return self._send(lib.task_audit.signal_bytes(qs['ep'][0],'meta' if route=='/api/meta' else 'series'),'application/json' if route=='/api/meta' else 'application/octet-stream',cache='private, no-cache')
            if route in ('/api/meta','/api/series'):
                ep=self._episode(parsed.query)
                if ep is None:return
                is_meta=route=='/api/meta'
                return self._send(ep.meta_bytes if is_meta else ep.series_bytes,
                                  'application/json' if is_meta else 'application/octet-stream',
                                  cache='private, no-cache',etag=ep.etag_meta if is_meta else ep.etag_series)
            if route=='/api/catalog':return self._json(lib.catalog(),cache='no-store')
            if route=='/api/task-audit':return self._json(lib.task_audit.catalog(),cache='no-store')
            if route=='/api/task-audit/curve':return self._json(lib.task_audit.curve(qs.get('ep',[''])[0]),cache='no-store')
            if route=='/api/task-audit/objects':return self._json(lib.task_audit.objects(qs.get('ep',[''])[0]),cache='no-store')
            if route=='/api/task-audit/frame':return self._send(lib.task_audit.frame(qs.get('ep',[''])[0],float(qs.get('t',['0'])[0])),'image/jpeg',cache='private, no-cache')
            if route=='/api/progress/models':return self._json(lib.progress_service.models(),cache='no-store')
            if route=='/api/execution-quality':return self._json(lib.execution_quality.current(qs.get('ep',[''])[0],qs.get('model_id',[''])[0]),cache='no-store')
            if route=='/api/progress':return self._json(lib.progress_service.current(qs.get('ep',[''])[0],qs.get('model_id',[''])[0]),cache='no-store')
            if route=='/api/progress/job':return self._json(lib.progress_service.public_job(lib.progress_service.job(qs.get('id',[''])[0])),cache='no-store')
            if route=='/api/frame-index':return self._json(lib.frame_store.public_index(qs.get('ep',[''])[0]),cache='private, no-cache')
            if route=='/api/frame-batch':
                payload=lib.frame_store.encoded_batch(qs.get('ep',[''])[0],qs.get('cam',['head'])[0],
                                                      int(qs.get('start',['0'])[0]),int(qs.get('count',['8'])[0]),qs.get('token',[None])[0])
                return self._send(payload,'application/octet-stream',cache='private, no-cache')
            if route=='/api/rules':return self._json(dict(rules=lib.rules(),labels=RULE_LABELS,defaults=DEFAULT_RULES))
            if route=='/api/diagnostics':return self._json(lib.diagnostics(qs.get('ep',[''])[0]))
            if route=='/api/trajectories':return self._json(lib.trajectories(qs.get('ep',[''])[0],self.robot),cache='private, no-cache')
            if route=='/api/reference-checks':return self._json(lib.reference_checks(qs.get('ep',[''])[0]))
            if route=='/api/history':return self._json(dict(history=lib.store.history(qs.get('ep',[''])[0])))
            if route=='/api/exports':return self._json(dict(exports=lib.exports()),cache='no-store')
            if route=='/api/download':
                name=qs.get('file',[''])[0]
                if Path(name).name!=name or not name.startswith('export_') or not name.endswith('.zip'):raise ValueError('文件名无效')
                p=lib.export_root/name
                if not p.is_file():raise KeyError('导出文件不存在')
                self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Length',str(p.stat().st_size));self.send_header('Content-Disposition',f'attachment; filename="{name}"');self.end_headers()
                with p.open('rb') as f:shutil.copyfileobj(f,self.wfile)
                return
            if route=='/api/frame' and 'cam' in qs and qs.get('ep',[''])[0] not in lib.order and lib.task_audit.has_snapshot(qs.get('ep',[''])[0]):
                return self._send(lib.task_audit.frame(qs['ep'][0],float(qs.get('t',['0'])[0])),'image/jpeg',cache='private, no-cache')
            if route=='/api/frame' and 'cam' in qs:
                if 'i' in qs:
                    _,frames=lib.frame_store.batch(qs['ep'][0],qs['cam'][0],int(qs['i'][0]),1,qs.get('token',[None])[0])
                    if not frames[0]:raise KeyError('该帧无法读取')
                    return self._send(frames[0],'image/jpeg',cache='private, no-cache')
                seconds=float(qs.get('t',['0'])[0])
                if not math.isfinite(seconds) or seconds<0:raise ValueError('时间无效')
                payload=lib.frame_at(qs['ep'][0],qs['cam'][0],seconds)
                import hashlib
                return self._send(payload,'image/jpeg',cache='private, no-cache',etag='"'+hashlib.sha1(payload).hexdigest()+'"')
            return super().do_GET()
        except (BrokenPipeError,ConnectionResetError):pass
        except KeyError as e:self._json({'error':str(e)},status=404)
        except Conflict as e:self._json({'error':str(e)},status=409)
        except (ValueError,TypeError,OSError) as e:self._json({'error':str(e)},status=400)
        except Exception as e:
            import traceback;traceback.print_exc();self._json({'error':str(e)},status=500)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('paths',nargs='*',type=Path)
    ap.add_argument('--port',type=int,default=8421);ap.add_argument('--workspace',type=Path,default=APP/'workspace')
    ap.add_argument('--analyze',action='store_true');args=ap.parse_args()
    lib=StudioLibrary(args.workspace.resolve())
    paths=args.paths or lib.store.setting('roots',[])
    for path in paths:
        try:lib.add_root(Path(path))
        except OSError as e:print(f'目录不可用: {path}: {e}')
    lib.store.set_setting('roots',[str(p) for p in lib.roots])
    lib.default_id=lib.order[0] if lib.order else None
    robot=viewer.Robot(APP/'robot'/'g1_29dof_rev_1_0.urdf')
    viewer.STATIC_DIR=APP/'static'
    if args.analyze:
        for ep in lib.order:lib.prepare(ep)
    handler=partial(Handler,library=lib,robot=robot)
    with viewer.ThreadingHTTPServer(('127.0.0.1',args.port),handler) as http:
        lib.recover_jobs()
        lib.taskflow.recover()
        print(f'RoboCurate: http://127.0.0.1:{args.port} · {len(lib.order)} records',flush=True)
        try:http.serve_forever()
        except KeyboardInterrupt:pass
        finally:
            lib.taskflow.close()
            lib.progress_service.close()


if __name__=='__main__':main()
