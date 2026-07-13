const DASHES = /[\u2010\u2011\u2012\u2013\u2014\u2212\uff0d]/g

function prepare(value) {
  const text = String(value || '').normalize('NFKC').replace(DASHES, '-').trim().toUpperCase()
  if (!text || text.length > 64 || /[\x00-\x1f\x7f]/.test(text)) return ''
  if (text.includes('/') || text.includes('\\') || text.includes('..')) return ''
  return text
}

export function normalizeVideoId(value) {
  const text = prepare(value)
  if (!text) return ''

  let match = text.match(/^FC2(?:\s*[-_]?\s*PPV)?\s*[-_]?\s*(\d{5,8})$/)
  if (match) return `FC2-${match[1]}`

  match = text.match(/^HEY(?:DOUGA)?\s*[-_]?\s*(\d{4})\s*[-_]\s*0?(\d{3,5})$/)
  if (match) return `HEYDOUGA-${match[1]}-${match[2]}`

  match = text.match(/^(HEYZO|GETCHU|GYUTTO)\s*[-_]?\s*(\d{3,8})$/)
  if (match) return `${match[1]}-${match[2]}`

  match = text.match(/^(MKB?D)\s*[-_]?\s*(S\d{2,3})$/)
  if (match) return `${match[1]}-${match[2]}`

  match = text.match(/^(MK3D2DBD|S2M|S2MBD)\s*[-_]?\s*(\d{2,3})$/)
  if (match) return `${match[1]}-${match[2]}`

  match = text.match(/^(T[23]8)\s*[-_]?\s*(\d{3})$/)
  if (match) return `${match[1]}-${match[2]}`

  match = text.match(/^R18\s*[-_]?\s*(\d{3})$/)
  if (match) return `R18-${match[1]}`

  match = text.match(/^(IBW)\s*[-_]?\s*(\d{2,5}Z)$/)
  if (match) return `${match[1]}-${match[2]}`

  match = text.match(/^(\d{6})[-_](\d{2,3})$/)
  if (match) return `${match[1]}-${match[2]}`

  if (/^(?:(?:N|K)\d{4}|RED[01]\d{2}|SKY[0-3]\d{2}|EX00[01]\d)$/.test(text)) return text

  match = text.match(/^([A-Z0-9]*[A-Z][A-Z0-9]{0,15})\s*[-_]\s*(\d{2,8})([A-Z]?)$/)
  if (match) return `${match[1]}-${match[2]}${match[3]}`

  match = text.match(/^([0-9]*[A-Z][A-Z0-9]*[A-Z])(\d{2,8})([A-Z]?)$/)
  if (match && match[1].length <= 16) return `${match[1]}-${match[2]}${match[3]}`

  if (/^H_\d{3,4}[A-Z]{1,10}\d{2,5}[A-Z0-9]{0,8}$/.test(text)) return text
  if (/^\d{3}_\d{4,5}$/.test(text)) return text
  if (/^402[A-Z]{3,6}\d*_[A-Z]{3,8}\d{5,6}$/.test(text)) return text

  return ''
}
