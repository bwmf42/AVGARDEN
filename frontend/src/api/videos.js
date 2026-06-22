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
        console.log(id);
        const pattern = /^([A-Z0-9]+)-\d+$/;

        if (!id.trim()) {
            alert('请输入视频内容', true);
            return;
        }

        if (!pattern.test(id)) {
            alert('格式错误：请输入(字母或数字)-数字的组合，如 ABC-123', true);
            return;
        }

        this.isAdding = true;
        try {
            const response = await axios.get(`${API_BASE}/api/addvideo/${encodeURIComponent(id)}`, {
                headers: {
                    'Authorization': `Bearer ${API_KEY}`
                }
            });
            console.log(response.data);

            if (response.status >= 200 && response.status < 300) {
                this.inputContent = ''; // 清空输入框
                // 使用原生alert替代ElMessage
                alert('视频添加成功');
            } else {
                alert(response.data.message || '添加视频失败');
            }
        } catch (error) {
            console.error('添加视频出错:', error);
            alert(`添加视频失败: ${error.message}`);
        } finally {
            this.isAdding = false;
        }
    }
}
