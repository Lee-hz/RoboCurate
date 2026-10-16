import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewRange,Taskflow} from '../static/taskflow.mjs';

test('full and partial ranges preserve the exact recording endpoint',()=>{
  const end=30.842835583;
  assert.deepEqual(reviewRange(end,'full','',''),{start_s:0,end_s:end});
  assert.deepEqual(reviewRange(end,'custom','23',String(end)),{start_s:23,end_s:end});
});

test('invalid ranges cannot silently turn into whole-recording requests',()=>{
  for(const [a,b] of [['',2],[0,''],[' ',2],[-1,2],[2,2],[3,2],[0,31],[1,1.1],['NaN',2],[0,'Infinity']]){
    assert.throws(()=>reviewRange(30,'custom',a,b));
  }
  assert.throws(()=>reviewRange(undefined,'full',0,1));
});

function workbench(){
  const controls=Object.fromEntries(['target','reference','template','instruction','mode','range-mode','range-start','range-end','range-fields','range-summary','reuse-range','setup-dialog'].map(id=>['#tf-'+id,{value:'',close(){}}]));
  controls['#tf-target'].value='target';controls['#tf-reference'].value='reference';controls['#tf-template'].value='template';controls['#tf-mode'].value='state';
  const requests=[],panel=new Taskflow({querySelector:id=>controls[id]},async(path,body)=>requests.push({path,body}),s=>s);
  panel.assets=[{id:'target',duration_s:30.842835583},{id:'other',duration_s:12}];
  panel.overview={provider:{model:'HORIZON-MiniMax'}};panel.message=()=>{};panel.refresh=async()=>{};
  panel.syncReviewRange({start_s:23,end_s:30.842835583});
  return {panel,controls,requests};
}

test('both analysis modes submit the identical partial range; reference parsing stays full',async()=>{
  const {panel,controls,requests}=workbench();
  await panel.action({dataset:{tf:'review'}});
  controls['#tf-mode'].value='visual';panel.syncReviewRange();
  await panel.action({dataset:{tf:'review'}});
  assert.deepEqual(requests.map(r=>[r.body.analysis_mode,r.body.start_s,r.body.end_s]),[['state',23,30.842835583],['visual',23,30.842835583]]);
  await panel.action({dataset:{tf:'reference'}});
  assert.equal(requests[2].body.asset_id,'reference');
  assert.equal('start_s' in requests[2].body,false);
  assert.equal('end_s' in requests[2].body,false);
});

test('a bad range sends no request, and changing recording resets the bounds',async()=>{
  const {panel,controls,requests}=workbench();
  controls['#tf-range-end'].value='99';
  await assert.rejects(panel.action({dataset:{tf:'review'}}),/检查范围/);
  assert.equal(requests.length,0);
  controls['#tf-target'].value='other';panel.syncReviewRange();
  assert.deepEqual(panel.selectedReviewRange(),{start_s:0,end_s:12});
});

test('review and template parsing cannot submit with an OG model configured',async()=>{
  const {panel,requests}=workbench();panel.overview.provider.model='HORIZON-OG-Astra';
  await assert.rejects(panel.action({dataset:{tf:'review'}}),/仅使用 HORIZON-MiniMax/);
  await assert.rejects(panel.action({dataset:{tf:'reference'}}),/仅使用 HORIZON-MiniMax/);
  assert.equal(requests.length,0);
});

test('refresh preserves edited scope and reuse restores the current result scope',async()=>{
  const {panel,controls}=workbench();
  controls['#tf-range-start'].value='24';panel.syncReviewRange();
  assert.equal(panel.selectedReviewRange().start_s,24);
  panel.run={asset_id:'target',result:{analysis_range:{start_s:23,end_s:30.842835583}}};
  panel.refreshSetupPreview=()=>{};
  controls['#tf-target'].value='other';panel.syncReviewRange();
  await panel.action({dataset:{tf:'reuse-range'}});
  assert.equal(controls['#tf-target'].value,'target');
  assert.deepEqual(panel.selectedReviewRange(),{start_s:23,end_s:30.842835583});
});

test('retry restores the exact failed job inputs without submitting another request',async()=>{
  const {panel,controls,requests}=workbench();
  panel.overview.jobs=[{id:'failed',kind:'review',asset_id:'target',template_id:'template',analysis_mode:'state',analysis_range:{start_s:6,end_s:11},instruction:'保留失败尝试',state:'failed'}];
  let opened=false;panel.openSetup=()=>{opened=true};panel.refreshSetupPreview=()=>{};
  await panel.action({dataset:{tf:'retry-job',id:'failed'}});
  assert.equal(opened,true);assert.equal(requests.length,0);
  assert.equal(controls['#tf-template'].value,'template');
  assert.equal(controls['#tf-instruction'].value,'保留失败尝试');
  assert.deepEqual(panel.selectedReviewRange(),{start_s:6,end_s:11});
});

test('an active review cannot be accidentally submitted twice',async()=>{
  const {panel,requests}=workbench();
  panel.overview.jobs=[{asset_id:'target',kind:'review',state:'running'}];
  await assert.rejects(panel.action({dataset:{tf:'review'}}),/正在分析/);
  assert.equal(requests.length,0);
});

test('completion replaces an unreviewed playback shell with the real run',async()=>{
  const {panel}=workbench();
  panel.refresh=Taskflow.prototype.refresh;
  panel.run={id:null,previewOnly:true};panel.overview.runs=[];
  panel.overview.jobs=[{id:'job',kind:'review',state:'running'}];
  const data={runs:[{id:'finished',model:'HORIZON-MiniMax',analysis_mode:'state'}],jobs:[{id:'job',kind:'review',state:'completed'}]};
  panel.api=async()=>data;panel.updateOverview=value=>{panel.overview=value};
  const loaded=[];panel.loadRun=async id=>{loaded.push(id);panel.run={id}};
  await panel.refresh();assert.deepEqual(loaded,['finished']);
  await panel.refresh();assert.deepEqual(loaded,['finished']);
});

test('job status identifies active work and reports elapsed time without fake progress',async()=>{
  const {latestReviewJob,jobElapsed}=await import('../static/taskflow.mjs');
  const running={id:'active',kind:'review',state:'running',created_at:'2026-10-16T06:00:00Z'};
  assert.equal(latestReviewJob([{id:'old',kind:'review',state:'failed'},running]).id,'active');
  assert.equal(jobElapsed(running,Date.parse('2026-10-16T06:02:05Z')),'2:05');
  assert.equal(jobElapsed({created_at:'invalid'}),'');
});
