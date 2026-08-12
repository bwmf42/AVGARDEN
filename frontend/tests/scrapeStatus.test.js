import assert from 'node:assert/strict'
import test from 'node:test'

import { scrapeStatusMessage } from '../src/scrapeStatus.js'

test('formats the active scrape phase and progress', () => {
  assert.equal(scrapeStatusMessage({
    running: true,
    phase_label: '未看中文补链中',
    progress: { current: 2, total: 7, code: 'START-001' },
  }), '未看中文补链中 · 2/7 · START-001')
})

test('prefers the last error over a previous summary', () => {
  assert.equal(scrapeStatusMessage({
    running: false,
    last_error: '98堂安全验证失败',
    last_summary: '旧摘要',
  }), '上次未完成：98堂安全验证失败')
})

test('formats the completion summary', () => {
  assert.equal(scrapeStatusMessage({ running: false, last_summary: '更新 3 条' }), '上次完成：更新 3 条')
})
