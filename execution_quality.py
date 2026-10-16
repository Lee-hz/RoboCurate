"""G1 task execution audit: measured evidence and explicit human decisions.

Stage labels locate candidate intervals. They do not prove safety, contact,
accuracy, task success, or retreat. No checkpoint or existing grade is changed.
"""
import copy
import hashlib
import json
import math
import threading
from collections import OrderedDict

import numpy as np

from storage import Conflict, now
from execution_metrics import POLICY as METRIC_POLICY, metric_contract, phase_metrics, with_duration_target

VERSION = 2
PROFILE = 'g1-mobile-manipulation-execution-v2'
MODEL_NAMES = ['接近左桌', '抓取香蕉', '持物搬运', '向篮子放置', '释放后观察']
PHASES = [
    dict(key='approach', name='接近', goal='安全并且迅速',
         boundary='开始向取物区接近，至到达可抓取位置。',
         checks=[('safety', '接近安全', '确认人与障碍物间距、身体平衡及到位减速；画面未覆盖的区域保留为无法判断。')]),
    dict(key='grasp', name='抓取', goal='准确并且迅速',
         boundary='开始针对目标抓取，至目标被有效抓住并抬起；失败尝试和重新调整计入用时。',
         checks=[('accuracy', '有效且准确地抓取', '确认抓到指定物体、抓取位置合适并有效抬起；记录抓空、重抓和无效调整。')]),
    dict(key='transport', name='搬运', goal='稳定并且迅速',
         boundary='有效持物后开始搬运，至到达放置准备位置。',
         checks=[('stability', '持物与身体稳定', '同时确认物体未滑移或掉落、身体运动稳定；IMU 和关节波动仅作为辅助证据。')]),
    dict(key='place', name='放置', goal='准确并且迅速',
         boundary='开始对准目标区域，至物体释放并稳定留在指定位置。',
         checks=[('accuracy', '放置位置与结果正确', '确认目标位置、物体姿态和释放后稳定性；只有手到位或二维框重合不足以确认放置成功。')]),
    dict(key='retreat', name='释放后撤离', goal='手臂收回，整机安全离开',
         boundary='从物体释放开始，覆盖手臂收回、整机离开操作区域及撤离后的稳定状态。',
         checks=[('arm_clear', '手臂安全收回', '手臂离开物体和容器，撤回过程没有刮碰或再次带动物体。'),
                 ('base_clear', '整机离开操作区域', '结合画面确认整机及其外廓离开指定操作区域；参考根部位置不作为实测位移。'),
                 ('safety', '撤离过程安全', '确认人、障碍物、机器人及已放置物体之间没有危险接触，身体保持稳定。')]),
]
LABELS = dict(pending='待审核', unknown='证据不足', fail='存在问题', passed='人工确认符合')


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def aggregate(states):
    """A confirmed problem dominates; speed never offsets it."""
    states = list(states)
    if 'fail' in states:
        return 'fail'
    if 'unknown' in states:
        return 'unknown'
    if not states or any(s != 'pass' for s in states):
        return 'pending'
    return 'passed'


def native_values(native, key, start, end, t0):
    if key+'.t' not in native or key+'.v' not in native:
        return None
    t, v = native[key+'.t'], native[key+'.v']
    if t.ndim != 1 or t.dtype.kind not in 'iu' or v.ndim != 2 or len(v) != len(t):
        return None
    if np.any(np.diff(t.astype(np.int64)) < 0):
        return None
    seconds = (t.astype(np.int64)-int(t0))/1e9
    v = v[(seconds >= start) & (seconds < end)]
    return v if len(v) else None


