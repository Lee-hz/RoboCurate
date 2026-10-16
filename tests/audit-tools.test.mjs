import test from 'node:test';
import assert from 'node:assert/strict';
import {AuditTools} from '../static/audit-tools.mjs';

test('retention saves through versioned review endpoint without resubmitting legacy QC',async()=>{
 const store=new Map();globalThis.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};
 const calls=[],record={id:'record',review:{revision:4,grade:'B',note:'existing',instruction:'pick',segments:[{start:1,end:3,label:'kept',grade:'B'}],event_decisions:{}}};
 const owner={root:{addEventListener(){},removeEventListener(){}},q:()=>null,message(){},api:async(url,body)=>{calls.push({url,body});return {reviews:{record:{...record.review,...body.changes[0].review,revision:5}}};}};
 const tools=new AuditTools(owner,record);tools.draft.event_decisions['a'.repeat(20)]='accepted';tools.persist();
 await tools.action({dataset:{audit:'save'}});
 assert.equal(calls[0].url,'/api/reviews');assert.equal('event_decisions' in calls[0].body.changes[0].review,false);assert.equal('event_evidence' in calls[0].body.changes[0].review,false);assert.equal(calls[0].body.changes[0].review.revision,4);
 assert.deepEqual(calls[0].body.changes[0].review.segments,record.review.segments);
 assert.equal(tools.draft.revision,5);assert.equal(tools.dirty,false);assert.equal(store.size,0);
});
test('save conflict preserves the draft and never silently retries with a new revision',async()=>{
 globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){throw Error('must retain draft');}};
 let calls=0;const owner={root:{addEventListener(){}},q:()=>null,api:async()=>{calls++;throw Error('revision conflict');}};
 const tools=new AuditTools(owner,{id:'record',review:{revision:7,grade:'',segments:[],event_decisions:{}}});tools.draft.note='pending';tools.persist();
 await assert.rejects(tools.action({dataset:{audit:'save'}}),/revision conflict/);
 assert.equal(calls,1);assert.equal(tools.draft.note,'pending');assert.equal(tools.draft.revision,7);assert.equal(tools.saving,false);
});
