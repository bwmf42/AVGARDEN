<template>
    <div class="video-card" @click="$emit('click')">
        <div class="poster-container">
            <img class="poster" :src="video.poster || video.cover" :alt="video.title">
            <div v-if="video.downloaded === true" class="badge downloaded">已下载</div>
            <div v-if="video.downloaded === false" class="badge undownloaded">未下载</div>
            <div v-if="video.hasChinese" class="badge chinese">中文</div>
        </div>
        <div class="info">
            <h3>{{ video.title }}</h3>
            <div v-if="video.actresses && video.actresses.length" class="actresses">
                {{ video.actresses.slice(0, 3).join(' / ') }}
            </div>
        </div>
    </div>
</template>

<script>
export default {
    props: {
        video: {
            type: Object,
            required: true
        }
    }
}
</script>

<style scoped>
.video-card {
    cursor: pointer;
    transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
    background: var(--surface);
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid var(--line);
    box-shadow: var(--shadow-soft);
    width: 100%;
    position: relative;
}

.video-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--primary-color);
    z-index: 2;
}

.video-card:hover {
    transform: translateY(-2px);
    border-color: var(--rose-line);
    box-shadow: var(--shadow-hover);
}

.poster-container {
    position: relative;
    width: 100%;
    padding-top: 137.78%;
    overflow: hidden;
    background: #f6edf2;
}

.poster {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.badge {
    position: absolute;
    padding: 4px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 800;
    z-index: 2;
    border: 1px solid rgba(255,255,255,0.7);
    backdrop-filter: blur(8px);
}

.badge.downloaded {
    bottom: 8px;
    right: 8px;
    background: rgba(40, 122, 67, 0.9);
    color: white;
}

.badge.undownloaded {
    bottom: 8px;
    right: 8px;
    background: rgba(186, 47, 93, 0.9);
    color: white;
}

.badge.chinese {
    top: 8px;
    right: 8px;
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
    font-weight: 700;
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
    line-height: 1.4;
}
</style>
