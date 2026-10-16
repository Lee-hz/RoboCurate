"""Portable training bundle from native samples, with conservative validity masks."""
import hashlib
import io
import json
import math
import shutil
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError
from mcap.reader import make_reader
from server import _jpeg_payload
from storage import now
from quality_evidence import fixed_spacing
from progress_service import validate_policy

STATE_KEYS=['state.q','hand.left.state_q','hand.right.state_q']
ACTION_KEYS=['action.q','hand.left.cmd_q','hand.right.cmd_q']


def align(times, values, grid, hold=False, max_gap_ns=100_000_000, quaternion=False):
    """Stable last duplicate wins; no extrapolation or bridging large gaps.

    Commands are causal zero-order hold; states use bracketing interpolation.
    Relative int64 differences avoid precision loss for epoch timestamps.
    """
    out=np.full((len(grid),values.shape[1]),np.nan,dtype=np.float32)
    valid=np.zeros(len(grid),dtype=bool)
    if len(times)==0:
        return out,valid
    order=np.argsort(times,kind='stable'); t=times[order]; v=values[order]
    keep=np.r_[t[:-1]!=t[1:], True]; t=t[keep]; v=v[keep]
    left=np.searchsorted(t,grid,side='right')-1
    inside=(left>=0)&(grid<=t[-1]); left=np.clip(left,0,len(t)-1)
    right=np.minimum(left+1,len(t)-1)
    age=grid-t[left]
    if hold:
        valid=inside&(age<=max_gap_ns)
        out[valid]=v[left[valid]]
    else:
        gap=t[right]-t[left]
        valid=inside&((age==0)|((gap>0)&(gap<=max_gap_ns)))
        weight=np.divide(age,gap,out=np.zeros(len(grid),dtype=float),where=gap!=0)
        a=v[left].astype(float); b=v[right].astype(float)
        if quaternion:
            b=np.where((a*b).sum(axis=1,keepdims=True)<0,-b,b)
        interp=a+(b-a)*weight[:,None]
        interp[age==0]=a[age==0]
        if quaternion:
            norm=np.linalg.norm(interp,axis=1,keepdims=True)
            interp=np.divide(interp,norm,out=np.full_like(interp,np.nan),where=norm>1e-8)
        out[valid]=interp[valid]
    valid &= np.isfinite(out).all(axis=1)
    out[~valid]=np.nan
    return out,valid


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()


def concrete_instruction(text):
    return bool(str(text or '').strip()) and 'validate v1.4' not in str(text).lower()


def plan_clip(native, meta, start_s, end_s, fps=30):
    """The shared alignment contract for preview, preflight and actual export.

    `valid` here proves timestamp/numeric coverage only. Export additionally
    decodes JPEGs and invalidates any corrupt image before publishing the ZIP.
    """
    start_s, end_s, fps = float(start_s), float(end_s), float(fps)
    duration = (meta['episode']['end_ns'] - meta['episode']['start_ns']) / 1e9
    if not all(math.isfinite(v) for v in (start_s, end_s, fps)) or not 1 <= fps <= 100:
        raise ValueError('采样率必须在 1–100 Hz 之间')
    if not 0 <= start_s < end_s <= duration + .0001:
        raise ValueError('片段超出源记录的时间范围')
    t0 = int(meta['episode']['start_ns'])
    start = t0 + round(start_s * 1e9)
    end = min(t0 + round(end_s * 1e9), int(meta['episode']['end_ns']))
    n = int(math.ceil((end - start) / 1e9 * fps))
    grid = start + np.rint(np.arange(n) * 1e9 / fps).astype(np.int64)
    grid = grid[grid < end]
    # A strict fixed-rate contract belongs to the derived training grid, not
    # the asynchronous raw sensor streams. Check every interval, including
    # failures that follow an earlier small deviation.
    grid_check = fixed_spacing((grid-grid[0])/1e9 if len(grid) else [], fps)
    if grid_check['severity'] in ('WARN','FAIL'):
        raise ValueError('导出时间网格不满足固定采样间隔，请检查采样配置')
    data = {'timestamp_ns': grid, 'timestamp_s': (grid - t0) / 1e9}
    masks = []
    for key in STATE_KEYS + ACTION_KEYS:
        if key + '.v' not in native or key + '.t' not in native:
            raise ValueError(f'缺少训练通道 {key}')
        values, valid = align(native[key + '.t'], native[key + '.v'], grid, hold=key in ACTION_KEYS)
        data[key] = values
        data['valid.' + key] = valid
        masks.append(valid)
    for key in ['state.dq', 'imu.quat', 'imu.gyro', 'ref.root_pos', 'ref.root_quat']:
        if key + '.v' in native:
            data[key], data['valid.' + key] = align(native[key + '.t'], native[key + '.v'], grid, quaternion=key.endswith('quat'))
    data['observation.state'] = np.concatenate([data[k] for k in STATE_KEYS], axis=1)
    data['action'] = np.concatenate([data[k] for k in ACTION_KEYS], axis=1)
    cameras = {}
    if not meta.get('cameras'):
        raise ValueError('训练导出需要至少一路相机')
    for name in meta['cameras']:
        times = native['camera.' + name + '.t']
        index = np.searchsorted(times, grid, side='right') - 1
        safe = np.clip(index, 0, max(len(times) - 1, 0))
        if len(times):
            selected = times[safe]
            valid = (index >= 0) & (grid - selected <= 100_000_000) & (selected >= start) & (selected < end)
        else:
            selected = np.full(len(grid), -1, dtype=np.int64)
            valid = np.zeros(len(grid), dtype=bool)
        data['valid.camera.' + name] = valid
        data['camera.' + name + '.timestamp_ns'] = np.where(valid, selected, -1)
        masks.append(valid)
        cameras[name] = dict(times=times, safe=safe)
    data['valid'] = np.logical_and.reduce(masks)
    return data, cameras


