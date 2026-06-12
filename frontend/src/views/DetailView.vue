<template>
    <div class="detail-wrapper">
        <!-- 左右翻页按钮 -->
        <button
            class="page-nav prev"
            :class="{ disabled: currentIndex <= 0 }"
            :disabled="currentIndex <= 0"
            @click="goPrev"
            aria-label="上一页"
        >
            <svg width="28" height="28" viewBox="0 0 24 24">
                <path fill="currentColor" d="M15.41 16.09l-4.58-4.59 4.58-4.59L14 5.5l-6 6 6 6z"/>
            </svg>
        </button>
        <button
            class="page-nav next"
            :class="{ disabled: currentIndex >= videoList.length - 1 }"
            :disabled="currentIndex >= videoList.length - 1"
            @click="goNext"
            aria-label="下一页"
        >
            <svg width="28" height="28" viewBox="0 0 24 24">
                <path fill="currentColor" d="M8.59 16.34l4.58-4.59-4.58-4.59L10 5.75l6 6-6 6z"/>
            </svg>
        </button>

        <div class="detail-container" v-if="video">
            <div class="header">
                <div class="header-main">
                    <div class="header-title">
                        <h1>{{ video.title }}</h1>
                        <p class="release-date">发行日期: {{ video.releaseDate }}</p>
                    </div>
                    <div class="pagination top-pagination" v-if="videoList.length > 1">
                        <button
                            class="page-btn"
                            :disabled="currentIndex <= 0"
                            @click="goPrev"
                        >上一页</button>
                        <span class="page-info">{{ currentIndex + 1 }} / {{ videoList.length }}</span>
                        <button
                            class="page-btn"
                            :disabled="currentIndex >= videoList.length - 1"
                            @click="goNext"
                        >下一页</button>
                    </div>
                </div>
            </div>

            <div class="content">
                <div class="poster">
                    <img :src="video.poster" :alt="video.title">
                </div>

                <Gallery :images="video.fanarts" />
            </div>
        </div>
    </div>
</template>

<script>
import Gallery from '../components/Gallery.vue'
import videosApi from '../api/videos'

export default {
    components: { Gallery },
    props: ['id'],
    data() {
        return {
            video: null,
            videoList: [],
            currentIndex: -1
        }
    },
    async created() {
        this.videoList = await videosApi.getVideoList()
        this.currentIndex = this.videoList.findIndex(v => v.id === this.id)
        this.video = await videosApi.getVideoDetail(this.id)
        document.addEventListener('keydown', this.handleKeydown)
    },
    beforeUnmount() {
        document.removeEventListener('keydown', this.handleKeydown)
    },
    methods: {
        goPrev() {
            if (this.currentIndex > 0) {
                const prev = this.videoList[this.currentIndex - 1]
                this.$router.push({ name: 'detail', params: { id: prev.id } })
            }
        },
        goNext() {
            if (this.currentIndex < this.videoList.length - 1) {
                const next = this.videoList[this.currentIndex + 1]
                this.$router.push({ name: 'detail', params: { id: next.id } })
            }
        },
        handleKeydown(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
            if (e.key === 'ArrowLeft') this.goPrev()
            if (e.key === 'ArrowRight') this.goNext()
        }
    }
}
</script>

<style scoped>
.detail-wrapper {
  position: relative;
  max-width: 1200px;
  margin: 0 auto;
}

.page-nav {
  position: fixed;
  top: 50%;
  transform: translateY(-50%);
  z-index: 100;
  width: 48px;
  height: 48px;
  border-radius: 999px;
  border: 1px solid var(--rose-line);
  background: rgba(255, 255, 255, 0.92);
  color: var(--secondary-color);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-soft);
  transition: all 0.18s ease;
  backdrop-filter: blur(12px);
}

.page-nav:hover:not(.disabled) {
  background: var(--primary-color);
  color: #fff;
  border-color: var(--primary-color);
  box-shadow: var(--shadow-hover);
  transform: translateY(-50%) translateY(-1px);
}

.page-nav.disabled {
  opacity: 0.35;
  cursor: default;
}

.prev {
  left: -72px;
}

.next {
  right: -72px;
}

.detail-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 22px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-top: 3px solid var(--primary-color);
  border-radius: 8px;
  box-shadow: var(--shadow-soft);
}

.header {
  margin-bottom: 18px;
}

.header-main {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.header-title {
  min-width: 0;
}

.header h1 {
  color: var(--text-color);
  font-size: 24px;
  line-height: 1.35;
  margin: 0 0 8px;
  font-weight: 800;
}

.release-date {
  display: inline-flex;
  color: var(--secondary-color);
  background: var(--surface-2);
  border: 1px solid var(--rose-line);
  border-radius: 999px;
  font-size: 13px;
  font-weight: 800;
  padding: 5px 10px;
  margin: 0;
}

.content {
  display: grid;
  gap: 18px;
}

.poster {
  background: #f7eef3;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}

.poster img {
  width: 100%;
  max-height: 520px;
  object-fit: contain;
  display: block;
}

.video-player {
  margin-top: 2rem;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--line);
  box-shadow: var(--shadow-soft);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 24px;
  padding: 12px 0;
}

.top-pagination {
  justify-content: flex-end;
  margin: 0;
  padding: 0;
  flex: 0 0 auto;
}

.page-info {
  font-size: 14px;
  color: var(--secondary-color);
  font-weight: 800;
  min-width: 80px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.page-btn {
  padding: 8px 18px;
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--secondary-color);
  font-size: 14px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.18s ease;
}

.page-btn:hover:not(:disabled) {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: #fff;
}

.page-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

@media (max-width: 1400px) {
  .prev { left: 12px; }
  .next { right: 12px; }
}

@media (max-width: 768px) {
  .header-main {
    align-items: stretch;
    flex-direction: column;
  }

  .top-pagination {
    justify-content: flex-start;
  }

  .page-nav {
    width: 40px;
    height: 40px;
  }

  .prev { left: 8px; }
  .next { right: 8px; }

  .detail-container {
    padding: 16px;
  }
}
</style>
