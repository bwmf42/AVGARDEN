package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestScrapeStatusHandlerProxiesQueueAPI(t *testing.T) {
	queueServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/scrape-status" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"running":true,"phase":"weekly_scrape"}`))
	}))
	defer queueServer.Close()

	previous := queueAPI
	queueAPI = queueServer.URL
	defer func() { queueAPI = previous }()

	recorder := httptest.NewRecorder()
	scrapeStatusHandler(recorder, httptest.NewRequest(http.MethodGet, "/api/scrape-status", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var body map[string]interface{}
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body["running"] != true || body["phase"] != "weekly_scrape" {
		t.Fatalf("unexpected body: %#v", body)
	}
}

func TestScrapeStatusHandlerFallsBackToSharedFile(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "scrape_pipeline.json")
	if err := os.WriteFile(path, []byte(`{"running":false,"last_summary":"完成"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SCRAPE_PIPELINE_PATH", path)

	previous := queueAPI
	queueAPI = "http://127.0.0.1:1"
	defer func() { queueAPI = previous }()

	recorder := httptest.NewRecorder()
	scrapeStatusHandler(recorder, httptest.NewRequest(http.MethodGet, "/api/scrape-status", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var body map[string]interface{}
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body["last_summary"] != "完成" {
		t.Fatalf("unexpected body: %#v", body)
	}
}
