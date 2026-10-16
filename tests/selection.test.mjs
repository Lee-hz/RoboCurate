import test from 'node:test';
import assert from 'node:assert/strict';
import {selectCandidates} from '../static/selection.mjs';
const row=(id,grade,score,extra={})=>({id,quality:{grading:{grade,method:'deminf_qualified_v2'},rating:{score}},...extra});
test('only qualified rows with current method enter candidate manifests',()=>{
 const rows=[row('a','A',9),row('b','B',6),row('c','C',2),...['D','E','R','U'].map(g=>row(g,g,10)),row('unknown','A',null),row('dup','A',9,{curation:{duplicate_of:'a'}}),{id:'legacy',quality:{grading:{grade:'A'},rating:{score:9.98}}}];
 assert.deepEqual(selectCandidates(rows),['a','b','c']);
 assert.deepEqual(selectCandidates(rows,true),['a']);
 assert.deepEqual(selectCandidates(rows.slice(2),true),[]);
});
