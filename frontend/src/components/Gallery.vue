<template>
  <div class="gallery" v-if="images.length > 0">
    <h2 class="gallery-title">剧照集锦</h2>
    <div class="gallery-grid">
      <div 
        v-for="(image, index) in images" 
        :key="index" 
        class="gallery-item" 
        @click="openLightbox(index)"
      >
        <img 
          :src="image" 
          :alt="'剧照 ' + (index + 1)"
          loading="lazy"
        >
      </div>
    </div>

    <transition name="fade">
      <div 
        class="lightbox" 
        v-if="showLightbox" 
        @click.self="closeLightbox"
      >
        <div class="lightbox-content">
          <button class="close-btn" @click="closeLightbox">
            <svg width="24" height="24" viewBox="0 0 24 24">
              <path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
            </svg>
          </button>
          
          <img 
            :src="images[currentIndex]" 
            class="lightbox-image"
            @click.stop
          >
          
          <button class="nav-btn prev" @click.stop="prevImage">
            <svg width="24" height="24" viewBox="0 0 24 24">
              <path fill="currentColor" d="M15.41 16.09l-4.58-4.59 4.58-4.59L14 5.5l-6 6 6 6z"/>
            </svg>
          </button>
          <button class="nav-btn next" @click.stop="nextImage">
            <svg width="24" height="24" viewBox="0 0 24 24">
              <path fill="currentColor" d="M8.59 16.34l4.58-4.59-4.58-4.59L10 5.75l6 6-6 6z"/>
            </svg>
          </button>
          
          <div class="image-counter">
            {{ currentIndex + 1 }} / {{ images.length }}
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script>
export default {
  props: {
    images: {
      type: Array,
      default: () => []
    }
  },
  data() {
    return {
      showLightbox: false,
      currentIndex: 0
    }
  },
  beforeUnmount() {
    this.unlockPageScroll()
    document.removeEventListener('keydown', this.handleKeydown)
  },
  methods: {
    openLightbox(index) {
      this.currentIndex = index
      this.showLightbox = true
      document.body.style.overflow = 'hidden'
      document.addEventListener('keydown', this.handleKeydown)
    },
    closeLightbox() {
      this.showLightbox = false
      this.unlockPageScroll()
      document.removeEventListener('keydown', this.handleKeydown)
    },
    unlockPageScroll() {
      document.body.style.overflow = ''
      document.documentElement.style.overflow = ''
    },
    prevImage() {
      this.currentIndex = (this.currentIndex - 1 + this.images.length) % this.images.length
    },
    nextImage() {
      this.currentIndex = (this.currentIndex + 1) % this.images.length
    },
    handleKeydown(e) {
      if (e.key === 'Escape') this.closeLightbox()
      if (e.key === 'ArrowLeft') this.prevImage()
      if (e.key === 'ArrowRight') this.nextImage()
    }
  }
}
</script>

<style scoped>
.gallery {
  margin-top: 1.5rem;
}

.gallery-title {
  color: var(--text-color);
  font-size: 18px;
  font-weight: 800;
  margin: 0 0 1rem;
  padding-left: 0;
}

.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  margin-top: 0;
}

.gallery-item {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
  border: 1px solid var(--line);
  box-shadow: var(--shadow-soft);
  aspect-ratio: 16/9;
  cursor: pointer;
}

.gallery-item:hover {
  transform: translateY(-2px);
  border-color: var(--rose-line);
  box-shadow: var(--shadow-hover);
}

.gallery-item::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(53, 36, 44, 0.18);
  opacity: 0;
  transition: opacity 0.18s ease;
}

.gallery-item:hover::after {
  opacity: 1;
}

.gallery-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.22s ease;
}

.gallery-item:hover img {
  transform: scale(1.03);
}

.lightbox {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(53, 36, 44, 0.88);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(10px);
}

.lightbox-content {
  position: relative;
  width: 90%;
  max-width: 1200px;
  max-height: 90vh;
}

.lightbox-image {
  max-height: 80vh;
  max-width: 100%;
  display: block;
  margin: 0 auto;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  box-shadow: 0 18px 42px rgba(53, 36, 44, 0.34);
  pointer-events: auto;
}

.close-btn {
  position: absolute;
  top: -40px;
  right: 0;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.22);
  color: white;
  font-size: 1.5rem;
  cursor: pointer;
  padding: 5px;
  opacity: 0.8;
  transition: opacity 0.2s;
}

.close-btn:hover {
  opacity: 1;
}

.nav-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  background: rgba(255, 255, 255, 0.2);
  border: none;
  color: white;
  width: 50px;
  height: 50px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.nav-btn:hover {
  background: rgba(255, 255, 255, 0.32);
  border-color: rgba(255, 255, 255, 0.45);
}

.prev {
  left: 20px;
}

.next {
  right: 20px;
}

.image-counter {
  position: absolute;
  bottom: -40px;
  left: 50%;
  transform: translateX(-50%);
  color: white;
  font-size: 1rem;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
  padding: 5px 15px;
  border-radius: 8px;
}

/* 只保留淡入淡出效果 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .gallery-grid {
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 10px;
  }
  
  .nav-btn {
    width: 40px;
    height: 40px;
  }
  
  .close-btn {
    top: 20px;
    right: 20px;
  }
}
</style>
