import assert from 'node:assert/strict'
import test from 'node:test'

import { summarizeCheckMessage, p115HealthCheck, recentFailureEvents } from '../src/utils/statusMessage.js'

test('valid cookie remains healthy while cloud download is disabled', () => {
  assert.deepEqual(p115HealthCheck({ has_cookies: true, verified: true, enabled: false, available: false }), {
    ok: true, msg: 'Cookie 有效 · 功能未启用',
  })
  assert.equal(p115HealthCheck({ has_cookies: true, verified: false, enabled: true }).ok, false)
})

test('failure window uses current NAS clock and its timezone, not snapshot time', () => {
  const recent = { ts: '2026-10-11 17:26:25' }
  assert.deepEqual(recentFailureEvents([
    { ts: '2026-10-11 14:40:12' }, recent,
    { ts: 'invalid' }, { ts: '2026-10-12 17:00:00' },
  ], '2026-10-12T16:00:00+08:00'), [recent])
  assert.deepEqual(recentFailureEvents([recent], '2026-10-12T17:27:00+08:00'), [])
})

test('shortens relay 503 json', () => {
  assert.equal(
    summarizeCheckMessage('HTTP 503: {"error":{"message":"Service temporarily unavailable","type":"api_error"}}'),
    '服务暂不可用',
  )
})

test('shortens unknown provider 400', () => {
  assert.equal(
    summarizeCheckMessage('HTTP 400: {"error":{"message":"unknown provider for model gpt-5.4"}}'),
    '模型不可用 (gpt-5.4)',
  )
})

test('keeps short chinese cookie errors', () => {
  assert.equal(summarizeCheckMessage('登录超时，请重新登录。'), '登录超时，请重新登录。')
})

test('falls back when empty', () => {
  assert.equal(summarizeCheckMessage(''), '异常')
})
