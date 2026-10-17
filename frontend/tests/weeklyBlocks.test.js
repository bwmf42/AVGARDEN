import test from 'node:test'
import assert from 'node:assert/strict'
import { filterBlockedVideos, nextRemainingVideo } from '../src/utils/weeklyBlocks.js'

const items = [
    { id: 'A', actresses: ['one', 'two'], genres: ['x', 'y'] },
    { id: 'B', actresses: ['one'], genres: ['z'] },
    { id: 'C', actresses: ['three'], genres: ['y'] },
    { id: 'D', actresses: ['four'], genres: ['z'] },
    { id: 'E' }
]

test('multiple actor and genre blocks remove every matching title without mutating the detail snapshot', () => {
    const remaining = filterBlockedVideos(items, { actresses: ['one', 'two'], genres: ['y'] })
    assert.deepEqual(remaining.map(item => item.id), ['D', 'E'])
    assert.equal(items.length, 5)
    assert.equal(nextRemainingVideo(items, 'A', remaining).id, 'D')
})

test('confirmation continues in original order, wraps at the end, and handles an empty list', () => {
    const remaining = [items[1], items[3]]
    assert.equal(nextRemainingVideo(items, 'C', remaining).id, 'D')
    assert.equal(nextRemainingVideo(items, 'E', remaining).id, 'B')
    assert.equal(nextRemainingVideo(items, 'A', []), undefined)
    assert.equal(nextRemainingVideo([], 'A', []), undefined)
})
