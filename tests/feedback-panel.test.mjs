import test from 'node:test';
import assert from 'node:assert/strict';
import {feedbackSample,relatedRequests} from '../static/feedback-panel.mjs';

test('playback is causal, preserves gaps, and cannot hold values beyond data',()=>{
  const data={rate_hz:20,times_s:[0,.05,.1],channels:[{key:'state.q',values:[[1],[null],[3]]}]};
  assert.deepEqual(feedbackSample(data,'state.q',0,.049),{time:0,value:1});
  assert.deepEqual(feedbackSample(data,'state.q',0,.06),{time:.05,value:null});
  assert.equal(feedbackSample(data,'state.q',0,.15).value,null);
  assert.equal(feedbackSample(data,'missing',0,.1).value,null);
});

test('request scopes use overlap, not frame observation window or a neighboring segment',()=>{
  const manifest={requests:[{id:'overlap',range:{start_s:2,end_s:4}},{id:'after',range:{start_s:4,end_s:6}},{id:'before',range:{start_s:0,end_s:2}}]};
  assert.deepEqual(relatedRequests(manifest,{start_s:2,end_s:4}).map(r=>r.id),['overlap']);
  assert.deepEqual(relatedRequests(null,{start_s:0,end_s:1}),[]);
});
