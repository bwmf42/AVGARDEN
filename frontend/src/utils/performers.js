const profilePattern = /\d{1,3}\s*(?:歳|才|岁|さい|years?\s*old)|[（(]\s*\d{1,3}\s*[）)]|大学生|女子大生|専門学生|学生モデル|モデル|会社員|専業主婦|主婦|フリーター|アルバイト|職業|职业|看護師|护士|保育士|店員|受付|新規\s*\d+\s*分コース|腋もアナルも綺麗|^(?:個人撮影|カップル)$/i

export function partitionPerformers(video = {}) {
    const names = [], notes = []
    for (const value of Array.isArray(video.performerNotes) ? video.performerNotes : []) {
        const text = String(value || '').trim()
        if (text && !notes.includes(text)) notes.push(text)
    }
    for (const value of Array.isArray(video.actresses) ? video.actresses : []) {
        const text = String(value || '').trim()
        const target = profilePattern.test(text) || notes.includes(text) ? notes : names
        if (text && !target.includes(text)) target.push(text)
    }
    return { names, notes }
}
