<template>
    <div class="container">
        <h1>媒体库</h1>
        <div class="video-grid">
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

h1 {
  color: var(--text-color);
  margin: 0 0 1.25rem;
  font-size: 24px;
  font-weight: 800;
  position: relative;
  display: inline-block;
}

h1::after {
  content: '';
  position: absolute;
  bottom: -8px;
  left: 0;
  width: 42px;
  height: 2px;
  background: var(--primary-color);
}

.video-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 18px;
  padding: 14px 0;
}
</style>