def metrics_for(native, start, end, t0):
    metrics = []

    def add(key, label, values, unit, calculation='p95'):
        if values is None:
            value = None
        else:
            values = np.asarray(values)
            # Missing numeric observations stay missing, never turn into zero.
            value = None if not len(values) or not np.isfinite(values).all() else float(
                np.ptp(values) if calculation == 'range' else np.percentile(np.abs(values), 95))
        metrics.append(dict(key=key, label=label, value=None if value is None else round(value, 4),
                            unit=unit, verdict=None, advisory_only=True))

    imu = native_values(native, 'imu.rpy', start, end, t0)
    for j, key, name in [(0, 'roll', '身体横滚变化范围'), (1, 'pitch', '身体俯仰变化范围')]:
        values = None if imu is None or imu.shape[1] < 2 else np.rad2deg(np.unwrap(imu[:, j]))
        add(key, name, values, '°', 'range')
    gyro = native_values(native, 'imu.gyro', start, end, t0)
    add('gyro', '身体角速度 P95', None if gyro is None else np.linalg.norm(gyro, axis=1), 'rad/s')
    dq = native_values(native, 'state.dq', start, end, t0)
    add('arm_speed', '双臂关节速度绝对值 P95', None if dq is None or dq.shape[1] != 29 else dq[:, 15:29].reshape(-1), 'rad/s')
    for side, label in [('left', '左手'), ('right', '右手')]:
        q = native_values(native, 'hand.'+side+'.state_q', start, end, t0)
        grip = None if q is None or q.shape[1] != 6 else np.median(q[:, 2:6], axis=1)
        add(side+'_grip', label+'四指闭合量变化范围', grip, '0–1', 'range')
    return metrics


def measure_window(phase, native, meta, diagnostics, start, end):
    phase = copy.deepcopy(phase)
    phase.update(start_s=start, end_s=end, duration_s=round(end-start, 4),
                 metrics=metrics_for(native, start, end, meta['episode']['start_ns']),
                 quantitative=phase_metrics(phase['key'],native,start,end,meta['episode']['start_ns']), events=[])
    for event in diagnostics.get('events', []):
        a, b = max(start, event['start_s']), min(end, event['end_s'])
        if b > a or (event['start_s'] == event['end_s'] and start <= event['start_s'] < end):
            phase['events'].append({**event, 'overlap_start_s': a, 'overlap_end_s': b})
    return phase


def load_native(cache):
    keys = ['imu.rpy', 'imu.quat', 'imu.gyro', 'state.dq', 'hand.left.state_q', 'hand.right.state_q']
    with np.load(cache/'native.npz', allow_pickle=False) as raw:
        return {k+s: raw[k+s] for k in keys for s in ('.v', '.t') if k+s in raw}


def build_report(result, meta, native, diagnostics):
    if result.get('stage_names') != MODEL_NAMES:
        raise ValueError('当前执行标准仅适用于已核对的 G1 搬运五阶段模型')
    duration = float(meta['episode']['duration_s'])
    phases, observed = [], set()
    for i, segment in enumerate(result.get('stage_segments', [])):
        k, start, end = segment['stage'], float(segment['start_s']), float(segment['end_s'])
        if type(k) is not int or not 0 <= k < len(PHASES) or not 0 <= start < end <= duration+.001:
            raise ValueError('阶段区间无效')
        observed.add(k)
        phase = copy.deepcopy(PHASES[k])
        phase.update(id=f'phase-{i}', model_stage=k, model_name=MODEL_NAMES[k],
                     candidate_start_s=start, candidate_end_s=end, review_fraction=segment.get('review_fraction'),
                     interval_source='model_candidate')
        phases.append(measure_window(phase,native,meta,diagnostics,start,end))
    for k in sorted(set(range(5))-observed):
        phases.append(dict(copy.deepcopy(PHASES[k]), id=f'missing-{k}', model_stage=k, model_name=MODEL_NAMES[k],
                           start_s=None, end_s=None, duration_s=None, interval_source='missing', metrics=[],
                           quantitative=metric_contract(PHASES[k]['key']), events=[]))
    return dict(version=VERSION, profile=PROFILE, phases=phases, stage_signature=result['signature'],
                model_id=result.get('model_id'), source=meta['source'], recording_duration_s=duration,
                metric_policy=copy.deepcopy(METRIC_POLICY),
                automatic_execution_verdict=False, retreat_scope='arm_and_whole_robot',
                note='自动计算阶段候选用时、原生运动指标和问题区间；执行结论来自明确保存的人工审核。',
                limitations=[
                    '安全、准确、持物稳定与整机撤离逐项结合画面确认。',
                    '原生指标使用记录时间；时间对齐和控制模式仍需核对。',
                    '末段按“释放后观察”定位，再核对手臂收回和整机离区。',
                    '撤离距离使用实际基座定位与操作区边界。',
                    '迅速仅在阶段范围与执行要求均确认后，对照同条件目标用时判断。',
                    '量化提醒线采用工程初值，用于定位复核区间。',
                ])


