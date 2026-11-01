package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestLocal115StatusAcrossBrowsingHandlers(t *testing.T) {
	root := withTestMediaRoot(t)
	configureBlockedListTestFiles(t)
	t.Setenv("BLOCKED_ACTRESSES", "")
	t.Setenv("BLOCKED_GENRES", "")
	cases := []struct {
		id         string
		status     string
		local      bool
		downloaded bool
		queue      string
	}{
		{"START-656", "submitted_to_115", true, true, ""},
		{"START-657", "submitted_to_115", false, false, "submitted_to_115"},
		{"START-658", "downloading", true, false, "downloading"},
		{"START-659", "queued", true, false, "queued"},
		{"START-660", "failed", true, false, "failed"},
		{"START-661", "done", true, true, ""},
		{"START-662", "", true, true, ""},
	}
	items := make([]map[string]interface{}, 0, len(cases))
	queue := make([]map[string]string, 0, len(cases))
	for _, tc := range cases {
		item := map[string]interface{}{"id": tc.id, "genres": []string{"fixture"}}
		if tc.status == "submitted_to_115" {
			item["queueStatus"] = tc.status // An upstream field must also be cleared for local media.
		}
		items = append(items, item)
		if tc.status != "" {
			queue = append(queue, map[string]string{"code": tc.id, "status": tc.status})
		}
		if tc.local {
			createSparseVideo(t, filepath.Join(root, tc.id, "nested", tc.id+".mp4"), 600*1024*1024)
		}
	}
	// A preview alone does not qualify as a downloaded main video.
	createSparseVideo(t, filepath.Join(root, "START-657", "preview.mp4"), 1024)
	weeklyData, err := json.Marshal(items)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, "__weekly__"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "__weekly__", "weekly.json"), weeklyData, 0644); err != nil {
		t.Fatal(err)
	}
	queueData, err := json.Marshal(queue)
	if err != nil {
		t.Fatal(err)
	}
	oldClient, oldOnlineClient, oldAPI := queueHTTPClient, onlineQueueHTTPClient, queueAPI
	oldIndex, oldIndexTime := mediaIndex, mediaIndexTime
	oldCache, oldTime, oldMod, oldSig := weeklyCache, weeklyCacheTime, weeklyCacheMod, weeklyCacheQueueSig
	t.Cleanup(func() {
		queueHTTPClient, onlineQueueHTTPClient, queueAPI = oldClient, oldOnlineClient, oldAPI
		mediaIndex, mediaIndexTime = oldIndex, oldIndexTime
		weeklyCache, weeklyCacheTime, weeklyCacheMod, weeklyCacheQueueSig = oldCache, oldTime, oldMod, oldSig
	})
	mediaIndex, mediaIndexTime = nil, time.Time{}
	invalidateWeeklyCache()
	queueAPI = "http://queue.test"
	client := &http.Client{Transport: resolveRoundTripper(func(r *http.Request) (*http.Response, error) {
		body := string(queueData)
		if r.URL.Path != "/api/queue" {
			id := strings.TrimPrefix(r.URL.Path, "/api/online-search/")
			found := false
			for _, item := range items {
				if item["id"] == id {
					data, err := json.Marshal(item)
					if err != nil {
						t.Fatal(err)
					}
					body, found = string(data), true
					break
				}
			}
			if !found {
				t.Fatalf("unexpected upstream request: %s", r.URL)
			}
		}
		return &http.Response{StatusCode: http.StatusOK, Header: http.Header{"Content-Type": {"application/json"}}, Body: io.NopCloser(strings.NewReader(body))}, nil
	})}
	queueHTTPClient, onlineQueueHTTPClient = client, client
	assertItem := func(t *testing.T, item map[string]interface{}, index int) {
		t.Helper()
		tc := cases[index]
		status, hasStatus := item["queueStatus"]
		if item["id"] != tc.id || item["downloaded"] != tc.downloaded ||
			(tc.queue == "" && hasStatus) || (tc.queue != "" && status != tc.queue) {
			t.Fatalf("%s: unexpected item %v; want downloaded=%v queueStatus=%q", tc.id, item, tc.downloaded, tc.queue)
		}
	}
	for _, endpoint := range []struct {
		path    string
		handler http.HandlerFunc
	}{
		{"/api/weekly", weeklyHandler},
		{"/api/weekly/by-genre/fixture", byGenreHandler},
	} {
		t.Run(endpoint.path, func(t *testing.T) {
			res := httptest.NewRecorder()
			endpoint.handler(res, httptest.NewRequest(http.MethodGet, endpoint.path, nil))
			t.Logf("GET %s -> %d %s", endpoint.path, res.Code, res.Body.String())
			var got []map[string]interface{}
			if res.Code != http.StatusOK || json.Unmarshal(res.Body.Bytes(), &got) != nil || len(got) != len(cases) {
				t.Fatalf("unexpected response: %d %s", res.Code, res.Body.String())
			}
			for i, item := range got {
				assertItem(t, item, i)
			}
		})
	}
	for i, tc := range cases {
		t.Run("online/"+tc.id, func(t *testing.T) {
			path := "/api/online-search/" + tc.id
			res := httptest.NewRecorder()
			onlineSearchHandler(res, httptest.NewRequest(http.MethodGet, path, nil))
			t.Logf("GET %s -> %d %s", path, res.Code, res.Body.String())
			var item map[string]interface{}
			if res.Code != http.StatusOK || json.Unmarshal(res.Body.Bytes(), &item) != nil {
				t.Fatalf("unexpected response: %d %s", res.Code, res.Body.String())
			}
			assertItem(t, item, i)
			if tc.downloaded && (item["localID"] != tc.id || item["localUrl"] != "/video/"+tc.id) {
				t.Fatalf("missing local navigation: %v", item)
			}
		})
	}
}
