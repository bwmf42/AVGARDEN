package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func createSparseVideo(t *testing.T, path string, size int64) {
	t.Helper()
	if enforceMainVideoAllocation {
		enforceMainVideoAllocation = false
		t.Cleanup(func() { enforceMainVideoAllocation = true })
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := file.Truncate(size); err != nil {
		file.Close()
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestMainVideoAllocationThreshold(t *testing.T) {
	if hasSufficientAllocatedBytes(100, 94) {
		t.Fatal("94 percent allocation must be rejected")
	}
	if !hasSufficientAllocatedBytes(100, 95) {
		t.Fatal("95 percent allocation must be accepted")
	}
}

func withTestMediaRoot(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	oldBasePath := basePath
	basePath = root
	t.Cleanup(func() { basePath = oldBasePath })
	return root
}

func TestFindMainVideoIgnoresSmallBundledClip(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "HOI-396")
	createSparseVideo(t, filepath.Join(dir, "广告.mp4"), 66*1024*1024)
	if got := findMainVideoInDir(root, "HOI-396"); got != "" {
		t.Fatalf("main video = %q", got)
	}
}

func TestFindMainVideoSupportsNestedLayout(t *testing.T) {
	root := t.TempDir()
	want := filepath.Join(root, "WAAA-611", "WAAA-611_FHD_CH", "WAAA-611_FHD_CH.mp4")
	createSparseVideo(t, want, 600*1024*1024)
	if got := findMainVideoInDir(root, "WAAA-611"); got != want {
		t.Fatalf("main video = %q, want %q", got, want)
	}
}

func TestFindMainVideoChoosesHigherBitrateSizedCopy(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "ROE-500")
	createSparseVideo(t, filepath.Join(dir, "ROE-500.mp4"), 2*1024*1024*1024)
	want := filepath.Join(dir, "hhd800.com@ROE-500.mp4")
	createSparseVideo(t, want, 5*1024*1024*1024)
	if got := findMainVideoInDir(root, "ROE-500"); got != want {
		t.Fatalf("main video = %q, want %q", got, want)
	}
}

func TestFindMainVideoStartsMultipartTitleAtPartOne(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "DVMM-413")
	want := filepath.Join(dir, "4k2.me@DVMM-413-1.mp4")
	createSparseVideo(t, want, 5*1024*1024*1024)
	createSparseVideo(t, filepath.Join(dir, "4k2.me@DVMM-413-2.mp4"), 6*1024*1024*1024)
	if got := findMainVideoInDir(root, "DVMM-413"); got != want {
		t.Fatalf("main video = %q, want %q", got, want)
	}
}

func TestBuildVideoListCacheHidesPosterOnlyDirectory(t *testing.T) {
	root := withTestMediaRoot(t)
	for _, code := range []string{"HOI-396", "WAAA-611"} {
		dir := filepath.Join(root, code)
		if err := os.MkdirAll(dir, 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, code+"-poster.jpg"), []byte("poster"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	createSparseVideo(t, filepath.Join(root, "WAAA-611", "nested", "WAAA-611.mp4"), 600*1024*1024)

	if err := buildVideoListCache(); err != nil {
		t.Fatal(err)
	}
	if len(videoListCache) != 1 || videoListCache[0].ID != "WAAA-611" {
		t.Fatalf("video cache = %#v", videoListCache)
	}
}

func TestBuildVideoListCacheSkipsInternalTrees(t *testing.T) {
	root := withTestMediaRoot(t)
	internalVideo := filepath.Join(root, "__weekly__", "nested", "SHOULD-NOT-SCAN.mp4")
	createSparseVideo(t, internalVideo, 600*1024*1024)
	if err := os.WriteFile(
		filepath.Join(root, "__weekly__", "__weekly__-poster.jpg"),
		[]byte("poster"),
		0644,
	); err != nil {
		t.Fatal(err)
	}

	if err := buildVideoListCache(); err != nil {
		t.Fatal(err)
	}
	if len(videoListCache) != 0 {
		t.Fatalf("internal tree leaked into video cache: %#v", videoListCache)
	}
}

func TestVideoDetailUsesNestedRelativePath(t *testing.T) {
	root := withTestMediaRoot(t)
	createSparseVideo(
		t,
		filepath.Join(root, "WAAA-611", "WAAA-611_FHD_CH", "WAAA-611_FHD_CH.mp4"),
		600*1024*1024,
	)
	request := httptest.NewRequest(http.MethodGet, "/api/videos/WAAA-611", nil)
	response := httptest.NewRecorder()
	videoDetailHandler(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	var detail VideoDetail
	if err := json.Unmarshal(response.Body.Bytes(), &detail); err != nil {
		t.Fatal(err)
	}
	want := "/file/WAAA-611/WAAA-611_FHD_CH/WAAA-611_FHD_CH.mp4"
	if detail.VideoFile != want {
		t.Fatalf("videoFile = %q, want %q", detail.VideoFile, want)
	}
}

func TestBuildMediaIndexUsesCleanIDForNestedVideo(t *testing.T) {
	root := withTestMediaRoot(t)
	createSparseVideo(t, filepath.Join(root, "857OMG-032", "nested", "OMG-032.mp4"), 600*1024*1024)
	index := buildMediaIndex()
	if !index["OMG-032"] {
		t.Fatalf("media index = %#v", index)
	}
}
