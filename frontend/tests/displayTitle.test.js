import test from 'node:test'
import assert from 'node:assert/strict'

import { displayTitle, isUsableTitleZh } from '../src/utils/displayTitle.js'

test('uses a real Chinese translation', () => {
  const video = {
    id: 'START-999',
    title: 'START-999 Japanese source title',
    titleZh: '测试中文标题'
  }

  assert.equal(isUsableTitleZh(video.titleZh, video.title, video.id), true)
  assert.equal(displayTitle(video), '测试中文标题')
  assert.equal(displayTitle(video, { withCode: true }), 'START-999 测试中文标题')
})

test('falls back when titleZh is only a code or studio residue', () => {
  const source = 'START-999 Complete source title'

  assert.equal(displayTitle({ id: 'START-999', title: source, titleZh: 'START-999' }), source)
  assert.equal(displayTitle({ id: 'START-999', title: source, titleZh: 'START' }), source)
})

test('falls back when titleZh still contains Japanese kana', () => {
  const video = {
    id: 'START-999',
    title: 'START-999 完整原始标题',
    titleZh: 'テスト标题'
  }

  assert.equal(isUsableTitleZh(video.titleZh, video.title, video.id), false)
  assert.equal(displayTitle(video), video.title)
})

test('keeps list formatting stable when fields are missing', () => {
  assert.equal(displayTitle({ id: 'ABC-123' }, { withCode: true, maxLen: 50 }), 'ABC-123')
  assert.equal(
    displayTitle({ id: 'ABC-123', titleZh: '这是一个很长的中文标题' }, { maxLen: 5 }),
    '这是一个很...'
  )
})
