"""Small CPU adaptations of DemInf and QoQ, not original-size reproductions.

DemInf KSG statistic follows jhejna/demonstration-information at
232151defb258b5ceb0a6b62644574b57d981b58 (MIT); see THIRD_PARTY.md.
QoQ follows arXiv:2603.09056 Eq. 6 with final-layer Gaussian BC gradients.
"""
import numpy as np
import torch
from torch import nn
from scipy.spatial.distance import cdist
from scipy.special import digamma

class VAE(nn.Module):
    def __init__(self,d,z):
        super().__init__(); self.enc=nn.Sequential(nn.Linear(d,128),nn.ReLU(),nn.Linear(128,128),nn.ReLU())
        self.mu=nn.Linear(128,z);self.logvar=nn.Linear(128,z)
        self.dec=nn.Sequential(nn.Linear(z,128),nn.ReLU(),nn.Linear(128,128),nn.ReLU(),nn.Linear(128,d))
    def forward(self,x):
        h=self.enc(x);m=self.mu(h);v=self.logvar(h).clamp(-8,8)
        return self.dec(m+torch.randn_like(m)*torch.exp(v/2)),m,v

def standardize(train,all_x):
    mean=train.mean(0);scale=train.std(0);scale=np.maximum(scale,1e-3)
    return np.clip((all_x-mean)/scale,-10,10).astype('float32'),mean,scale

def embed_vae(x,fit,seed,steps,z):
    torch.manual_seed(seed);rng=np.random.default_rng(seed)
    norm,mean,scale=standardize(x[fit],x);data=torch.from_numpy(norm)
    model=VAE(x.shape[1],min(z,x.shape[1]));opt=torch.optim.Adam(model.parameters(),lr=3e-4)
    for _ in range(steps):
        b=data[rng.choice(fit,256)];out,mu,lv=model(b)
        loss=(out-b).square().sum(-1).mean()+.05*(-.5*(1+lv-mu.square()-lv.exp()).sum(-1).mean())
        opt.zero_grad();loss.backward();opt.step()
    with torch.inference_mode():
        emb=torch.cat([model.mu(model.enc(b)) for b in data.split(1024)]).numpy()
    return emb,dict(model=model.state_dict(),mean=mean,scale=scale,z=min(z,x.shape[1]),final_loss=float(loss.detach()))

def ksg_local(obs,action,ks=(5,6,7)):
    """Same self-included strict marginal counts and omitted constants as upstream."""
    ds=cdist(obs,obs);da=cdist(action,action);joint=np.maximum(ds,da)
    radii=np.sort(joint,axis=1)[:,ks]
    ns=(ds[:,:,None]<radii[:,None,:]).sum(1);na=(da[:,:,None]<radii[:,None,:]).sum(1)
    return -(digamma(np.maximum(ns,1))+digamma(np.maximum(na,1))).mean(1)

def deminf_score(obs,action,fit,seed,steps=1800):
    zs,sm=embed_vae(obs,fit,seed,steps,12);za,am=embed_vae(action,fit,seed+1,steps,6)
    rng=np.random.default_rng(seed);zs=zs+rng.normal(0,1e-7,zs.shape);za=za+rng.normal(0,1e-7,za.shape)
    # Equal episode sampling upstream prevents a long idle trajectory dominating.
    total=np.zeros(len(zs));count=np.zeros(len(zs))
    for _ in range(4):
        order=rng.permutation(len(zs));chunks=np.array_split(order,max(1,round(len(order)/512)))
        for ids in chunks:
            total[ids]+=ksg_local(zs[ids],za[ids]);count[ids]+=1
    scores=total/count;scores=np.clip(scores,*np.quantile(scores,[.01,.99]))
    return scores,dict(state=sm,action=am,seed=seed)

class BC(nn.Module):
    def __init__(self,s,a):
        super().__init__();self.trunk=nn.Sequential(nn.Linear(s,128),nn.ReLU(),nn.Linear(128,64),nn.ReLU());self.head=nn.Linear(64,a)
    def forward(self,x):return self.head(self.trunk(x))

def qoq_score(obs,action,fit,reference,owners,seed,steps=1800):
    torch.manual_seed(seed);rng=np.random.default_rng(seed)
    x,xm,xs=standardize(obs[fit],obs);y,ym,ys=standardize(action[fit],action)
    x=torch.from_numpy(x);y=torch.from_numpy(y);m=BC(x.shape[1],y.shape[1]);opt=torch.optim.Adam(m.parameters(),lr=3e-4)
    for _ in range(steps):
        ids=rng.choice(fit,256);loss=(m(x[ids])-y[ids]).square().mean()
        opt.zero_grad();loss.backward();opt.step()
    # Exact factorization of final-linear-layer gradient cosine, no random projection.
    with torch.inference_mode():
        h=m.trunk(x);h=torch.cat([h,torch.ones(len(h),1)],1);err=m.head(h[:,:-1])-y
        h=nn.functional.normalize(h,dim=1);err=nn.functional.normalize(err,dim=1)
        output=[]
        for start in range(0,len(x),512):
            end=min(start+512,len(x));sim=(h[start:end]@h[reference].T)*(err[start:end]@err[reference].T)
            same=owners[start:end,None]==owners[reference][None,:]
            sim[torch.from_numpy(same)]=-float('inf')
            output.append(sim.max(1).values.numpy())
    return np.concatenate(output),dict(model=m.state_dict(),x_mean=xm,x_scale=xs,y_mean=ym,y_scale=ys,seed=seed,final_loss=float(loss.detach()))
