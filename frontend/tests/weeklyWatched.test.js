import test from 'node:test'
import assert from 'node:assert/strict'

import { mergeWatchedSources } from '../src/api/weeklyWatched.js'


test('server becomes authoritative after the one-time watched migration', () => {
    assert.deepEqual(
        mergeWatchedSources(['KEEP-001'], ['EXPIRED-001'], [], true),
        ['KEEP-001']
    )
})

test('local watched IDs are included during first migration', () => {
    assert.deepEqual(
        mergeWatchedSources(['SERVER-001'], ['LOCAL-001'], ['SESSION-001'], false),
        ['SERVER-001', 'LOCAL-001', 'SESSION-001']
    )
})
