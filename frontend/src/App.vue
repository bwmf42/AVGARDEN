<template>
  <div id="app">
    <div class="app-shell">
      <aside class="app-sidebar">
        <router-link to="/" class="logo">
          <h1>AV/GARDEN</h1>
          <span>NAS 媒体库</span>
        </router-link>

        <nav class="side-nav" aria-label="主导航">
          <router-link to="/" class="nav-link">媒体库</router-link>
          <router-link to="/weekly" class="nav-link">每日推荐</router-link>
          <router-link to="/download" class="nav-link">下载管理</router-link>
          <router-link to="/settings" class="nav-link">设置</router-link>
          <router-link to="/logs" class="nav-link">日志</router-link>
        </nav>

        <div class="scrape-card">
          <strong>周推荐刮削</strong>
          <p>手动更新每日推荐会触发 worker 容器内的 weekly_updater.py。</p>
          <button type="button" class="sidebar-action" :disabled="scrapeRunning" @click="runWeeklyScrape">
            {{ scrapeRunning ? '刮削中...' : '手动刮削' }}
          </button>
        </div>
      </aside>

      <div class="content-column">
        <header class="app-header">
          <input 
            v-model="inputContent" 
            type="text" 
            placeholder="搜索番号、标题、演员或标签"
            class="search-input"
            @keyup.enter="handleSearch"
          >
          <button class="search-button ghost" @click="handleSearch">
            搜索
          </button>
          <button 
            class="search-button"
            @click="handleAddVideo"
            :disabled="isAdding"
          >
            {{ isAdding ? '添加中...' : '添加' }}
          </button>
        </header>

        <!-- 全局状态栏 -->
        <div v-if="statusBar.visible" class="status-bar">
          <span v-for="item in statusBar.items" :key="item.id" class="status-item" :class="item.status">
            <span class="status-dot"></span>
            <button type="button" class="status-code" @click="openStatusDetail(item)">
              {{ statusDisplayID(item.id) }}
            </button>
            <template v-if="item.status === 'queued'">等待中</template>
            <template v-if="item.status === 'downloading'">
              {{ progressPercent(item) }}%
              <span v-if="item.speed > 0"> {{ formatSpeed(item.speed) }}</span>
            </template>
            <template v-if="item.status === 'failed'">下载失败</template>
            <a
              v-if="item.status === 'failed'"
              class="status-javbus"
              :href="javbusURL(item.id)"
              target="_blank"
              rel="noreferrer"
              @click.stop
            >
              JavBus
            </a>
            <button
              v-if="item.status === 'failed'"
              type="button"
              class="status-dismiss"
              :aria-label="`忽略 ${item.id} 下载失败提示`"
              title="忽略此失败提示"
              @click.stop="dismissFailedStatus(item)"
            >
              关闭
            </button>
          </span>
        </div>

        <main class="app-main">
          <router-view v-slot="{ Component }">
            <keep-alive :include="['HomeView', 'WeeklyView']">
              <component :is="Component" :key="$route.fullPath" />
            </keep-alive>
          </router-view>
        </main>

        <footer class="app-footer">
          <p>© 2026 AV/GARDEN</p>
        </footer>
      </div>

      <aside class="activity-rail">
        <div class="activity-head">
          <h2>活动</h2>
          <span>{{ statusSummary }}</span>
        </div>

        <div v-if="primaryActiveItem" class="activity-card">
          <strong>下载中的条目</strong>
          <button type="button" class="activity-code" @click="openStatusDetail(primaryActiveItem)">
            {{ statusDisplayID(primaryActiveItem.id) }}
          </button>
          <div class="rail-progress">
            <span :style="{ width: progressPercent(primaryActiveItem) + '%' }"></span>
          </div>
          <p>{{ progressPercent(primaryActiveItem) }}%<span v-if="primaryActiveItem.speed > 0"> · {{ formatSpeed(primaryActiveItem.speed) }}</span></p>
        </div>
        <div v-else class="activity-card muted-card">
          <strong>下载中的条目</strong>
          <p>暂无进行中的下载。</p>
        </div>

        <div class="activity-card">
          <strong>队列</strong>
          <div v-if="visibleQueueItems.length" class="queue-mini-list">
            <div v-for="item in visibleQueueItems" :key="item.id" class="queue-mini-row">
              <span class="rail-status" :class="item.status">{{ statusText(item) }}</span>
              <button type="button" @click="openStatusDetail(item)">{{ statusDisplayID(item.id) }}</button>
            </div>
          </div>
          <p v-else>没有等待、下载中或最近失败的条目。</p>
        </div>

        <div class="activity-card">
          <strong>日志摘要</strong>
          <p>日志页保留浅色表格和可读文本，不使用黑色终端块。</p>
        </div>
      </aside>
    </div>

    <!-- 全局 Toast -->
    <div v-if="toast.visible" class="global-toast" :class="toast.type">
        {{ toast.msg }}
    </div>
  </div>