def preflight(library, records, options):
    """Inspect every selected record before any output file or slow image copy."""
    kind = options.get('kind', 'manifest')
    fps = float(options.get('fps', 30))
    ratio = float(options.get('validation_ratio', .2))
    policy = validate_policy(options.get('progress'))
    if policy and kind != 'dataset':
        raise ValueError('进展权重仅用于通用训练包')
    if kind not in ('manifest', 'dataset') or not math.isfinite(fps) or not 1 <= fps <= 100:
        raise ValueError('导出格式或采样率无效')
    if not math.isfinite(ratio) or not 0 <= ratio <= .5:
        raise ValueError('验证集比例应在 0–0.5 之间')
    rows = []
    for record in records:
        ref = library.ref(record['id'])
        review = record['review']
        row = dict(id=record['id'], name=record['episode_id'], blockers=[], warnings=[], clips=[], samples=0, aligned_samples=0)
        if kind == 'dataset':
            progress_snapshot = None
            if policy:
                try:
                    progress_snapshot = library.progress_service.for_export(record['id'], policy)
                    row['progress'] = dict(model_id=policy['model_id'], covered_samples=0, eligible_anchors=0, retained_anchors=0)
                    row['warnings'].append(progress_snapshot[0]['domain_note'])
                except (ValueError, KeyError, OSError) as exc:
                    row['blockers'].append(str(exc))
            grading = record.get('quality', {}).get('grading', {})
            if grading.get('grade') == 'D':
                row['blockers'].append('自动数据等级 D：'+grading['summary'])
            elif grading.get('method') == 'deminf_qualified_v2' and grading.get('grade') not in ('A','B','C'):
                row['blockers'].append('未通过任务准入：'+grading.get('summary','待复核'))
            if review.get('source_fingerprint') and review['source_fingerprint'] != library.fingerprint(ref):
                row['blockers'].append('源文件已改变，需要重新审核')
            elif review['grade'] in ('A','B') and not review.get('source_fingerprint'):
                row['blockers'].append('缺少审核来源记录，请重新保存标注')
            if review['grade'] not in ('A', 'B'):
                row['blockers'].append('人工等级需为 A 或 B')
            if not concrete_instruction(review.get('instruction') or record.get('source_instruction')):
                row['blockers'].append('需要填写具体任务指令')
            if library.state(ref.id)['state'] != 'ready':
                row['blockers'].append('需要完成深度解析')
            else:
                cache = library.cache_dir(ref)
                meta = json.loads((cache/'meta.json').read_text())
                # Estimate coverage even before approval. This temporary plan
                # never assigns a grade or permits bypassing the blockers above.
                clips = review.get('segments') or [dict(start=0, end=meta['episode']['duration_s'], label='完整记录', grade='B')]
                clips = [c for c in clips if c.get('grade', review['grade']) in ('A','B')]
                if not clips:
                    row['blockers'].append('没有 A / B 级保留片段')
                with np.load(cache/'native.npz', allow_pickle=False) as native:
                    for clip in clips:
                        try:
                            plan, _ = plan_clip(native, meta, clip['start'], clip['end'], fps)
                            count = len(plan['valid'])
                            aligned = int(plan['valid'].sum())
                            row['samples'] += count
                            row['aligned_samples'] += aligned
                            if progress_snapshot:
                                stats = library.progress_service.apply_to_clip(*progress_snapshot, plan, policy, fps)
                                for key in ('covered_samples','eligible_anchors','retained_anchors'):
                                    row['progress'][key] += stats[key]
                            row['clips'].append(dict(label=clip['label'], start=clip['start'], end=clip['end'], samples=count, aligned_samples=aligned,
                                                     invalid_by_channel={k[6:]:int((~v).sum()) for k,v in plan.items() if k.startswith('valid.') and k.split('valid.',1)[1] in STATE_KEYS+ACTION_KEYS+['camera.'+n for n in meta['cameras']]}))
                            if not aligned:
                                row['blockers'].append(f"{clip['label']} 没有可对齐样本")
                        except (ValueError, KeyError) as e:
                            row['blockers'].append(str(e))
            if record.get('source_eligible') is False:
                row['warnings'].append('源录制标记训练转换受限；本次是通用 RGB 包，保留原标记')
            if row['samples'] and row['aligned_samples'] < row['samples']:
                row['warnings'].append(f"{row['samples']-row['aligned_samples']} 个时刻缺少完整覆盖，将标记为无效")
            if progress_snapshot and row['progress']['retained_anchors'] == 0:
                row['blockers'].append('当前阈值与动作块长度下，没有可保留的进展权重样本')
        rows.append(row)
    return dict(ready=not any(r['blockers'] for r in rows), kind=kind, fps=fps, records=rows,
                samples=sum(r['samples'] for r in rows), aligned_samples=sum(r['aligned_samples'] for r in rows),
                note='预检验证数值与时间覆盖；图像完整解码在正式导出时检查，最终有效数可能减少。')


