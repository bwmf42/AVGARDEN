import test from 'node:test'
import assert from 'node:assert/strict'
import { partitionPerformers } from '../src/utils/performers.js'

test('legacy age/job labels are descriptions while formal credits remain interactive names', () => {
    assert.deepEqual(partitionPerformers({ actresses: ['京香 大学生モデル', '真央 19さい', '鈴村あいり', '結城りえ(24)'] }), {
        names: ['鈴村あいり'], notes: ['京香 大学生モデル', '真央 19さい', '結城りえ(24)']
    })
})
test('explicit amateur nickname notes stay separate and are deduplicated', () => {
    assert.deepEqual(partitionPerformers({ actresses: ['彩月', '河北彩伽'], performerNotes: ['彩月', '彩月'] }), {
        names: ['河北彩伽'], notes: ['彩月']
    })
})
