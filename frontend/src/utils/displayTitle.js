/**
 * Prefer a real Chinese titleZh; fall back to the source title when titleZh is
 * a studio/code residue or an obviously incomplete translation.
 */

const KANA_RE = /[\u3040-\u309f\u30a0-\u30ff]/
const HAN_RE = /[\u4e00-\u9fff]/

function stripCodePrefix(text, videoId) {
  let body = String(text || '').trim()
  const id = String(videoId || '').trim()
  if (!body) return ''
  if (id) {
    const re = new RegExp(`^${id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*[:：\\-]?\\s*`, 'i')
    body = body.replace(re, '').trim()
  }
  // studio prefix only: ROYD from ROYD-342
  const studio = id.includes('-') ? id.split('-')[0] : ''
  if (studio && body.toUpperCase() === studio.toUpperCase()) {
    return ''
  }
  return body
}

export function isUsableTitleZh(titleZh, sourceTitle = '', videoId = '') {
  const zh = String(titleZh || '').trim()
  if (!zh) return false
  // Kana left in titleZh means it is not a completed Chinese translation.
  if (KANA_RE.test(zh)) return false
  const id = String(videoId || '').trim()
  if (id && zh.toUpperCase() === id.toUpperCase()) return false

  const body = stripCodePrefix(zh, id)
  if (!body || body.length <= 1) return false

  // Studio-only residue: IPZZ / ROYD / HUNTC.
  const studio = id.includes('-') ? id.split('-')[0] : ''
  if (studio && body.toUpperCase() === studio.toUpperCase()) return false
  if (/^[A-Z]{2,12}$/i.test(body) && !HAN_RE.test(body)) return false

  const source = String(sourceTitle || '').trim()
  // A short Latin/code-like token is usually another provider residue.
  if (!HAN_RE.test(body) && /^[A-Za-z0-9][A-Za-z0-9\s\-_.]*$/.test(body) && body.length < 12) {
    return false
  }
  if (!HAN_RE.test(body) && body.length < 10) {
    return false
  }
  if (source.length >= 30 && body.length < 4) return false
  if (source.length >= 60 && body.length < 8 && body.length * 8 < source.length) return false
  return true
}

/**
 * @param {object} video
 * @param {{ withCode?: boolean, maxLen?: number }} [opts]
 */
export function displayTitle(video, opts = {}) {
  const v = video || {}
  const id = String(v.id || '').trim()
  const source = String(v.title || v.titleJp || '').trim()
  const zh = String(v.titleZh || '').trim()
  let t = isUsableTitleZh(zh, source, id) ? zh : (source || zh || id)

  if (opts.withCode && id) {
    const upper = t.toUpperCase()
    const idUpper = id.toUpperCase()
    if (!upper.startsWith(idUpper)) {
      t = `${id} ${t}`
    }
  }
  const maxLen = opts.maxLen
  if (maxLen && t.length > maxLen) {
    return t.slice(0, maxLen) + '...'
  }
  return t
}