def apply_review(report, review):
    out = copy.deepcopy(report)
    fresh = review.get('signature') == report['signature']
    out['review'] = review
    out['review_stale'] = bool(review.get('revision') and not fresh)
    decisions = review.get('phases', {}) if fresh else {}
    for phase in out['phases']:
        d = decisions.get(phase['id'], {})
        if d.get('evidence'):
            phase.update(copy.deepcopy(d['evidence']))
        checks = []
        for key, label, help_text in phase['checks']:
            checks.append(dict(key=key, label=label, help=help_text, status=d.get('checks', {}).get(key, 'pending')))
        core = aggregate(c['status'] for c in checks)
        boundary = bool(d.get('boundary_confirmed')) and phase['start_s'] is not None
        target = d.get('target_s')
        phase['quantitative']=with_duration_target(phase.get('quantitative',[]),phase['duration_s'],target,boundary,core=='passed')
        pace = 'pending'
        if phase['key'] != 'retreat':
            if core == 'fail':
                pace = 'blocked'
            elif core == 'passed' and boundary and target is not None:
                pace = 'pass' if phase['duration_s'] <= target else 'fail'
            checks.append(dict(key='pace', label='迅速完成', help='阶段完整、执行要求符合后，将用时与填写的同条件目标比较。', status=pace))
        state = aggregate(c['status'] for c in checks)
        if state == 'passed' and not boundary:
            state = 'pending'
        if phase['start_s'] is None and state != 'fail':
            state = 'unknown'
        phase.update(checks=checks, decision=d, state=state, state_label=LABELS[state],
                     boundary_confirmed=boundary, target_s=target)
    states = ['pass' if p['state'] == 'passed' else p['state'] for p in out['phases']]
    out['state'] = aggregate(states)
    out['state_label'] = LABELS[out['state']]
    out['summary'] = dict(phases=len(out['phases']), confirmed=sum(p['state']=='passed' for p in out['phases']),
                          issues=sum(p['state']=='fail' for p in out['phases']),
                          pending=sum(p['state'] in ('pending','unknown') for p in out['phases']))
    return out


