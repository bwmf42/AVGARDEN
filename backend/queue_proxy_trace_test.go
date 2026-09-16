package main

import (
	"bytes"
	"io/ioutil"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

// queueHTTPClient keeps its production 15s budget: this change is diagnostics only.
func TestQueueHTTPClientTimeoutUnchanged(t *testing.T) {
	if queueHTTPClient.Timeout != 15*time.Second {
		t.Fatalf("queueHTTPClient.Timeout = %v, want 15s", queueHTTPClient.Timeout)
	}
}

func TestQueueRequestIDPrefersSafeInboundValue(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/api/queue/", nil)
	req.Header.Set("X-Request-ID", "abc-123_XYZ.7")
	if got := queueRequestID(req); got != "abc-123_XYZ.7" {
		t.Fatalf("queueRequestID = %q, want inbound value", got)
	}

	req.Header.Set("X-Request-ID", "bad id with spaces\nand newline")
	got := queueRequestID(req)
	if !queueRequestIDRe.MatchString(got) || got == "bad id with spaces\nand newline" {
		t.Fatalf("queueRequestID did not sanitize unsafe value: %q", got)
	}
}

func TestQueueProxyForwardsRequestID(t *testing.T) {
	var seenID string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seenID = r.Header.Get("X-Request-ID")
		w.Header().Set("X-Request-ID", seenID)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte("[]"))
	}))
	defer upstream.Close()

	previous := queueAPI
	queueAPI = upstream.URL
	defer func() { queueAPI = previous }()

	req := httptest.NewRequest(http.MethodGet, "/api/queue/", nil)
	req.Header.Set("X-Request-ID", "corr-unit-1")
	rec := httptest.NewRecorder()
	queueHandler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if seenID != "corr-unit-1" {
		t.Fatalf("upstream X-Request-ID = %q, want corr-unit-1", seenID)
	}
	if got := rec.Header().Get("X-Request-ID"); got != "corr-unit-1" {
		t.Fatalf("proxied response X-Request-ID = %q", got)
	}
}

func TestQueueProxyGeneratesRequestID(t *testing.T) {
	var seenID string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seenID = r.Header.Get("X-Request-ID")
		w.Write([]byte("[]"))
	}))
	defer upstream.Close()

	previous := queueAPI
	queueAPI = upstream.URL
	defer func() { queueAPI = previous }()

	rec := httptest.NewRecorder()
	queueHandler(rec, httptest.NewRequest(http.MethodGet, "/api/queue/", nil))

	if !queueRequestIDRe.MatchString(seenID) || !strings.HasPrefix(seenID, "q-") {
		t.Fatalf("generated X-Request-ID = %q", seenID)
	}
}

// On a transport error the proxy must still log the phases that completed.
func TestQueueProxyLogsPhasesOnFailure(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	upstream.Close() // nothing listening -> dial error

	previous := queueAPI
	queueAPI = upstream.URL
	defer func() { queueAPI = previous }()

	var buf bytes.Buffer
	previousOut := logger.Writer()
	logger.SetOutput(&buf)
	defer logger.SetOutput(previousOut)

	req := httptest.NewRequest(http.MethodPost, "/api/queue/ping", nil)
	req.Header.Set("X-Request-ID", "corr-fail-1")
	rec := httptest.NewRecorder()
	queueHandler(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
	logged := buf.String()
	for _, want := range []string{"[QueueProxy]", "request=corr-fail-1", "method=POST", "path=/api/queue/ping", "dns_ms=", "connect_ms=", "ttfb_ms=", "total_ms=", "error="} {
		if !strings.Contains(logged, want) {
			t.Fatalf("log line missing %q:\n%s", want, logged)
		}
	}
}

// End-to-end correlation against a live queue_api; opt-in via env so the normal
// test run stays hermetic.
func TestQueueProxyEndToEndRequestID(t *testing.T) {
	base := strings.TrimSpace(os.Getenv("QUEUE_PROXY_E2E_URL"))
	if base == "" {
		t.Skip("QUEUE_PROXY_E2E_URL not set")
	}
	t.Setenv("AVGARDEN_QUEUE_TRACE", "1") // log every proxied request, not just slow ones

	previous := queueAPI
	queueAPI = strings.TrimRight(base, "/")
	defer func() { queueAPI = previous }()

	var buf bytes.Buffer
	previousOut := logger.Writer()
	logger.SetOutput(&buf)
	defer logger.SetOutput(previousOut)

	proxy := httptest.NewServer(http.HandlerFunc(queueHandler))
	defer proxy.Close()

	req, err := http.NewRequest(http.MethodGet, proxy.URL+"/api/queue/", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("X-Request-ID", "corr-e2e-1")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, _ := ioutil.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d body=%s", resp.StatusCode, body)
	}
	if got := resp.Header.Get("X-Request-ID"); got != "corr-e2e-1" {
		t.Fatalf("response X-Request-ID = %q, want corr-e2e-1", got)
	}
	if !strings.Contains(buf.String(), "request=corr-e2e-1") {
		t.Fatalf("go log missing request id:\n%s", buf.String())
	}

	// A POST that cannot create a download task (unknown queue sub-path -> 404)
	// still exercises the proxy, the queue lock and the response write phase.
	postReq, err := http.NewRequest(http.MethodPost, proxy.URL+"/api/queue/ping", strings.NewReader("{}"))
	if err != nil {
		t.Fatal(err)
	}
	postReq.Header.Set("Content-Type", "application/json")
	postReq.Header.Set("X-Request-ID", "corr-e2e-post-1")
	postResp, err := http.DefaultClient.Do(postReq)
	if err != nil {
		t.Fatal(err)
	}
	defer postResp.Body.Close()
	postBody, _ := ioutil.ReadAll(postResp.Body)
	if postResp.StatusCode != http.StatusNotFound {
		t.Fatalf("POST status = %d body=%s, want 404 (no queue side effect)", postResp.StatusCode, postBody)
	}
	if !strings.Contains(buf.String(), "request=corr-e2e-post-1") {
		t.Fatalf("go log missing POST request id:\n%s", buf.String())
	}
	t.Logf("go proxy log: %s", strings.TrimSpace(buf.String()))
}