</template>

<script>
function normalizeStatusID(id) {
  return String(id || '').trim().toUpperCase()
}

function normalizeVideoCode(id) {
  const normalized = normalizeStatusID(id)
  const sourcePrefixed = normalized.match(/^420([A-Z]+-\d+)$/)
  return sourcePrefixed ? sourcePrefixed[1] : normalized
}

function normalizeInputID(value) {
  return normalizeStatusID(value)
}

export default {
  name: 'App',
  data() {
    return {
      inputContent: '',
      isAdding: false,
      scrapeRunning: false,
      toast: { visible: false, msg: '', type: 'info' },
      statusBar: { visible: false, items: [] },
      statusTimer: null
    }
  },
  computed: {
    activeStatusItems() {
      return this.statusBar.items.filter(item => item.status !== 'failed')
    },
    failedStatusItems() {
      return this.statusBar.items.filter(item => item.status === 'failed')
    },
    primaryActiveItem() {
      return this.activeStatusItems.find(item => item.status === 'downloading') || this.activeStatusItems[0] || null
    },
    visibleQueueItems() {
      return [...this.activeStatusItems, ...this.failedStatusItems].slice(0, 6)
    },
    statusSummary() {
      if (!this.statusBar.items.length) return '空闲'
      const active = this.activeStatusItems.length
      const failed = this.failedStatusItems.length
      const parts = []
      if (active) parts.push(`${active} 个进行中`)
      if (failed) parts.push(`${failed} 个失败`)
      return parts.join(' · ')
    }
  },
  mounted() {
    window.addEventListener('av-garden-toast', this.onToast)
    window.addEventListener('av-garden-refresh-status', this.fetchStatus)
    this.fetchStatus()
    this.statusTimer = setInterval(() => this.fetchStatus(), 60000)
  },
  beforeUnmount() {
    window.removeEventListener('av-garden-toast', this.onToast)
    window.removeEventListener('av-garden-refresh-status', this.fetchStatus)
    if (this.statusTimer) clearInterval(this.statusTimer)
  },
  methods: {
    onToast(e) {
      this.toast = { visible: true, msg: e.detail.msg, type: e.detail.type || 'info' }
      setTimeout(() => { this.toast.visible = false }, 4000)
    },
    async handleAddVideo() {
      const code = normalizeInputID(this.inputContent)
      if (!code) {
        this.showToast('请输入番号', 'warn')
        return
      }
      if (!/^([A-Z0-9]+)-\d+$/.test(code)) {
        this.showToast('格式错误，请输入 ABC-123 这样的番号', 'warn')
        return
      }
      this.isAdding = true
      try {
        const resp = await fetch('/api/queue/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code })
        })
        if (!resp.ok) {
          this.showToast(`${code} 添加失败，请重试`, 'warn')
          return
        }
        this.inputContent = ''
        this.showToast(`${code} 已加入下载队列`, 'info')
        this.fetchStatus()
      } catch (e) {
        this.showToast(`${code} 添加失败，请重试`, 'warn')
      } finally {
        this.isAdding = false
      }
    },
    handleSearch() {
      const q = this.inputContent.trim()
      if (!q) {
        this.showToast('请输入搜索内容', 'warn')
        return
      }
      this.$router.push({ name: 'search', query: { q } })
    },
    showToast(msg, type = 'info') {
      window.dispatchEvent(new CustomEvent('av-garden-toast', { detail: { msg, type } }))
    },
    async fetchStatus() {
      try {
        const resp = await fetch('/api/queue-status')
        if (!resp.ok) return
        const data = await resp.json()
        const items = [...data.active, ...data.failed].filter(item => item.status !== 'done')
        window.avGardenQueueStatus = items
        window.dispatchEvent(new CustomEvent('av-garden-status', { detail: { items } }))
        this.applyVisibleStatusItems(items)
      } catch(e) {}
    },
    applyVisibleStatusItems(items) {
      this.statusBar.items = items
      this.statusBar.visible = items.length > 0
    },
    async dismissFailedStatus(item) {
      const id = normalizeStatusID(item.id)
      if (!id || item.status !== 'failed') return
      this.applyVisibleStatusItems((window.avGardenQueueStatus || []).filter(status => normalizeStatusID(status.id) !== id))
      try {
        await fetch(`/api/failed-ack/${encodeURIComponent(id)}`, { method: 'POST' })
        await this.fetchStatus()
      } catch (e) {}
    },
    openStatusDetail(item) {
      const id = normalizeVideoCode(item.id)
      if (!id) return
      this.$router.push({ name: 'weekly-detail', params: { id }, query: { tab: 'unwatched' } })
    },
    javbusURL(id) {
      return `https://www.javbus.com/${encodeURIComponent(normalizeVideoCode(id))}`
    },
    statusDisplayID(id) {
      return normalizeVideoCode(id)
    },
    statusText(item) {
      const map = { queued: '等待', downloading: 'qB', failed: '失败' }
      return map[item.status] || item.status
    },
    progressPercent(item) {
      const raw = item.progress_pct ?? item.progress ?? 0
      const value = Number(raw)
      if (!Number.isFinite(value)) return 0
      return Math.max(0, Math.min(100, Math.round(value)))
    },
    formatSpeed(bps) {
      if (!bps || bps === 0) return ''
      if (bps < 1024*1024) return (bps/1024).toFixed(0) + 'KB/s'
      return (bps/1024/1024).toFixed(1) + 'MB/s'
    },
    async runWeeklyScrape() {
      if (this.scrapeRunning) return
      this.scrapeRunning = true
      try {
        const resp = await fetch('/api/weekly/scrape', { method: 'POST' })
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          this.showToast(data.message || '周推荐刮削启动失败', 'warn')
          return
        }
        this.showToast(data.message || '周推荐刮削已开始', 'info')
      } catch (e) {
        this.showToast('刮削请求失败，请检查服务状态', 'warn')
      } finally {
        this.scrapeRunning = false
      }
    }
  }
}
</script>

