import assert from 'node:assert/strict'
import test from 'node:test'
import { downloadStatusText, downloadChannel, failureReason } from '../src/utils/downloadStatus.js'

test('reports the actual transfer engine rather than the requested local target', () => {
  assert.equal(downloadStatusText({ target: 'qb', transport: 'online', status: 'downloading' }), '在线流 · 下载中')
  assert.equal(downloadStatusText({ transport: 'qb', status: 'downloading' }), 'qB · 下载中')
  assert.equal(downloadChannel({ target: 'qb' }), '本地')
})

test('cloud jobs describe resolution and submission, not local download progress', () => {
  assert.equal(downloadStatusText({ target: '115', status: 'queued' }), '115 · 等待提交')
  assert.equal(downloadStatusText({ target: '115', phase: 'resolving', status: 'downloading' }), '115 · 查找磁链')
  assert.equal(downloadStatusText({ target: '115', phase: 'submitting', status: 'downloading' }), '115 · 提交中')
})

test('failed items expose the real reason, truncated with the full text kept for the tooltip', () => {
  assert.deepEqual(failureReason({ message: '无可用磁链（115 仅支持磁链云下载）' }, 8), {
    text: '无可用磁链（11…', full: '无可用磁链（115 仅支持磁链云下载）',
  })
  assert.deepEqual(failureReason({ message: ' 短原因 ' }), { text: '短原因', full: '短原因' })
  assert.deepEqual(failureReason({}), { text: '', full: '' })
})
