package main

import (
	"encoding/json"
	"io/ioutil"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

// The Go queue proxy must forward the client's idempotency key verbatim and
// stay compatible with clients that do not send one.
func TestQueuePostForwardsRequestID(t *testing.T) {
	forwarded := map[string]string{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := ioutil.ReadAll(r.Body)
		forwarded = map[string]string{}
		_ = json.Unmarshal(body, &forwarded)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"added"}`))
	}))
	defer upstream.Close()

	previousAPI, previousQueue := queueAPI, queuePath
	queueAPI = upstream.URL
	queuePath = filepath.Join(t.TempDir(), "download_queue.txt")
	defer func() {
		queueAPI = previousAPI
		queuePath = previousQueue
	}()

	post := func(payload string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/api/queue/", strings.NewReader(payload))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		queueHandler(rec, req)
		return rec
	}

	rec := post(`{"code":"ABC-123","target":"115","request_id":"rid-1"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	if forwarded["request_id"] != "rid-1" {
		t.Fatalf("request_id not forwarded: %v", forwarded)
	}
	if forwarded["code"] != "ABC-123" || forwarded["target"] != "115" {
		t.Fatalf("normalized payload wrong: %v", forwarded)
	}

	if rec := post(`{"code":"ABC-124","target":"qb"}`); rec.Code != http.StatusOK {
		t.Fatalf("legacy client rejected: %d %s", rec.Code, rec.Body.String())
	}
	if _, ok := forwarded["request_id"]; ok {
		t.Fatalf("legacy client must not gain a request_id: %v", forwarded)
	}

	post(`{"code":"ABC-125","target":"qb","request_id":"bad id"}`)
	if _, ok := forwarded["request_id"]; ok {
		t.Fatalf("unsafe request_id must be dropped: %v", forwarded)
	}
}