<style>
/* 全局基础样式 */
:root {
  --app-bg: #fff7fa;
  --surface: #ffffff;
  --surface-2: #fffbfd;
  --line: #eadde3;
  --rose-line: #f3c6d4;
  --primary-color: #e84d7a;
  --secondary-color: #ba2f5d;
  --accent-color: #f9dbe5;
  --text-color: #35242c;
  --muted-color: #80636f;
  --success-color: #287a43;
  --warning-color: #a15c00;
  --danger-color: #b42318;
  --info-color: #2563eb;
  --shadow-soft: 0 8px 24px rgba(186, 47, 93, 0.08);
  --shadow-hover: 0 14px 32px rgba(186, 47, 93, 0.12);
}

body {
  margin: 0;
  padding: 0;
  font-family: Inter, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
  color: var(--text-color);
  background:
    linear-gradient(rgba(232, 77, 122, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(232, 77, 122, 0.045) 1px, transparent 1px),
    var(--app-bg);
  background-size: 32px 32px;
  letter-spacing: 0;
}

#app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr) 330px;
}

.app-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 22px;
  padding: 18px;
  background: rgba(255, 255, 255, 0.86);
  border-right: 1px solid var(--rose-line);
  backdrop-filter: blur(14px);
  z-index: 40;
}

.logo {
  display: grid;
  gap: 6px;
  padding: 8px 4px 16px;
  color: var(--secondary-color);
  text-decoration: none;
  border-bottom: 1px solid var(--line);
}

