"""Reproducible WARP relative-progress training on frozen feature caches.

The manifest splits whole source episodes before selecting demonstrations.
Synthetic warps belong to their source split; validation never sees training
frames. This entry point measures time-warp prediction, not robot success.
"""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import random
import time
import numpy as np
import torch
import torch.nn.functional as F
from vendor.warp_rm.aggregator import TransformerAggregator
from .core import WarpConfig, UPSTREAM, contiguous_runs, sample_warp, relative_targets, two_hot, json_signature
from .features import BACKBONE_ID, atomic_json
from .model import file_sha256, load_model


def load_manifest(path, config):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text())
    rows = manifest['episodes']
    split_hashes, feature_hashes, groups, contract = {}, {}, {'train': [], 'validation': []}, None
    audit = []
    for row in rows:
        split = row['split']
        if split not in groups:
            raise ValueError('Every episode must explicitly belong to train or validation')
        source_hash = row['source_sha256']
        if len(source_hash) != 64 or any(c not in '0123456789abcdef' for c in source_hash):
            raise ValueError('Each episode needs a source SHA256')
        if source_hash in split_hashes and split_hashes[source_hash] != split:
            raise ValueError('Source content leaks across the train/validation split')
        split_hashes[source_hash] = split
        feature_path = (path.parent / row['features']).resolve()
        descriptor = json.loads(feature_path.with_suffix('.json').read_text())
        if descriptor.get('source_sha256', source_hash) != source_hash:
            raise ValueError('Manifest source SHA256 differs from feature extraction provenance')
        feature_hash = file_sha256(feature_path)
        if feature_hash in feature_hashes and feature_hashes[feature_hash] != split:
            raise ValueError('Identical feature content leaks across train/validation')
        feature_hashes[feature_hash] = split
        current = descriptor['contract']
        # All features must come from one camera/preprocessing/backbone contract.
        if current['fps'] != config.fps or current['feature_stride'] != config.feature_stride:
            raise ValueError('Feature time scale differs from training label calibration')
        if contract is not None and contract != current:
            raise ValueError('Mixed feature contracts; train a separate model for each camera/task')
        contract = current
        with np.load(feature_path, allow_pickle=False) as data:
            features = data['features'].astype(np.float32)
            valid = data['valid'].astype(bool)
        if features.ndim != 2 or features.shape[1] != current['dimension'] or len(valid) != len(features):
            raise ValueError('Malformed feature cache')
        runs = contiguous_runs(valid & np.isfinite(features).all(axis=1))
        runs = [(int(a), int(b)) for a, b in runs if b - a >= config.window_size + 1]
        if not runs:
            raise ValueError('No continuous valid observation window: ' + row['features'])
        groups[split].append((features, runs))
        audit.append(dict(id=row['id'], split=split, source_sha256=source_hash,
                          feature_sha256=feature_hash, frames=len(features), runs=runs,
                          task=row.get('task', ''), selection=row.get('selection', 'explicit manifest')))
    if not all(groups.values()):
        raise ValueError('Training requires separate train and validation episodes')
    if len({r.get('task', '') for r in rows}) != 1 or not rows[0].get('task', '').strip():
        raise ValueError('Each run requires one explicit, shared task definition')
    return groups, dict(episodes=audit, feature_contract=contract, task=rows[0]['task'],
                        manifest_sha256=file_sha256(path), split_policy=manifest.get('split_policy', 'explicit episodes'))


def sample_batch(episodes, config, rng, size):
    x, y = [], []
    for _ in range(size):
        features, runs = episodes[int(rng.integers(len(episodes)))]
        a, b = runs[int(rng.integers(len(runs)))]
        ids = a + sample_warp(b - a, config, rng)
        x.append(features[ids])
        y.append(relative_targets(ids, config))
    return np.stack(x), np.stack(y)


def evaluate(model, episodes, config, device, batches=8, batch_size=16, seed=20260916):
    rng = np.random.default_rng(seed)
    total, squared, sign_right, sign_total, clipped = 0., 0., 0, 0, 0
    count = 0
    model.eval()
    with torch.inference_mode():
        for _ in range(batches):
            x, y = sample_batch(episodes, config, rng, batch_size)
            prediction, _, logits = model(torch.from_numpy(x).to(device))
            target = torch.from_numpy(two_hot(y)).to(device)
            total += float(-(target * F.log_softmax(logits, -1)).sum(-1).sum())
            pred = prediction.cpu().numpy()
            squared += float(np.square(pred - y).sum())
            dy, dp = np.diff(y), np.diff(pred)
            mask = np.abs(dy) > 1e-6
            sign_right += int(((np.sign(dy) == np.sign(dp)) & mask).sum())
            sign_total += int(mask.sum())
            clipped += int((np.abs(y) > 3).sum())
            count += y.size
    return dict(cross_entropy=total / count, rmse=math.sqrt(squared / count),
                warp_direction_accuracy=sign_right / max(1, sign_total),
                clipped_label_fraction=clipped / count, tokens=count,
                interpretation='Held-out synthetic time warps; not measured task success')


