"""Whole-trajectory facility-location selection, inspired by apricot.

Maximize sum_i max_{j in selected} similarity(i,j) with greedy marginal gain.
Quality is used only to resolve numerically equal gains, not an arbitrary weight.
"""
import numpy as np
from scipy.spatial.distance import cdist

def descriptors(states,actions,owners,episode_ids):
    values=np.c_[states,actions];values=np.clip((values-values.mean(0))/np.maximum(values.std(0),1e-3),-10,10)
    return np.array([np.r_[values[owners==i].mean(0),values[owners==i].std(0)] for i in episode_ids])

def facility_select(desc,n,quality=None):
    desc=np.asarray(desc,float)
    if desc.ndim!=2 or not np.isfinite(desc).all() or not 0<n<=len(desc):raise ValueError('Invalid coverage inputs')
    dist=cdist(desc,desc,'sqeuclidean');positive=dist[dist>1e-10];band=float(np.median(positive)) if len(positive) else 1.
    sim=np.exp(-dist/max(band,1e-10));current=np.zeros(len(desc));remaining=set(range(len(desc)));chosen=[]
    quality=np.zeros(len(desc)) if quality is None else np.asarray(quality)
    for _ in range(n):
        gains=np.maximum(sim-current[:,None],0).sum(0);best=max(remaining,key=lambda j:(round(float(gains[j]),12),float(quality[j]),-j));chosen.append(best);remaining.remove(best);current=np.maximum(current,sim[:,best])
    return chosen,dict(mean_representation=float(current.mean()),min_representation=float(current.min()),kernel='RBF median squared trajectory distance',objective='sum of maximum similarity to selected whole trajectories')
