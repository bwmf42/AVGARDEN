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
