export function p115HealthCheck(config) {
  const ok = !!config.has_cookies && !!config.verified
  return {
    ok,
    msg: ok
      ? (config.enabled ? 'Cookie 有效' : 'Cookie 有效 · 功能未启用')
      : (config.message || 'Cookie 已失效，请到设置重新测试连接'),
  }
}

export function recentFailureEvents(events, serverTime = '') {
  const now = Date.parse(serverTime) || Date.now()
  // Log timestamps omit their zone. Use the API clock's zone, even when the
  // browser is abroad, rather than interpreting NAS timestamps as browser time.
  const zone = String(serverTime).match(/(Z|[+-]\d{2}:\d{2})$/)?.[1] || ''
  return (Array.isArray(events) ? events : []).filter(event => {
    let raw = String(event?.ts || '').replace(' ', 'T')
    if (!/(Z|[+-]\d{2}:\d{2})$/.test(raw)) raw += zone
    const ts = Date.parse(raw)
    return Number.isFinite(ts) && ts >= now - 24 * 3600 * 1000 && ts <= now
  })
}

function extractJsonMessage(raw) {
  const text = String(raw || '').trim()
  if (!text) return ''
  try {
    const parsed = JSON.parse(text)
    return String(parsed?.error?.message || parsed?.message || parsed?.msg || '').trim()
  } catch (e) {
    const match = text.match(/"message"\s*:\s*"((?:\\.|[^"\\])*)"/)
    if (!match) return ''
    return match[1].replace(/\\"/g, '"').replace(/\\n/g, ' ').trim()
  }
}

export function summarizeCheckMessage(raw, fallback = '异常') {
  const text = String(raw || '').replace(/\s+/g, ' ').trim()
  if (!text) return fallback

  const http = text.match(/^HTTP\s+(\d+)\s*:?\s*(.*)$/i)
  if (http) {
    const code = http[1]
    let extracted = extractJsonMessage(http[2]) || http[2].trim()
    // Drop noisy request ids so short Chinese API errors stay readable.
    extracted = extracted.replace(/\s*\(request id:[^)]+\)\s*/gi, '').trim()
    if (/无权访问/.test(extracted)) {
      return extracted.length <= 28 ? extracted : '无权访问该模型分组'
    }
    if (code === '503') return '服务暂不可用'
    if (/unknown provider/i.test(extracted)) {
      const model = extracted.match(/model\s+([^\s"]+)/i)
      return model ? `模型不可用 (${model[1]})` : '模型不可用'
    }
    if (/model[_ ]?not[_ ]?found/i.test(extracted)) return '模型不可用'
    if (extracted && extracted.length <= 40 && !extracted.startsWith('{')) return extracted
    return `请求失败 (${code})`
  }

  if (text.startsWith('{') && extractJsonMessage(text)) {
    return summarizeCheckMessage(extractJsonMessage(text), fallback)
  }

  if (text.length > 48) return `${text.slice(0, 46)}…`
  return text
}
