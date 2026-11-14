import assert from 'node:assert/strict';
import test from 'node:test';
import {requestKeyFor} from '../tools/scene/request_identity.mjs';

const exec = (session, callId) => ({agent: {session: {id: session}}, callId});

test('request keys bind a DSH session and the exact outer or PTC tool call', () => {
  assert.equal(requestKeyFor({}, exec('session-a', 'call-a')), 'dsh:session-a:call-a');
  assert.equal(requestKeyFor({}, exec('session-a', 'call-a:ptc:1')), 'dsh:session-a:call-a:ptc:1');
  assert.notEqual(requestKeyFor({}, exec('session-a', 'call-a')), requestKeyFor({}, exec('session-b', 'call-a')));
  assert.notEqual(requestKeyFor({}, exec('session-a', 'call-a:ptc:0')),
    requestKeyFor({}, exec('session-a', 'call-a:ptc:1')));
});

test('an explicit request key is preserved without mutating the submitted arguments', () => {
  const args = Object.freeze({request_key: 'operator-request'});
  const before = JSON.stringify(args);
  assert.equal(requestKeyFor(args, exec('session-a', 'call-a')), 'operator-request');
  assert.equal(JSON.stringify(args), before);
});
