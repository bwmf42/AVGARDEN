import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeVideoId } from '../src/utils/videoId.js'

const cases = new Map([
  ['omg-032', 'OMG-032'],
  ['OMG032', 'OMG-032'],
  ['ABP984', 'ABP-984'],
  ['ＡＢＰ９８４', 'ABP-984'],
  ['300MIUM-1395', '300MIUM-1395'],
  ['300mium1395', '300MIUM-1395'],
  ['259luxu1234', '259LUXU-1234'],
  ['857OMG-032', '857OMG-032'],
  ['FC2 PPV 1234567', 'FC2-1234567'],
  ['fc2ppv_1234567', 'FC2-1234567'],
  ['062620_001', '062620-001'],
  ['HEYZO1009', 'HEYZO-1009'],
  ['heydouga-4017-0123', 'HEYDOUGA-4017-123'],
  ['T28557', 'T28-557'],
  ['IBW123Z', 'IBW-123Z'],
  ['N1234', 'N1234'],
  ['h_086abc00123', 'H_086ABC00123'],
])

test('normalizes supported video ID formats', () => {
  for (const [raw, expected] of cases) {
    assert.equal(normalizeVideoId(raw), expected, raw)
  }
})

test('rejects unsafe or ambiguous input', () => {
  for (const raw of ['../OMG-032', 'OMG-032; touch X', 'ABC', '123456', 'A/B-123', '']) {
    assert.equal(normalizeVideoId(raw), '', raw)
  }
})