.logo h1 {
  margin: 0;
  color: var(--secondary-color);
  font-size: 18px;
  font-weight: 900;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

.logo span {
  color: var(--muted-color);
  font-size: 12px;
  line-height: 1.5;
}

.side-nav {
  display: grid;
  align-content: start;
  gap: 6px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 10px 11px;
  border-radius: 8px;
  color: var(--muted-color);
  text-decoration: none;
  font-size: 14px;
  font-weight: 800;
  border: 1px solid transparent;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

.nav-link::before {
  content: "";
  width: 9px;
  height: 9px;
  border: 1px solid currentColor;
  border-radius: 2px;
  flex: 0 0 auto;
}

.nav-link:hover,
.nav-link.router-link-active {
  color: var(--secondary-color);
  background: #fff2f7;
  border-color: var(--rose-line);
}

.scrape-card {
  padding: 13px;
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  background: var(--surface-2);
  box-shadow: 0 10px 26px rgba(186, 47, 93, 0.06);
}

.scrape-card strong {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
}

.scrape-card p {
  margin: 0 0 10px;
  color: var(--muted-color);
  font-size: 12px;
  line-height: 1.5;
}

.sidebar-action {
  width: 100%;
  min-height: 34px;
  border: 1px solid var(--primary-color);
  border-radius: 8px;
  background: var(--primary-color);
  color: white;
  font-weight: 800;
  cursor: pointer;
}

.sidebar-action:disabled {
  cursor: default;
  opacity: 0.66;
}

.content-column {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 30;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 18px 22px 12px;
  background: rgba(255, 247, 250, 0.88);
  border-bottom: 1px solid rgba(243, 198, 212, 0.78);
  backdrop-filter: blur(14px);
}

.search-input {
  padding: 8px 12px;
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  outline: none;
  font-size: 14px;
  width: 100%;
  min-width: 0;
  height: 42px;
  transition: all 0.18s ease;
  background-color: var(--surface);
  color: var(--text-color);
  box-shadow: 0 8px 24px rgba(186, 47, 93, 0.06);
}

.search-input::placeholder {
  color: #bfa5af;
}

.search-input:focus {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(232, 77, 122, 0.12);
}

.search-button {
  background-color: var(--primary-color);
  color: white;
  border: 1px solid var(--primary-color);
  padding: 8px 14px;
  border-radius: 8px;
  height: 40px;
  cursor: pointer;
  font-weight: 800;
  transition: all 0.18s ease;
  white-space: nowrap;
}

.search-button:hover {
  background-color: var(--secondary-color);
  border-color: var(--secondary-color);
}

.search-button.ghost {
  background: var(--surface);
  color: var(--secondary-color);
  border-color: var(--rose-line);
}

.search-button.ghost:hover {
  background: var(--surface-2);
  color: var(--primary-color);
  border-color: var(--primary-color);
}

/* 主内容区 */
.app-main {
  flex: 1;
  min-width: 0;
  padding: 20px 22px 34px;
  max-width: 1320px;
  width: 100%;
  margin: 0 auto;
}

/* 底部样式 */
.app-footer {
  text-align: center;
  padding: 1rem 1.2rem;
  border-top: 1px solid var(--rose-line);
  color: var(--muted-color);
  font-size: 0.82rem;
  background: rgba(255, 255, 255, 0.82);
}

.activity-rail {
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 18px;
  border-left: 1px solid var(--rose-line);
  background: rgba(255, 251, 253, 0.94);
  overflow: auto;
}

.activity-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin: 4px 0 14px;
}

.activity-head h2 {
  margin: 0;
  font-size: 18px;
}

.activity-head span {
  color: var(--muted-color);
  font-size: 12px;
  font-weight: 800;
}

.activity-card {
  margin-bottom: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: 0 10px 26px rgba(186, 47, 93, 0.055);
}

.activity-card strong {
  display: block;
  margin-bottom: 8px;
  font-size: 14px;
}

.activity-card p {
  margin: 0;
  color: var(--muted-color);
  font-size: 12px;
  line-height: 1.55;
}

.muted-card {
  background: var(--surface-2);
}

.activity-code {
  appearance: none;
  display: block;
  width: 100%;
  margin-bottom: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-color);
  text-align: left;
  font-size: 15px;
  font-weight: 900;
  cursor: pointer;
}

.rail-progress {
  height: 7px;
  margin: 10px 0 8px;
  border-radius: 999px;
  background: #eef2f7;
  overflow: hidden;
}

.rail-progress span {
  display: block;
  height: 100%;
  min-width: 5%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--info-color), var(--primary-color));
}

