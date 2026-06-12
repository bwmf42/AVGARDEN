<template>
    <div class="container">
        <div class="page-head">
            <h1>搜索结果</h1>
            <div class="query-pill">{{ query }}</div>
        </div>

        <div v-if="loading" class="loading">加载中...</div>
        <div v-else-if="!query" class="empty">请输入搜索内容</div>
        <div v-else-if="results.length === 0" class="empty">没有找到相关影片</div>

        <div v-else class="result-sections">
            <div v-if="localResults.length" class="section">
                <h2>本地片 ({{ localResults.length }})</h2>
                <div class="video-grid">
                    <div v-for="video in localResults" :key="'local-' + video.id" class="video-card" @click="openResult(video)">
                        <div class="cover-container">
                            <img class="cover local-cover" :src="video.poster || video.cover" :alt="video.title" loading="lazy">
                            <div class="source-badge local">本地</div>
                        </div>
                        <div class="info">
                            <h3>{{ displayTitle(video) }}</h3>
                            <div v-if="video.actresses && video.actresses.length" class="actresses">
                                {{ video.actresses.slice(0, 3).join(' / ') }}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div v-if="weeklyResults.length" class="section">
                <h2>刮削片 ({{ weeklyResults.length }})</h2>
                <div class="video-grid">
                    <div v-for="video in weeklyResults" :key="'weekly-' + video.id" class="video-card" @click="openResult(video)">
                        <div class="cover-container">
                            <img class="cover" :src="video.cover || video.poster || getDmmFallback(video)" :alt="video.title" loading="lazy">
                            <div class="source-badge weekly">刮削</div>
                            <div v-if="video.hasChinese" class="badge chinese">中文</div>
                        </div>
                        <div class="info">
                            <h3>{{ displayTitle(video) }}</h3>
                            <div v-if="video.actresses && video.actresses.length" class="actresses">
                                {{ video.actresses.slice(0, 3).join(' / ') }}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script>
import videosApi from '../api/videos'

function normalizeText(value) {
    return String(value || '').trim().toUpperCase()
}

export default {
    name: 'SearchView',
    data() {
        return {
            loading: true,
            localItems: [],
            weeklyItems: []
        }
    },
    computed: {
        query() {
            return String(this.$route.query.q || '').trim()
        },
        normalizedQuery() {
            return normalizeText(this.query)
        },
        localResults() {
            return this.localItems
                .filter(video => this.matches(video))
                .map(video => ({ ...video, source: 'local' }))
        },
        weeklyResults() {
            const localIDs = new Set(this.localResults.map(video => normalizeText(video.id)))
            return this.weeklyItems
                .filter(video => !localIDs.has(normalizeText(video.id)))
                .filter(video => this.matches(video))
                .map(video => ({ ...video, source: 'weekly' }))
        },
        results() {
            return [...this.localResults, ...this.weeklyResults]
        }
    },
    async created() {
        await this.loadData()
    },
    async beforeRouteUpdate(to, from, next) {
        next()
        await this.loadData()
    },
    methods: {
        async loadData() {
            this.loading = true
            try {
                const [local, weeklyResp] = await Promise.all([
                    videosApi.getVideoList(),
                    fetch('/api/weekly')
                ])
                this.localItems = Array.isArray(local) ? local : []
                this.weeklyItems = weeklyResp.ok ? await weeklyResp.json() : []
            } catch (e) {
                console.error(e)
            } finally {
                this.loading = false
            }
        },
        matches(video) {
            const q = this.normalizedQuery
            if (!q) return false
            const fields = [
                video.id,
                video.title,
                video.titleZh,
                video.titleJp,
                ...(Array.isArray(video.actresses) ? video.actresses : [])
            ]
            return fields.some(field => normalizeText(field).includes(q))
        },
        displayTitle(video) {
            let title = video.titleZh || video.title || video.id
            const id = video.id || ''
            if (id && !normalizeText(title).startsWith(normalizeText(id))) {
                title = `${id} ${title}`
            }
            return title
        },
        getDmmFallback(video) {
            const c = (video.id || '').toLowerCase().replace('-', '')
            return c ? `https://pics.dmm.co.jp/mono/movie/adult/${c}/${c}pl.jpg` : ''
        },
        openResult(video) {
            if (video.source === 'local') {
                this.$router.push({ name: 'detail', params: { id: video.id } })
                return
            }
            this.$router.push({ name: 'weekly-detail', params: { id: video.id }, query: { tab: 'unwatched' } })
        }
    }
}
</script>

<style scoped>
.container { padding: 0; }

.page-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 1.25rem;
  flex-wrap: wrap;
}

h1 {
  color: var(--text-color);
  margin: 0;
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

.query-pill {
  color: var(--secondary-color);
  background: var(--surface);
  border: 1px solid var(--rose-line);
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 13px;
  font-weight: 800;
}

.loading,
.empty {
  text-align: center;
  color: var(--muted-color);
  padding: 40px;
  font-size: 15px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.section {
  margin-bottom: 28px;
}

h2 {
  margin: 0 0 12px;
  font-size: 16px;
  color: var(--text-color);
  font-weight: 800;
}

.video-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 18px;
  padding: 14px 0;
}

.video-card {
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
  background: var(--surface);
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--line);
  box-shadow: var(--shadow-soft);
  position: relative;
}

.video-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 3px;
  background: var(--primary-color);
  z-index: 3;
}

.video-card:hover {
  transform: translateY(-2px);
  border-color: var(--rose-line);
  box-shadow: var(--shadow-hover);
}

.cover-container {
  position: relative;
  width: 100%;
  padding-top: 137.78%;
  overflow: hidden;
  background: #f6edf2;
}

.cover {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.source-badge,
.badge {
  position: absolute;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  z-index: 4;
  border: 1px solid rgba(255,255,255,0.7);
  backdrop-filter: blur(8px);
}

.source-badge {
  top: 8px;
  right: 8px;
}

.source-badge.local {
  background: rgba(40, 122, 67, 0.9);
  color: white;
}

.source-badge.weekly {
  background: rgba(186, 47, 93, 0.9);
  color: white;
}

.badge.chinese {
  top: 8px;
  left: 8px;
  background: rgba(161, 92, 0, 0.9);
  color: white;
}

.info {
  padding: 12px;
  background: var(--surface);
  border-top: 1px solid var(--line);
}

h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 750;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--text-color);
  line-height: 1.45;
}

.actresses {
  font-size: 12px;
  color: var(--muted-color);
  margin-top: 6px;
}
</style>
