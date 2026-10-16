#!/usr/bin/env python3
"""Download the official Qwen CPU trial weights and verify published hashes."""
import concurrent.futures,hashlib,json,os,tarfile,time,urllib.request,urllib.parse
from pathlib import Path
root=(Path(__file__).resolve().parents[1]/'workspace/local-vlm').resolve();models=root/'models'/'Qwen3-VL-2B-Instruct';models.mkdir(parents=True,exist_ok=True)
model='Qwen/Qwen3-VL-2B-Instruct-GGUF'
meta=json.load(urllib.request.urlopen('https://modelscope.cn/api/v1/models/'+model+'/repo/files?Revision=master&Recursive=true',timeout=30))
files={f['Path']:f for f in meta['Data']['Files'] if f['Type']=='blob'}
release=json.load(urllib.request.urlopen('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11429',timeout=30))
a=next(a for a in release['assets'] if a['name']=='llama-b11429-bin-ubuntu-x64.tar.gz')
items=[]
for name in ['Qwen3VL-2B-Instruct-Q4_K_M.gguf','mmproj-Qwen3VL-2B-Instruct-F16.gguf','README.md']:
 f=files[name];url='https://modelscope.cn/api/v1/models/'+model+'/repo?Revision='+f['Revision']+'&FilePath='+urllib.parse.quote(name)
 items.append(dict(name=name,url=url,path=str(models/name),size=f['Size'],sha256=f['Sha256']))
items.append(dict(name=a['name'],url=a['browser_download_url'],path=str(root/a['name']),size=a['size'],sha256=(a.get('digest') or '').removeprefix('sha256:')))
manifest=dict(model=model,model_source='https://modelscope.cn/models/'+model,license='Apache-2.0 (official model card)',runtime_release=release['html_url'],files=items)
(root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
def download(item):
 path=Path(item['path']);partial=path.with_suffix(path.suffix+'.part')
 def verified(p):
  if not p.exists() or p.stat().st_size!=item['size']:return False
  digest=hashlib.file_digest(p.open('rb'),'sha256').hexdigest() if hasattr(hashlib,'file_digest') else sha(p)
  return not item['sha256'] or digest==item['sha256']
 def sha(p):
  h=hashlib.sha256()
  with p.open('rb') as f:
   for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
  return h.hexdigest()
 if verified(path):print('VERIFIED existing',item['name'],flush=True);return
 for attempt in range(4):
  try:
   offset=partial.stat().st_size if partial.exists() else 0
   req=urllib.request.Request(item['url'],headers={'Range':f'bytes={offset}-'} if offset else {})
   with urllib.request.urlopen(req,timeout=60) as r:
    if offset and r.status!=206:offset=0
    mode='ab' if offset else 'wb';last=time.monotonic();count=offset
    with partial.open(mode) as out:
     while True:
      block=r.read(4*1024**2)
      if not block:break
      out.write(block);count+=len(block)
      if time.monotonic()-last>8:
       print('DOWNLOAD',item['name'],f'{count/1024**2:.0f}/{item["size"]/1024**2:.0f} MiB',flush=True);last=time.monotonic()
   if not verified(partial):raise ValueError('size or SHA256 mismatch')
   partial.replace(path);item['verified_sha256']=sha(path);print('VERIFIED',item['name'],flush=True);return
  except Exception as e:
   print('RETRY',item['name'],attempt+1,type(e).__name__,flush=True)
   if attempt==3:raise
   if partial.exists() and partial.stat().st_size>=item['size']:partial.unlink()
   time.sleep(2)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(download,items))
(root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
archive=root/a['name'];destination=root/'llama-b11429';destination.mkdir(exist_ok=True)
with tarfile.open(archive) as tar:
 for member in tar.getmembers():
  candidate=(destination/member.name).resolve()
  if not candidate.is_relative_to(destination.resolve()):raise ValueError('unsafe archive path')
  if member.issym() or member.islnk():
   target=(candidate.parent/member.linkname).resolve()
   if not target.is_relative_to(destination.resolve()):raise ValueError('unsafe archive link')
  if member.isdev():raise ValueError('archive contains device')
 tar.extractall(destination)
print('SETUP_COMPLETE',root,flush=True)
