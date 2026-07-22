import axios from 'axios'

// 空字符串 = 同域请求（前端由 Go 后端 serve 静态文件，API 同域）
const API_BASE = ''
const API_KEY = import.meta.env.VITE_API_KEY || ''

export default {
    async getVideoList() {
        const response = await axios.get(`${API_BASE}/api/videos`)
        const videos = Array.isArray(response.data) ? response.data : []
        return videos.map(video => ({
            ...video,
            poster: `${API_BASE}${video.poster}` // 拼接完整URL
        }))
    },

    async getVideoDetail(id) {
        const response = await axios.get(`${API_BASE}/api/videos/${encodeURIComponent(id)}`)
        const data = response.data
        const fanarts = data.fanarts || []

        // 处理详情数据中的路径
        return {
            ...data,
            poster: fanarts.length ? `${API_BASE}${fanarts[0]}` : null,
            videoFile: data.videoFile ? `${API_BASE}${data.videoFile}` : null,
            fanarts: fanarts.map(img => `${API_BASE}${img}`)
        }
    },

    async addVideo(id) {
        // Align with backend normalizeUserVideoID: allow FC2 / 300MIUM / etc.
        const raw = (id || '').trim()
        if (!raw) {
            alert('请输入视频内容')
            return
        }
        // Loose client check; server is the source of truth for normalization.
        if (!/^[A-Za-z0-9][A-Za-z0-9._\-\s]{1,40}$/.test(raw)) {
            alert('格式错误：请输入番号，如 ABC-123 或 300MIUM-1395')
            return
        }
        if (!API_KEY) {
            alert('前端未配置 API 密钥（构建时需注入 VITE_API_KEY，与后端 API_KEY 一致）')
            return
        }

        this.isAdding = true
        try {
            const response = await axios.get(`${API_BASE}/api/addvideo/${encodeURIComponent(raw)}`, {
                headers: {
                    Authorization: `Bearer ${API_KEY}`,
                },
            })

            if (response.status >= 200 && response.status < 300) {
                this.inputContent = ''
                alert(typeof response.data === 'string' ? response.data : '视频添加成功')
            } else {
                alert((response.data && response.data.message) || '添加视频失败')
            }
        } catch (error) {
            const detail =
                error.response?.data?.error ||
                error.response?.data ||
                error.message ||
                '未知错误'
            alert(`添加视频失败: ${detail}`)
        } finally {
            this.isAdding = false
        }
    }
}
