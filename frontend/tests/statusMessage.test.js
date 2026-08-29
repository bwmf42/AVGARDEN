import assert from 'node:assert/strict'
import test from 'node:test'

import { summarizeCheckMessage } from '../src/utils/statusMessage.js'

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
