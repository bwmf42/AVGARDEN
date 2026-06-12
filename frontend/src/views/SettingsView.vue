<template>
    <div class="container">
        <h1 class="page-title">设置</h1>

        <div class="tabs">
            <button v-for="t in tabs" :key="t.key" :class="['tab', { active: activeTab === t.key }]" @click="activeTab = t.key">
                {{ t.label }}
            </button>
        </div>

        <div class="section scrape-section">
            <div class="scrape-copy">
                <h2>周推荐刮削</h2>
                <p>{{ scrapeMessage }}</p>
            </div>
            <button class="scrape-btn" :disabled="scrapeRunning" @click="runWeeklyScrape">
                {{ scrapeRunning ? '刮削中...' : '手动刮削' }}
            </button>
        </div>

        <div class="section">
            <div class="add-row">
                <input v-model="newItem" :placeholder="'添加' + currentTab.label" class="add-input"
                    @keyup.enter="addItem" />
                <button class="add-btn" @click="addItem">添加</button>
            </div>

            <div class="list">
                <div v-for="item in currentList" :key="item" class="list-item">
                    <span>{{ item }}</span>
                    <button class="del-btn" @click="removeItem(item)">移除</button>
                </div>
                <div v-if="currentList.length === 0" class="empty">暂无</div>
            </div>
        </div>
    </div>
</template>

<script>
const ENDPOINTS = {
    actresses: '/api/block-actress/',
    genres: '/api/block-genre/',
    favs: '/api/fav-actress/',
    keywords: '/api/block-keyword/',
}

export default {
    name: 'SettingsView',
    data() {
        return {
            activeTab: 'actresses',
            newItem: '',
            actresses: [],
            genres: [],
            favs: [],
            keywords: [],
            scrapeRunning: false,
            scrapeMessage: '手动更新每日推荐，适合错过当天自动刮削时使用。',
        }
    },
    computed: {
        tabs() {
            return [
                { key: 'actresses', label: '屏蔽女优' },
                { key: 'genres', label: '屏蔽标签' },
                { key: 'favs', label: '收藏女优' },
                { key: 'keywords', label: '标题关键词' },
            ]
        },
        currentTab() { return this.tabs.find(t => t.key === this.activeTab) || this.tabs[0] },
        currentList() { return this[this.activeTab] || [] },
    },
    async created() {
        await this.loadAll()
    },
    methods: {
        async loadAll() {
            await this.loadList('actresses')
            await this.loadList('genres')
            await this.loadList('favs')
            await this.loadList('keywords')
        },
        async loadList(key) {
            try {
                const r = await fetch(ENDPOINTS[key])
                if (r.ok) {
                    this[key] = await r.json()
                }
            } catch (e) { }
        },
        async addItem() {
            const v = this.newItem.trim()
            if (!v) return
            const url = ENDPOINTS[this.activeTab]
            try {
                await fetch(url + encodeURIComponent(v), { method: 'POST' })
                if (!this.currentList.includes(v)) this.currentList.push(v)
                this.newItem = ''
            } catch (e) { }
        },
        async removeItem(item) {
            const url = ENDPOINTS[this.activeTab]
            try {
                await fetch(url + encodeURIComponent(item), { method: 'POST' })
                const idx = this.currentList.indexOf(item)
                if (idx >= 0) this.currentList.splice(idx, 1)
            } catch (e) { }
        },
        async runWeeklyScrape() {
            if (this.scrapeRunning) return
            this.scrapeRunning = true
            this.scrapeMessage = '正在抓取并更新周推荐，完成前不要重复点击。'
            try {
                const resp = await fetch('/api/weekly/scrape', { method: 'POST' })
                const data = await resp.json().catch(() => ({}))
                if (!resp.ok) {
                    this.scrapeMessage = data.message || '刮削失败，请稍后重试。'
                    return
                }
                this.scrapeMessage = data.message || '周推荐刮削完成。'
            } catch (e) {
                this.scrapeMessage = '刮削请求失败，请检查服务状态。'
            } finally {
                this.scrapeRunning = false
            }
        },
    }
}
</script>

<style scoped>
.container {
  max-width: 660px;
  margin: 0 auto;
}

.page-title {
  color: var(--text-color);
  font-size: 24px;
  font-weight: 800;
  margin: 0 0 1.25rem;
  position: relative;
  display: inline-block;
}

.page-title::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: -8px;
  width: 42px;
  height: 2px;
  background: var(--primary-color);
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.tab {
  padding: 8px 13px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--muted-color);
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 800;
  transition: all 0.18s ease;
}

.tab:hover {
  border-color: var(--rose-line);
  color: var(--secondary-color);
}

.tab.active {
  background: var(--secondary-color);
  border-color: var(--secondary-color);
  color: white;
}

.section {
  background: var(--surface);
  border: 1px solid var(--line);
  border-top: 3px solid var(--primary-color);
  border-radius: 8px;
  padding: 18px;
  box-shadow: var(--shadow-soft);
}

.scrape-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.scrape-copy {
  min-width: 0;
}

.scrape-copy h2 {
  margin: 0 0 6px;
  color: var(--text-color);
  font-size: 16px;
  font-weight: 800;
}

.scrape-copy p {
  margin: 0;
  color: var(--muted-color);
  font-size: 13px;
  line-height: 1.5;
}

.add-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.add-input {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  background: var(--surface);
  color: var(--text-color);
}

.add-input:focus {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(232, 77, 122, 0.12);
}

.add-btn {
  padding: 10px 18px;
  background: var(--primary-color);
  color: white;
  border: 1px solid var(--primary-color);
  border-radius: 8px;
  cursor: pointer;
  font-weight: 800;
  transition: all 0.18s ease;
}

.add-btn:hover {
  background: var(--secondary-color);
  border-color: var(--secondary-color);
}

.scrape-btn {
  flex: 0 0 auto;
  padding: 10px 18px;
  background: var(--primary-color);
  color: white;
  border: 1px solid var(--primary-color);
  border-radius: 8px;
  cursor: pointer;
  font-weight: 800;
  transition: all 0.18s ease;
}

.scrape-btn:hover:not(:disabled) {
  background: var(--secondary-color);
  border-color: var(--secondary-color);
}

.scrape-btn:disabled {
  cursor: wait;
  opacity: 0.68;
}

.list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.list-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 9px 7px 11px;
  background: var(--surface-2);
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  font-size: 13px;
  color: var(--secondary-color);
  font-weight: 700;
}

.del-btn {
  background: #fff5f4;
  border: 1px solid #ffd0cc;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: var(--danger-color);
  padding: 3px 6px;
  font-weight: 800;
}

.del-btn:hover {
  background: var(--danger-color);
  color: white;
  border-color: var(--danger-color);
}

.empty {
  color: var(--muted-color);
  font-size: 14px;
}

@media (max-width: 520px) {
  .scrape-section {
    align-items: stretch;
    flex-direction: column;
  }

  .add-row {
    flex-direction: column;
  }
}
</style>
