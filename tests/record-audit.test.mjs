import test from 'node:test';
import assert from 'node:assert/strict';
import {taskOutcome,recordingAudits,preferredRun,auditStatus} from '../static/record-audit.mjs';

const run=(id,asset,model='HORIZON-MiniMax')=>({id,asset_id:asset,model,summary:{segment_count:3},reviewed_segments:0,analysis_range:{start_s:23,end_s:30.84}});
const overview={assets:[{id:'a',name:'same',source:{kind:'recording',id:'r1'}},{id:'b',name:'same',source:{kind:'recording',id:'r2'}}],runs:[run('old','a','OG-Astra'),run('new','a'),run('other','b')],jobs:[]};

test('record identity scopes every run even when display names coincide',()=>{
  assert.deepEqual(recordingAudits(overview,'r1').runs.map(r=>r.id),['old','new']);
  assert.deepEqual(recordingAudits(overview,'missing').runs,[]);
  assert.equal(preferredRun(recordingAudits(overview,'r1').runs).id,'new');
});
test('model success is pending human review and displays partial scope',()=>{
  const status=auditStatus(overview,'r1');
  assert.equal(status.key,'pending');
  assert.match(status.detail,/23.0–30.8s/);
  assert.match(status.detail,/人工 0\/3/);
  assert.equal(auditStatus(overview,'missing').key,'not_started');
  assert.equal(auditStatus(null,'r1').key,'unavailable');
});
test('reviewed and active statuses are scoped to the recording',()=>{
  const data=structuredClone(overview);data.runs[1].reviewed_segments=3;
  assert.equal(auditStatus(data,'r1').key,'reviewed');
  data.jobs=[{kind:'review',asset_id:'b',state:'running'}];
  assert.equal(auditStatus(data,'r1').key,'reviewed');
  assert.equal(auditStatus(data,'r2').key,'running');
});


test('task screening keeps failed attempts even if other stages completed',()=>{
 const overview={assets:[{id:'a',source:{kind:'recording',id:'r'}}],runs:[{id:'run',asset_id:'a',model:'HORIZON-MiniMax',analysis_mode:'state',summary:{segment_count:3,completed:2,not_completed:1,uncertain:0},analysis_range:{start_s:23,end_s:30}}]};
 assert.equal(taskOutcome(overview,'r').key,'failed');
 overview.runs[0].summary={segment_count:3,completed:3,not_completed:0,uncertain:0};
 const outcome=taskOutcome(overview,'r');assert.equal(outcome.label,'已分析阶段均完成');assert.match(outcome.detail,/23.0–30.0s/);assert.match(outcome.detail,/待复核/);
});
test('no run, unavailable service, and historical providers cannot masquerade as MiniMax conclusions',()=>{
 assert.equal(taskOutcome(null,'r').key,'unavailable');
 assert.equal(taskOutcome({assets:[],runs:[]},'r').key,'not_started');
 const overview={assets:[{id:'a',source:{kind:'recording',id:'r'}}],runs:[{asset_id:'a',model:'OG-Astra',summary:{completed:3,segment_count:3}}]};
 assert.equal(taskOutcome(overview,'r').key,'legacy');
});

test('stage filters independently include failed and uncertain attempts in the same range',async()=>{
  const {matchesTaskOutcome}=await import('../static/record-audit.mjs');
  const data={assets:overview.assets,runs:[{...run('mixed','a'),summary:{segment_count:3,completed:1,not_completed:1,uncertain:1}}],jobs:[]};
  assert.equal(matchesTaskOutcome(data,'r1','failed'),true);
  assert.equal(matchesTaskOutcome(data,'r1','uncertain'),true);
  assert.equal(matchesTaskOutcome(data,'r1','completed'),false);
  assert.equal(matchesTaskOutcome(data,'r2','failed'),false);
  assert.equal(matchesTaskOutcome(null,'r1','completed'),false);
  data.runs[0].summary={segment_count:3,completed:3,not_completed:0,uncertain:0};
  assert.equal(matchesTaskOutcome(data,'r1','completed'),true);
  assert.equal(auditStatus(data,'r1').key,'pending');
  assert.match(auditStatus(data,'r1').detail,/23.0–30.8s/);
  data.runs[0].model='OG-Astra';
  assert.equal(auditStatus(data,'r1').key,'legacy');
  for(const filter of ['failed','uncertain','completed'])assert.equal(matchesTaskOutcome(data,'r1',filter),false);
});

test('manual retention filters distinguish unset, deferred and outdated decisions',async()=>{
  const {matchesRetention}=await import('../static/record-audit.mjs');
  const record={review:{grade:null},review_stale:false};
  assert.equal(matchesRetention(record,'unreviewed'),true);
  assert.equal(matchesRetention(record,'C'),false);
  record.review.grade='C';
  assert.equal(matchesRetention(record,'unreviewed'),false);
  assert.equal(matchesRetention(record,'C'),true);
  record.review.grade='A';record.review_stale=true;
  assert.equal(matchesRetention(record,'A'),false);
  assert.equal(matchesRetention(record,'stale'),true);
  assert.equal(matchesRetention(record,''),true);
});

test('a failed first analysis stays distinguishable from a never-started recording',()=>{
  const data={assets:overview.assets,runs:[],jobs:[{kind:'review',asset_id:'a',state:'failed',message:'模型输出不完整'}]};
  assert.equal(auditStatus(data,'r1').key,'failed');
  assert.equal(auditStatus(data,'r2').key,'not_started');
  data.jobs.unshift({kind:'review',asset_id:'a',state:'running'});
  assert.equal(auditStatus(data,'r1').key,'running');
});
