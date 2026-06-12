<template>
    <div class="container">
        <h1 class="page-title">下载管理</h1>
        
        <div v-if="loading" class="loading">加载中...</div>
        
        <div v-else-if="items.length === 0" class="empty">
            <p>队列为空</p>
            <p class="hint">在每日推荐详情页点击「加入下载队列」即可添加</p>
        </div>

        <div v-else class="queue-sections">
            <!-- 进行中：等待 + 下载中 -->
            <div v-if="activeItems.length" class="section">
                <h2 class="section-title">进行中 ({{ activeItems.length }})</h2>
                <div class="queue-list">
                    <div v-for="item in activeItems" :key="item.code" class="queue-item" :class="item.status">
                        <div class="item-main">
                            <div class="item-top">
                                <span class="status-badge" :class="item.status">{{ statusText(item) }}</span>
                                <span class="code">{{ item.code }}</span>
                            </div>
                            <div v-if="item.status === 'downloading'" class="progress-section">
                                <div class="progress-bar">
                                    <div class="progress-fill" :style="{ width: progressWidth(item) + '%' }"></div>
                                </div>
                                <div class="progress-info">
                                    <span v-if="item.speed > 0">{{ formatSpeed(item.speed) }}</span>
                                    <span v-if="item.size > 0" class="eta-text">{{ formatETA(item) }}</span>
                                    <span class="size-text">{{ formatSize(item.size) }}</span>
                                    <span v-if="item.progress_pct > 0" class="pct-text">{{ item.progress_pct }}%</span>
                                </div>
                            </div>
                        </div>
                        <div class="item-actions">
                            <button class="btn-delete" @click="removeItem(item.code)">移出记录</button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 已完成：折叠 -->
            <div v-if="doneItems.length" class="section">
                <h2 class="section-title clickable" @click="showDone = !showDone">
                    已完成 ({{ doneItems.length }}) · {{ showDone ? '收起' : '展开' }}
                </h2>
                <div v-if="showDone" class="queue-list">
                    <div v-for="item in doneItems" :key="item.code" class="queue-item done">
                        <div class="item-main">
                            <div class="item-top">
                                <span class="status-badge done">完成</span>
                                <span class="code">{{ item.code }}</span>
                            </div>
                            <div class="done-info">{{ formatSize(item.size) }}</div>
                        </div>
                        <div class="item-actions">
                            <a class="btn-view" :href="'/' + item.code" target="_blank">查看</a>
                            <button class="btn-delete" @click="removeItem(item.code)">移出记录</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script>
export default {
    name: 'DownloadView',
    data() {
        return {
            items: [],
            loading: true,
            pollTimer: null,
            showDone: false
        }
    },
    computed: {
        activeItems() {
            return this.items.filter(i => i.status !== 'done')
        },
        doneItems() {
            return this.items.filter(i => i.status === 'done')
        }
    },
    async created() {
        await this.fetchStatus()
        this.pollTimer = setInterval(() => this.fetchStatus(), 3000)
    },
    beforeUnmount() {
        if (this.pollTimer) clearInterval(this.pollTimer)
    },
    methods: {
        async fetchStatus() {
            try {
                const resp = await fetch('/api/queue/')
                if (resp.ok) {
                    this.items = await resp.json()
                }
            } catch (e) {
                console.error('Queue fetch error:', e)
            }
            this.loading = false
        },
        statusText(item) {
            const map = { 'queued': '等待中', 'downloading': 'qB 下载中', 'failed': '失败' }
            return map[item.status] || item.status
        },
        progressWidth(item) {
            if (item.progress_pct === 100) return 100
            if (item.progress_pct > 0) return item.progress_pct
            if (item.size > 0) {
                const est = Math.min(85, Math.max(5, item.size / (2 * 1024**3) * 100))
                return Math.round(est)
            }
            return 5
        },
        formatSize(bytes) {
            if (!bytes || bytes === 0) return ''
            const units = ['B', 'KB', 'MB', 'GB', 'TB']
            let i = 0
            let size = bytes
            while (size >= 1024 && i < units.length - 1) { size /= 1024; i++ }
            return size.toFixed(i > 0 ? 1 : 0) + ' ' + units[i]
        },
        formatSpeed(bps) {
            if (!bps || bps === 0) return ''
            if (bps < 1024) return (bps).toFixed(0) + ' B/s'
            if (bps < 1024*1024) return (bps/1024).toFixed(0) + ' KB/s'
            return (bps/1024/1024).toFixed(1) + ' MB/s'
        },
        formatETA(item) {
            if (!item.speed || item.speed === 0) return ''
            if (!item.size || item.size === 0) return ''
            const remaining = item.size * (100 - Math.min(99, item.progress_pct || 0)) / 100
            const seconds = remaining / item.speed
            if (seconds < 60) return Math.ceil(seconds) + 's'
            if (seconds < 3600) return Math.ceil(seconds / 60) + 'm'
            const h = Math.floor(seconds / 3600)
            const m = Math.ceil((seconds % 3600) / 60)
            return h + 'h' + (m > 0 ? m + 'm' : '')
        },
        async removeItem(code) {
            if (!confirm(`确定将 ${code} 从下载管理中移出吗？\n不会删除已经下载的文件。`)) {
                return
            }
            try {
                await fetch(`/api/queue/${code}`, { method: 'DELETE' })
                this.items = this.items.filter(i => i.code !== code)
            } catch (e) {
                console.error(e)
            }
        }
    }
}
</script>