def build_bundle(library, records, options, root, job):
    export_id=job['id']; stage=root/(export_id+'.partial'); stage.mkdir(parents=True)
    kind=options.get('kind','manifest'); fps=float(options.get('fps',30))
    if kind not in ('manifest','dataset') or not math.isfinite(fps) or not 1<=fps<=100:
        raise ValueError('导出格式或采样率无效')
    ratio=float(options.get('validation_ratio',0.2))
    policy=validate_policy(options.get('progress'))
    if policy and kind!='dataset':raise ValueError('进展权重仅用于通用训练包')
    if not 0<=ratio<=0.5: raise ValueError('验证集比例应在 0–0.5 之间')
    manifest=[]; total_valid=0; total_samples=0
    for ri,record in enumerate(records):
        job.update(message=f"{ri+1}/{len(records)} · {record['episode_id'] or record['id']}")
        ep=record['id']; ref=library.ref(ep); review=record['review']
        row=dict(id=ep,episode=ref.episode_id or ref.name,source=str(ref.path),size_bytes=ref.path.stat().st_size,
                 task=ref.task,session=ref.session,operator_outcome=ref.outcome,
                 source_eligible=record['source_eligible'],source_reason=record['source_reason'],
                 quality=record['quality'],review=review,clips=[])
        decisions=review.get('event_decisions',{})
        evidence=review.get('event_evidence',{})
        row['reviewed_events_missing_evidence']=[key for key in decisions if not evidence.get(key) or evidence[key].get('unresolved')]
        row['reviewed_events_with_evidence']=len(decisions)-len(row['reviewed_events_missing_evidence'])
        if kind=='dataset':
            grading = record.get('quality', {}).get('grading', {})
            if grading.get('grade') == 'D':
                raise ValueError('自动数据等级 D：'+grading['summary'])
            elif grading.get('method') == 'deminf_qualified_v2' and grading.get('grade') not in ('A','B','C'):
                raise ValueError('未通过任务准入：'+grading.get('summary','待复核'))
            fingerprint=library.fingerprint(ref)
            if review.get('source_fingerprint')!=fingerprint:
                raise ValueError('原始文件已变化，请重新审核')
            if review['grade'] not in ['A','B']:
                raise ValueError(f'{row["episode"]} 尚未人工审核为 A / B')
            instruction=review.get('instruction','').strip() or record.get('source_instruction','').strip()
            if not instruction or 'validate v1.4' in instruction.lower():
                raise ValueError(f'{row["episode"]} 需要先填写具体任务指令')
            if library.state(ep)['state']!='ready':
                raise ValueError(f'{row["episode"]} 需要先完成深度质检')
            cache=library.cache_dir(ref); meta=json.loads((cache/'meta.json').read_text())
            row['sha256']=sha256(ref.path)
            # Duplicate file contents share a split even under different paths.
            u=int(hashlib.sha256((str(options.get('seed',42))+row['sha256']).encode()).hexdigest()[:16],16)/2**64
            row['split']='validation' if u<ratio else 'train'
            clips=review.get('segments') or [dict(start=0,end=meta['episode']['duration_s'],label='完整记录')]
            names={k:meta['channels'].get(k,{}).get('names',[]) for k in STATE_KEYS+ACTION_KEYS}
            row['instruction']=instruction
            row['feature_layout']={
                'observation.state':[k+':'+n for k in STATE_KEYS for n in names[k]],
                'action':[k+':'+n for k in ACTION_KEYS for n in names[k]]}
            row['units']={k:meta['channels'].get(k,{}).get('unit') for k in STATE_KEYS+ACTION_KEYS}
            progress_snapshot=library.progress_service.for_export(ep,policy) if policy else None
            if progress_snapshot:
                result=progress_snapshot[0]
                row['progress']={k:result[k] for k in ('model_id','model_label','signature','model_signature','checkpoint_sha256',
                                                       'feature_contract','warp_config','validation_status','domain_note','created_at')}
            with np.load(cache/'native.npz',allow_pickle=False) as native:
                for ci,clip in enumerate(clips):
                    if clip.get('grade',review['grade']) not in ('A','B'): continue
                    folder=stage/ep/f'clip_{ci:03}'; folder.mkdir(parents=True)
                    data, camera_plan = plan_clip(native, meta, clip['start'], clip['end'], fps)
                    grid=data['timestamp_ns']
                    masks=[data['valid.'+key] for key in STATE_KEYS+ACTION_KEYS]
                    image_rows=[{} for _ in grid]; camera_details={}
                    for cam,desc in meta['cameras'].items():
                        job['message']=f"{ri+1}/{len(records)} · {row['episode']} · 片段 {ci+1} · {cam} 图像"
                        times=camera_plan[cam]['times'];safe=camera_plan[cam]['safe']
                        valid=data['valid.camera.'+cam]; masks.append(valid)
                        wanted=set(int(t) for t in times[safe[valid]])
                        imgdir=folder/'images'/cam; imgdir.mkdir(parents=True)
                        written={}
                        if wanted:
                            with ref.path.open('rb') as f:
                                for _,_,msg in make_reader(f).iter_messages(topics=[desc['topic']],start_time=min(wanted),end_time=max(wanted)+1):
                                    if msg.log_time not in wanted: continue
                                    jpeg=_jpeg_payload(msg.data)
                                    if not jpeg: continue
                                    try:
                                        with Image.open(io.BytesIO(jpeg)) as decoded:
                                            decoded.load()
                                    except (OSError, ValueError, UnidentifiedImageError):
                                        continue  # corrupt images invalidate their samples
                                    filename=f'{int(msg.log_time)}.jpg'; (imgdir/filename).write_bytes(jpeg)
                                    written[int(msg.log_time)]=f'images/{cam}/{filename}'
                        for i in range(len(grid)):
                            stamp=int(times[safe[i]]) if len(times) else -1
                            if valid[i] and stamp in written: image_rows[i][cam]=written[stamp]
                            else: valid[i]=False; image_rows[i][cam]=None
                        data['camera.'+cam+'.timestamp_ns'][~valid]=-1
                        camera_details[cam]=dict(topic=desc['topic'],images=len(written),valid_samples=int(valid.sum()))
                    if not meta['cameras']: raise ValueError('训练导出需要至少一路相机')
                    data['valid']=np.logical_and.reduce(masks)
                    if not data['valid'].any(): raise ValueError(f'{row["episode"]} 片段 {ci} 没有时间对齐的有效训练样本')
                    progress_stats=library.progress_service.apply_to_clip(*progress_snapshot,data,policy,fps) if progress_snapshot else None
                    np.savez_compressed(folder/'samples.npz',**data)
                    (folder/'images.jsonl').write_text('\n'.join(json.dumps(dict(sample=i,timestamp_ns=int(grid[i]),images=x)) for i,x in enumerate(image_rows))+'\n')
                    c=dict(**clip,path=str(folder.relative_to(stage)),samples=len(grid),valid_samples=int(data['valid'].sum()),cameras=camera_details)
                    if progress_stats:c['progress']=progress_stats
                    (folder/'clip.json').write_text(json.dumps(dict(**c,instruction=instruction,split=row['split']),ensure_ascii=False,indent=2))
                    total_samples+=len(grid);total_valid+=int(data['valid'].sum());row['clips'].append(c)
            if not row['clips']: raise ValueError(f'{row["episode"]} 没有 A / B 级可用片段')
            if progress_snapshot:
                if not sum(c['progress']['retained_anchors'] for c in row['clips']):
                    raise ValueError('图像解码后没有可保留的进展权重样本')
                if library.progress_service.for_export(ep,policy)[0]['signature'] != progress_snapshot[0]['signature']:
                    raise ValueError('导出过程中进展模型或评分发生变化，请重试')
            if library.fingerprint(ref)!=fingerprint:
                raise ValueError('导出过程中原始文件发生变化，请重新解析')
        manifest.append(row)
        job['progress']=(ri+1)/len(records)*90
    manifest_data=dict(format='robot-data-studio.v1',created_at=now(),kind=kind,options=options,episodes=manifest,
                       samples=total_samples,valid_samples=total_valid,
                       alignment=dict(clock='MCAP log_time (ns)',states='linear, quaternion normalized shortest-arc interpolation',
                                      actions='previous sample hold',cameras='previous frame, original JPEG',
                                      max_gap_ms=100,extrapolate=False,interval='[start,end)',
                                      invalid='NaN / false; always apply valid mask'),
                       limitations=['RGB only; no depth synthesized','No measured base translation; ref.root_pos is reference-frame data',
                                    'Portable NPZ/JPEG bundle; not a native LeRobot or RLDS dataset',
                                    'Original source training_eligible flag is preserved, not overridden by human grade',
                                    'Split is by source SHA256; use session-held-out splits for independent-session evaluation'])
    (stage/'manifest.json').write_text(json.dumps(manifest_data,ensure_ascii=False,indent=2))
    (stage/'README.txt').write_text('RoboCurate v1\n\n读取 manifest.json；训练时只用 samples.npz 中 valid=True 的行。\nobservation.state 和 action 为 41 维，字段顺序和单位见 manifest。图像文件索引见 images.jsonl。\n保留无效行供审计；序列训练必须在连续有效区间采样，不能跨越无效行或片段边界。\n时间区间采用 [start,end)。动作使用前值保持，相机只取当前时刻之前且 100ms 内的帧。\n身体位置为 29 个关节弧度，双手各 6 维为归一化闭合量。\n头部图像保留原始双目拼接 JPEG，裁剪、resize 与归一化需按模型配置完成。\n本包为通用格式，不是原生 LeRobot / RLDS。未把 RGB-only 数据转换为 RGB-D。\n',encoding='utf-8')
    if policy:
        with (stage/'README.txt').open('a',encoding='utf-8') as f:
            f.write('\n本包附带 WARP-RM 权重：warp.velocity 为进展速度，warp.valid 为图像进展与数据共同有效掩码，warp.eligible 为完整动作块覆盖，warp.weight 为块末速度门控权重。\n使用 dataset_reader.RobotDataset(..., curation="warp", sequence_length=manifest.options.progress.horizon)，返回 sample_weight；按其加权训练损失。\n阈值为严格大于，不在片段尾部补齐，不跨片段。valid 保留原始技术有效性，未被进展评分覆盖。模型来源及迁移验证状态见 manifest。\n')
    job.update(message='正在封装导出文件',progress=95)
    target=root/(export_id+'.zip'); temp=root/(export_id+'.zip.tmp')
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file(): z.write(p,p.relative_to(stage))
    temp.replace(target)
    shutil.rmtree(stage)  # only this job's disposable derived staging directory
    return dict(file=target.name,kind=kind,size_bytes=target.stat().st_size,episodes=len(manifest),samples=total_samples,valid_samples=total_valid)
