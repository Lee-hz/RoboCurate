import test from 'node:test';
import assert from 'node:assert/strict';
import {advancePlayback} from '../static/playback-clock.mjs';

test('queued frame before a play click cannot rewind or produce negative time', () => {
  assert.equal(advancePlayback(0, 1000, 4100, 1, 48.48), 0);
  assert.equal(advancePlayback(19.61, 1000, 4100, 1, 48.48), 19.61);
});
test('normal playback preserves selected speed and stops at the record boundary', () => {
  assert.equal(advancePlayback(10, 1050, 1000, 2, 48.48), 10.1);
  assert.equal(advancePlayback(48.45, 1050, 1000, 1, 48.48), 48.48);
});
test('resuming after a long blocked frame does not skip an unseen interval', () => {
  assert.equal(advancePlayback(10, 31000, 1000, 1, 48.48), 10.1);
});
