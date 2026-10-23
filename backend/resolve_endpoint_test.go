package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type resolveRoundTripper func(*http.Request) (*http.Response, error)

func (transport resolveRoundTripper) RoundTrip(r *http.Request) (*http.Response, error) {
	return transport(r)
}

func TestResolveProxyGET(t *testing.T) {
	for _, status := range []int{http.StatusOK, http.StatusBadRequest, http.StatusBadGateway} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			body := `{"code":"START-653","kind":"magnet","source":"plwt_chinese","magnet":"magnet:?xt=urn:btih:TEST","title":"","size_gib":0,"published_at":"","forum_url":""}`
			if status != http.StatusOK {
				body = `{"error":"resolve failed"}`
			}
			var seenMethod, seenURI, seenID string
			previousClient := onlineQueueHTTPClient
			onlineQueueHTTPClient = &http.Client{Timeout: previousClient.Timeout, Transport: resolveRoundTripper(func(r *http.Request) (*http.Response, error) {
				seenMethod, seenURI, seenID = r.Method, r.URL.RequestURI(), r.Header.Get("X-Request-ID")
				return &http.Response{
					StatusCode: status,
					Header:     http.Header{"Content-Type": {"application/json"}, "X-Request-Id": {seenID}},
					Body:       io.NopCloser(strings.NewReader(body)),
				}, nil
			})}
			defer func() { onlineQueueHTTPClient = previousClient }()
			previous := queueAPI
			queueAPI = "http://queue.test/"
			defer func() { queueAPI = previous }()

			const path = "/api/resolve/START%2D653?test=1"
			req := httptest.NewRequest(http.MethodGet, path, nil)
			req.Header.Set("X-Request-ID", "resolve-unit-1")
			rec := &deadlineRecorder{ResponseRecorder: httptest.NewRecorder()}
			started := time.Now()
			resolveHandler(rec, req)
			if seenMethod != http.MethodGet || seenURI != path || seenID != "resolve-unit-1" {
				t.Fatalf("upstream request = %s %s, request ID = %q", seenMethod, seenURI, seenID)
			}
			if rec.Code != status || rec.Body.String() != body {
				t.Fatalf("response = %d %s, want %d %s", rec.Code, rec.Body.String(), status, body)
			}
			if rec.Header().Get("X-Request-ID") != "resolve-unit-1" || rec.Header().Get("Content-Type") != "application/json" {
				t.Fatalf("response headers = %v", rec.Header())
			}
			if rec.deadline.Before(started.Add(2*time.Minute-time.Second)) || rec.deadline.After(time.Now().Add(2*time.Minute+time.Second)) {
				t.Fatalf("unexpected resolve write deadline: %v", rec.deadline)
			}
		})
	}
}

func TestResolveProxyRejectsNonGET(t *testing.T) {
	previousClient := onlineQueueHTTPClient
	calls := 0
	onlineQueueHTTPClient = &http.Client{Transport: resolveRoundTripper(func(r *http.Request) (*http.Response, error) {
		calls++
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader("{}"))}, nil
	})}
	defer func() { onlineQueueHTTPClient = previousClient }()
	for _, method := range []string{http.MethodPost, http.MethodDelete, http.MethodPut, http.MethodPatch, http.MethodHead, http.MethodOptions} {
		t.Run(method, func(t *testing.T) {
			rec := &deadlineRecorder{ResponseRecorder: httptest.NewRecorder()}
			resolveHandler(rec, httptest.NewRequest(method, "/api/resolve/START-653", nil))
			if rec.Code != http.StatusMethodNotAllowed {
				t.Fatalf("status = %d, want 405", rec.Code)
			}
			if !rec.deadline.IsZero() {
				t.Fatal("non-GET request entered the resolve proxy")
			}
		})
	}
	if calls != 0 {
		t.Fatalf("non-GET requests reached upstream %d times", calls)
	}
}

func TestResolveUsesOnlineSearchTimeouts(t *testing.T) {
	if onlineQueueHTTPClient.Timeout != 90*time.Second {
		t.Fatalf("upstream timeout = %v, want 90s", onlineQueueHTTPClient.Timeout)
	}
	if onlineSearchWriteTimeout != 2*time.Minute {
		t.Fatalf("write timeout = %v, want 2m", onlineSearchWriteTimeout)
	}
}