class ExecutionQualityService:
    def __init__(self, library):
        self.library = library
        self.memo = OrderedDict()
        self.lock = threading.RLock()
        with library.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS execution_reviews (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS execution_history (seq INTEGER PRIMARY KEY, id TEXT, at TEXT, before TEXT, after TEXT);
            ''')

    @staticmethod
    def empty():
        return dict(revision=0, signature=None, phases={}, updated_at=None)

    def review(self, key):
        with self.library.store.connect() as db:
            row = db.execute('SELECT body FROM execution_reviews WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else self.empty()

    def evidence(self, ep, model):
        lib = self.library
        current = lib.progress_service.current(ep, model)
        if current['state'] != 'ready' or current['result'].get('kind') != 'stage_progress':
            raise ValueError('请先生成本记录的阶段识别结果')
        cache = lib.cache_dir(lib.ref(ep))
        result = current['result']
        diagnostics = lib.diagnostics(ep)

        def identity():
            return dict(version=VERSION, profile=PROFILE, phase_contract=PHASES,
                        metric_policy=METRIC_POLICY,
                        source=lib.fingerprint(lib.ref(ep)), stage=result['signature'],
                        native=[(cache/'native.npz').stat().st_size, (cache/'native.npz').stat().st_mtime_ns],
                        meta=(cache/'meta.json').stat().st_mtime_ns, diagnostics=diagnostics['signature'])

        with self.lock:
            key = signature(identity())
            if key not in self.memo:
                meta = json.loads((cache/'meta.json').read_text())
                report = build_report(result, meta, load_native(cache), diagnostics)
                if key != signature(identity()):
                    raise Conflict('数据已变化，请重新读取执行质检')
                report['signature'] = key
                self.memo[key] = report
                while len(self.memo) > 8:
                    self.memo.popitem(last=False)
            return self.memo[key]

    def current(self, ep, model):
        return apply_review(self.evidence(ep, model), self.review(ep+':'+model))

    def save(self, body):
        ep, model = body.get('ep'), body.get('model_id')
        report = self.evidence(ep, model)
        if body.get('signature') != report['signature']:
            raise Conflict('数据、阶段模型或规则已变化，请重新核对')
        if type(body.get('revision')) is not int:
            raise ValueError('缺少执行审核版本')
        phase = next((p for p in report['phases'] if p['id'] == body.get('phase_id')), None)
        if phase is None:
            raise ValueError('没有可审核的阶段区间')
        decision = body.get('decision')
        if not isinstance(decision, dict):
            raise ValueError('审核内容无效')
        start, end = decision.get('start_s',phase['start_s']), decision.get('end_s',phase['end_s'])
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (start,end)) or not 0 <= start < end <= report['recording_duration_s']+.0001 or end-start < .1:
            raise ValueError('请指定记录内至少 0.1 秒的完整阶段区间')
        if start != phase['start_s'] or end != phase['end_s']:
            cache = self.library.cache_dir(self.library.ref(ep))
            meta = json.loads((cache/'meta.json').read_text())
            phase = measure_window(phase,load_native(cache),meta,self.library.diagnostics(ep),start,end)
            phase['interval_source']='human_corrected'
            if self.evidence(ep,model)['signature'] != report['signature']:
                raise Conflict('数据已变化，请重新核对阶段范围')
        checks = decision.get('checks')
        keys = {c[0] for c in phase['checks']}
        if not isinstance(checks, dict) or set(checks) != keys or any(s not in ('pending','pass','fail','unknown') for s in checks.values()):
            raise ValueError('请填写该阶段的各项检查')
        boundary = decision.get('boundary_confirmed', False)
        if type(boundary) is not bool:
            raise ValueError('阶段范围确认无效')
        note, basis = decision.get('note', ''), decision.get('pace_basis', '')
        if any(not isinstance(t, str) or len(t)>2000 for t in (note, basis)):
            raise ValueError('审核说明应不超过 2000 字')
        if any(s != 'pending' for s in checks.values()) and not note.strip():
            raise ValueError('请填写画面、位置或问题时间等审核依据')
        target = decision.get('target_s')
        if target is not None:
            if phase['key']=='retreat' or isinstance(target, bool) or not isinstance(target,(float,int)) or not math.isfinite(target) or not 0 < target <= 3600:
                raise ValueError('同条件目标用时应为 0–3600 秒之间的正数')
            if not basis.strip():
                raise ValueError('请说明目标用时的依据，例如已确认的同条件优质演示')
        clean = dict(checks=checks, boundary_confirmed=boundary, note=note.strip(), target_s=target,
                     start_s=start, end_s=end,
                     pace_basis=basis.strip(), reviewed_at=now(), origin='human_review',
                     evidence=copy.deepcopy(phase))
        key = ep+':'+model
        with self.library.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM execution_reviews WHERE id=?', (key,)).fetchone()
            old = json.loads(row[0]) if row else self.empty()
            if old['revision'] != body['revision']:
                raise Conflict('执行审核已在其他窗口更新，请刷新后重试')
            decisions = copy.deepcopy(old['phases']) if old.get('signature') == report['signature'] else {}
            decisions[phase['id']] = clean
            new = dict(revision=old['revision']+1, signature=report['signature'], phases=decisions, updated_at=now())
            text = json.dumps(new, ensure_ascii=False, allow_nan=False)
            db.execute('INSERT OR REPLACE INTO execution_reviews VALUES (?,?)', (key,text))
            db.execute('INSERT INTO execution_history(id,at,before,after) VALUES (?,?,?,?)',
                       (key,now(),json.dumps(old,ensure_ascii=False),text))
        return apply_review(report,new)
