<template>
    <div class="container">
        <div class="library-hero">
            <div>
                <span>媒体库</span>
                <h1>本地影片</h1>
                <p>来自 NAS 视频目录和已生成的元数据。</p>
            </div>
            <div class="library-count">{{ videos.length }} 项</div>
        </div>

        <div v-if="videos.length === 0" class="empty-state">暂无本地影片</div>
        <div v-else class="video-grid">
            <VideoCard v-for="video in videos" :key="video.id" :video="video" @click="navigateToDetail(video.id)" />
        </div>
    </div>
</template>

<script>
import VideoCard from '../components/VideoCard.vue'
import videosApi from '../api/videos'

export default {
    name: 'HomeView', // 必须声明name用于keep-alive匹配
    components: { VideoCard },
    data() {
        return {
            videos: [],
            scrollPosition: 0
        }
    },
    async created() {
        // 从缓存恢复数据或重新加载
        if (!this.videos.length) {
            this.videos = await videosApi.getVideoList()
        }
    },
    async activated() {
        // 每次切回首页时刷新视频列表
        this.videos = await videosApi.getVideoList()
        window.scrollTo(0, this.scrollPosition)
        },
        beforeRouteLeave(to, from, next) {
        // 离开时保存滚动位置
        this.scrollPosition = window.scrollY
        next()
    },
    methods: {
        navigateToDetail(id) {
            this.$router.push({ name: 'detail', params: { id } })
        }
    }
}
</script>

<style scoped>
.container {
  padding: 0;
}

.library-hero {
  min-height: 184px;
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 26px;
  padding: 26px;
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  background:
    linear-gradient(110deg, rgba(255,255,255,0.96) 0 46%, rgba(255,242,247,0.9) 46% 100%),
    repeating-linear-gradient(90deg, rgba(186,47,93,0.08) 0 1px, transparent 1px 22px);
  box-shadow: var(--shadow-soft);
}

.library-hero span {
  color: var(--secondary-color);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

h1 {
  color: var(--text-color);
  margin: 10px 0 8px;
  font-size: clamp(32px, 4vw, 56px);
  line-height: 1.03;
  font-weight: 900;
}

.library-hero p {
  max-width: 480px;
  margin: 0;
  color: var(--muted-color);
  font-size: 14px;
  line-height: 1.7;
}

.library-count {
  flex: 0 0 auto;
  padding: 9px 12px;
  border: 1px solid var(--rose-line);
  border-radius: 999px;
  background: var(--surface);
  color: var(--secondary-color);
  font-size: 13px;
  font-weight: 900;
}

.video-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(166px, 1fr));
  gap: 18px;
  padding: 14px 0;
}

.empty-state {
  padding: 40px;
  text-align: center;
  color: var(--muted-color);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
}

@media (max-width: 640px) {
  .library-hero {
    min-height: 0;
    align-items: start;
    flex-direction: column;
    padding: 20px;
  }
}
</style>