<style scoped>
.container {
  max-width: 860px;
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

.empty p {
  margin: 0;
}

.empty .hint {
  font-size: 13px;
  color: #a88c98;
  margin-top: 8px;
}

.section {
  margin-bottom: 26px;
}

.section-title {
  font-size: 16px;
  color: var(--text-color);
  font-weight: 800;
  margin: 0 0 12px;
}

.section-title.clickable {
  cursor: pointer;
  user-select: none;
  color: var(--muted-color);
}

.section-title.clickable:hover {
  color: var(--secondary-color);
}

.queue-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.queue-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 14px 14px 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 3px solid var(--primary-color);
  border-radius: 8px;
  box-shadow: var(--shadow-soft);
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.queue-item.downloading {
  border-left-color: var(--info-color);
  background: #f7fbff;
}

.queue-item.queued {
  border-left-color: var(--warning-color);
  background: #fffbf2;
}

.queue-item.done {
  border-left-color: var(--success-color);
  background: #f8fff9;
}

.queue-item.failed {
  border-left-color: var(--danger-color);
  background: #fff5f4;
}

.queue-item:hover {
  transform: translateY(-1px);
  border-color: var(--rose-line);
  box-shadow: var(--shadow-hover);
}

.item-main {
  flex: 1;
  min-width: 0;
}

.item-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  min-width: 0;
}

.status-badge {
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
  border: 1px solid var(--line);
  background: var(--surface-2);
}

.status-badge.queued {
  border-color: #ffe0ad;
  color: var(--warning-color);
  background: #fff9ed;
}

.status-badge.downloading {
  border-color: #cfe7ff;
  color: var(--info-color);
  background: #f3f9ff;
}

.status-badge.done {
  border-color: #bfe8ca;
  color: var(--success-color);
  background: #f4fbf5;
}

.status-badge.failed {
  border-color: #ffd0cc;
  color: var(--danger-color);
  background: #fff5f4;
}

.code {
  font-size: 15px;
  font-weight: 800;
  color: var(--text-color);
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-actions {
  display: flex;
  gap: 8px;
  align-self: flex-start;
  flex-shrink: 0;
}

.btn-delete,
.btn-view {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 30px;
  padding: 6px 11px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  text-decoration: none;
  transition: all 0.18s ease;
}

.btn-delete {
  border: 1px solid #ffd0cc;
  background: #fff5f4;
  color: var(--danger-color);
}

.btn-delete:hover {
  background: var(--danger-color);
  border-color: var(--danger-color);
  color: white;
}

.btn-view {
  border: 1px solid #bfe8ca;
  background: #f4fbf5;
  color: var(--success-color);
}

.btn-view:hover {
  background: var(--success-color);
  border-color: var(--success-color);
  color: white;
}

.progress-section {
  margin-top: 4px;
}

.progress-bar {
  height: 7px;
  background: #eef2f7;
  border-radius: 999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--info-color), var(--primary-color));
  border-radius: 999px;
  transition: width 1s ease;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 5px;
  font-size: 12px;
  color: var(--muted-color);
  font-variant-numeric: tabular-nums;
}

.size-text,
.pct-text {
  font-family: 'SF Mono', Monaco, Menlo, monospace;
}

.done-info {
  font-size: 13px;
  color: var(--success-color);
  font-weight: 700;
  margin-top: 2px;
}

@media (max-width: 640px) {
  .queue-item {
    flex-direction: column;
  }

  .item-actions {
    width: 100%;
  }

  .btn-delete,
  .btn-view {
    flex: 1;
  }
}
</style>