def train(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'run.json').exists():
        raise ValueError('Output already contains a run; choose a new directory')
    if args.steps < 1 or args.batch_size < 1 or args.eval_every < 1 or args.threads < 1 or args.eval_batches < 1 or args.warmup_steps < 0:
        raise ValueError('Steps, batch size, evaluation interval and threads must be positive')
    if not math.isfinite(args.lr) or args.lr <= 0:
        raise ValueError('Learning rate must be finite and positive')
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed); random.seed(args.seed); np.random.seed(args.seed)
    rng = np.random.default_rng(args.seed)
    config = WarpConfig(window_size=getattr(args, 'window_size', 32), feature_stride=args.feature_stride, source_standard_stride=args.source_standard_stride)
    groups, audit = load_manifest(args.manifest, config)
    architecture = dict(d_model=args.d_model, n_heads=args.n_heads, n_layers=args.n_layers,
                        dropout=.15, stochastic_depth_p=.1)
    if args.init:
        model, initial_config, initial_meta = load_model(args.init, args.device)
        if initial_config != config:
            raise ValueError('Warm-start checkpoint has a different time-scale contract')
        original_contract = initial_meta.get('provenance', {}).get('feature_contract')
        current_contract = audit['feature_contract']
        if original_contract:
            if original_contract != current_contract:
                raise ValueError('Warm-start checkpoint has a different visual feature contract')
        elif current_contract.get('backbone') != BACKBONE_ID or current_contract['dimension'] != 768:
            raise ValueError('Published head warm-start requires the original DINOv3 features')
        architecture.update(d_model=model.d_model, n_layers=len(model.transformer.layers),
                            n_heads=model.transformer.layers[0].self_attn.num_heads)
        init_hash = initial_meta['sha256']
    else:
        model = TransformerAggregator(**architecture, backbone_dim=audit['feature_contract']['dimension'],
                                      max_seq_len=config.window_size).to(args.device)
        init_hash = None
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-3)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
        optimizer, T_0=max(3 * args.steps, 1000), T_mult=1, eta_min=args.lr * .01)
    run = dict(version=1, upstream_commit=UPSTREAM, warp_config=asdict(config), architecture=architecture,
               training=vars(args), audit=audit, init_sha256=init_hash, state='running',
               paper_architecture=architecture['d_model'] == 768 and architecture['n_layers'] == 12 and architecture['n_heads'] == 8,
               reproducibility='Explicit NumPy Generator, torch and Python seeds; upstream sampler created an unseeded Generator',
               started_at=time.time(), validation=[]) 
    atomic_json(output / 'run.json', run)
    best = float('inf')
    try:
        baseline = evaluate(model, groups['validation'], config, args.device, args.eval_batches,
                            min(args.batch_size, 16), args.seed + 1)
        run['validation'].append(dict(step=0, **baseline))
        atomic_json(output / 'run.json', run)
        for step in range(1, args.steps + 1):
            model.train()
            x, y = sample_batch(groups['train'], config, rng, args.batch_size)
            _, _, logits = model(torch.from_numpy(x).to(args.device))
            target = torch.from_numpy(two_hot(y)).to(args.device)
            loss = -(target * F.log_softmax(logits, -1)).sum(-1).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
            optimizer.step()
            # Match the released trainer's post-step warmup convention.
            if step - 1 < args.warmup_steps:
                for group in optimizer.param_groups:
                    group['lr'] = args.lr * step / max(1, args.warmup_steps)
            else:
                scheduler.step()
            if step % args.eval_every == 0 or step == args.steps:
                metrics = evaluate(model, groups['validation'], config, args.device,
                                   args.eval_batches, min(args.batch_size, 16), args.seed + 1)
                row = dict(step=step, train_ce=float(loss.detach()), **metrics)
                run['validation'].append(row)
                print(json.dumps(row), flush=True)
                checkpoint = dict(model=model.state_dict(), step=step, warp_config=asdict(config),
                                  architecture=architecture, backbone_dim=audit['feature_contract']['dimension'],
                                  label_mode='relative', attention='bidirectional', ablation='no_abs',
                                  n_cameras=1, standard_stride_src=config.source_standard_stride,
                                  feature_stride=config.feature_stride, metrics=metrics, provenance=audit,
                                  run_signature=json_signature({k:v for k,v in run.items() if k not in ('validation','state')}))
                temp = output / 'latest.pt.tmp'; torch.save(checkpoint, temp); temp.replace(output / 'latest.pt')
                if metrics['cross_entropy'] < best:
                    best = metrics['cross_entropy']
                    temp = output / 'best.pt.tmp'; torch.save(checkpoint, temp); temp.replace(output / 'best.pt')
                    run['best_step'] = step
                atomic_json(output / 'run.json', run)
        run.update(state='complete', finished_at=time.time(), best_sha256=file_sha256(output / 'best.pt'))
    except BaseException as exc:
        run.update(state='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', error=str(exc), finished_at=time.time())
        raise
    finally:
        atomic_json(output / 'run.json', run)
    return run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True); p.add_argument('--output', required=True)
    p.add_argument('--init'); p.add_argument('--device', default='cpu'); p.add_argument('--threads', type=int, default=4)
    p.add_argument('--steps', type=int, default=20000); p.add_argument('--batch-size', type=int, default=256)
    p.add_argument('--lr', type=float, default=1e-4); p.add_argument('--warmup-steps', type=int, default=1000)
    p.add_argument('--eval-every', type=int, default=200); p.add_argument('--eval-batches', type=int, default=8)
    p.add_argument('--seed', type=int, default=42); p.add_argument('--feature-stride', type=int, default=1)
    p.add_argument('--window-size', type=int, default=32)
    p.add_argument('--source-standard-stride', type=int, default=15)
    p.add_argument('--d-model', type=int, default=768); p.add_argument('--n-layers', type=int, default=12)
    p.add_argument('--n-heads', type=int, default=8)
    train(p.parse_args())


if __name__ == '__main__':
    main()