.queue-mini-list {
  display: grid;
  gap: 0;
}

.queue-mini-row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 10px 0;
  border-top: 1px solid var(--line);
}

.queue-mini-row:first-child {
  border-top: 0;
  padding-top: 0;
}

.queue-mini-row button {
  appearance: none;
  min-width: 0;
  padding: 0;
  overflow: hidden;
  border: 0;
  background: transparent;
  color: var(--text-color);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.rail-status {
  width: max-content;
  padding: 3px 7px;
  border-radius: 999px;
  background: #f3f9ff;
  color: var(--info-color);
  font-size: 12px;
  font-weight: 800;
}

.rail-status.queued {
  background: #fff9ed;
  color: var(--warning-color);
}

.rail-status.failed {
  background: #fff5f4;
  color: var(--danger-color);
}

/* 响应式调整 */
@media (max-width: 1220px) {
  .app-shell {
    grid-template-columns: 190px minmax(0, 1fr);
  }

  .activity-rail {
    position: static;
    grid-column: 1 / -1;
    height: auto;
    border-left: 0;
    border-top: 1px solid var(--rose-line);
  }
}

@media (max-width: 780px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .app-sidebar {
    position: static;
    height: auto;
    grid-template-rows: auto auto auto;
    border-right: 0;
    border-bottom: 1px solid var(--rose-line);
  }

  .side-nav {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .app-header {
    grid-template-columns: 1fr;
    padding: 14px 16px;
  }

  .search-input {
    font-size: 13px;
  }

  .search-button {
    padding: 8px 12px;
    font-size: 13px;
  }

  .app-main {
    padding: 1rem;
  }

  .activity-rail {
    padding: 16px;
  }
}

@media (max-width: 480px) {
  .nav-link {
    font-size: 12px;
    padding: 9px 10px;
  }

  .search-button {
    padding: 6px 10px;
  }
}

* {
  box-sizing: border-box;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.global-toast {
  position: fixed;
  top: 20px;
  right: 20px;
  padding: 12px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  z-index: 9999;
  animation: toastIn 0.24s ease;
  border: 1px solid var(--rose-line);
  background: var(--surface);
  color: var(--text-color);
  box-shadow: var(--shadow-hover);
}
.global-toast.info { border-color: #bfd7ff; color: var(--info-color); }
.global-toast.warn { border-color: #ffe0ad; color: var(--warning-color); }
@keyframes toastIn { from { transform: translateX(100px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

/* 状态栏 */
.status-bar {
  background: rgba(255, 251, 253, 0.96);
  color: var(--text-color);
  padding: 7px 20px;
  display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
  font-size: 12px; font-family: 'SF Mono', Monaco, monospace;
  border-bottom: 1px solid var(--rose-line);
  box-shadow: 0 2px 10px rgba(186, 47, 93, 0.05);
}
.status-item {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  background: white;
  border: 1px solid var(--rose-line);
  box-shadow: 0 2px 8px rgba(186, 47, 93, 0.06);
}
.status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.status-code {
  appearance: none;
  border: 0;
  background: transparent;
  color: inherit;
  padding: 0;
  font: inherit;
  font-weight: 800;
  cursor: pointer;
}
.status-code:hover {
  text-decoration: underline;
}
.status-javbus {
  color: inherit;
  text-decoration: none;
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 11px;
  font-weight: 800;
  background: rgba(255,255,255,0.76);
}
.status-javbus:hover {
  background: white;
}
.status-item.downloading .status-dot { background: var(--info-color); animation: pulse 1s infinite; }
.status-item.failed .status-dot { background: var(--danger-color); }
.status-item.queued .status-dot { background: var(--warning-color); }
.status-item.failed {
  color: var(--danger-color);
  border-color: #ffd0cc;
  background: #fff5f4;
}
.status-item.downloading {
  color: var(--info-color);
  border-color: #cfe7ff;
  background: #f3f9ff;
}
.status-item.queued {
  color: var(--warning-color);
  border-color: #ffe0ad;
  background: #fff9ed;
}
.status-dismiss {
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  border: 1px solid currentColor;
  background: rgba(255,255,255,0.76);
  color: inherit;
  font: inherit;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
}
.status-dismiss:hover {
  background: white;
}
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
</style>
