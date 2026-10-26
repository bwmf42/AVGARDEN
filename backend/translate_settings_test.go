package main

import (
	"bytes"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type settingsTransport func(*http.Request) (*http.Response, error)

func (transport settingsTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	return transport(r)
}

func TestTranslateSettingsForwarding(t *testing.T) {
	previousClient, previousURL := queueHTTPClient, queueAPI
	defer func() { queueHTTPClient, queueAPI = previousClient, previousURL }()
	queueAPI = "http://queue.test/"
	for _, method := range []string{http.MethodGet, http.MethodPost} {
		for _, status := range []int{200, 400, 500} {
			body := ""
			if method == http.MethodPost {
				body = `{"base":"https://relay.test/v1","key":"fake-settings-secret"}`
			}
			called := false
			queueHTTPClient = &http.Client{Transport: settingsTransport(func(r *http.Request) (*http.Response, error) {
				called = true
				got, _ := io.ReadAll(r.Body)
				if r.Method != method || r.URL.String() != "http://queue.test/api/translate-settings" || string(got) != body {
					t.Fatal("incorrect settings request forwarding")
				}
				if r.Header.Get("Content-Type") != "application/json" {
					t.Fatal("missing JSON type")
				}
				return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(`{"key_set":true}`))}, nil
			})}
			req := httptest.NewRequest(method, "/api/translate-settings", strings.NewReader(body))
			req.Header.Set("Content-Type", "application/json; charset=utf-8")
			rec := httptest.NewRecorder()
			translateSettingsHandler(rec, req)
			if !called || rec.Code != status || rec.Body.String() != `{"key_set":true}` {
				t.Fatal("incorrect proxy response")
			}
			if rec.Header().Get("Cache-Control") != "no-store" {
				t.Fatal("settings must not be cached")
			}
		}
	}
}

func TestTranslateSettingsRejectsInvalidRequests(t *testing.T) {
	previous := queueHTTPClient
	defer func() { queueHTTPClient = previous }()
	queueHTTPClient = &http.Client{Transport: settingsTransport(func(*http.Request) (*http.Response, error) {
		t.Fatal("invalid request reached upstream")
		return nil, errors.New("unexpected")
	})}
	for _, method := range []string{"PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"} {
		rec := httptest.NewRecorder()
		translateSettingsHandler(rec, httptest.NewRequest(method, "/api/translate-settings", nil))
		if rec.Code != 405 {
			t.Errorf("%s: status %d", method, rec.Code)
		}
	}
	for _, method := range []string{"GET", "POST"} {
		for _, unknownLength := range []bool{false, true} {
			req := httptest.NewRequest(method, "/api/translate-settings", strings.NewReader(strings.Repeat("x", 4097)))
			req.Header.Set("Content-Type", "application/json")
			if unknownLength {
				req.ContentLength = -1
			}
			rec := httptest.NewRecorder()
			translateSettingsHandler(rec, req)
			if rec.Code != 413 {
				t.Errorf("oversized %s status %d", method, rec.Code)
			}
		}
	}
}

func TestTranslateSettingsContentType(t *testing.T) {
	previous := queueHTTPClient
	defer func() { queueHTTPClient = previous }()
	for _, method := range []string{http.MethodGet, http.MethodPost} {
		for _, contentType := range []string{"", "text/plain", "invalid", "application/json"} {
			t.Run(method+"/"+contentType, func(t *testing.T) {
				called := false
				queueHTTPClient = &http.Client{Transport: settingsTransport(func(r *http.Request) (*http.Response, error) {
					called = true
					if r.Method != method {
						t.Fatal("incorrect forwarded method")
					}
					return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{}`))}, nil
				})}
				req := httptest.NewRequest(method, "/api/translate-settings", strings.NewReader(`{}`))
				if contentType != "" {
					req.Header.Set("Content-Type", contentType)
				}
				rec := httptest.NewRecorder()
				translateSettingsHandler(rec, req)
				wantStatus := 200
				if method == http.MethodPost && contentType != "application/json" {
					wantStatus = 415
				}
				if rec.Code != wantStatus || called != (wantStatus == 200) {
					t.Fatalf("status %d, want %d; upstream called: %t", rec.Code, wantStatus, called)
				}
				if rec.Header().Get("Cache-Control") != "no-store" {
					t.Fatal("settings must not be cached")
				}
			})
		}
	}
}

func TestTranslateSettingsProxyFailureDoesNotLeakKey(t *testing.T) {
	const key = "unique-fake-key-A7z9"
	previousClient := queueHTTPClient
	previousOutput := logger.Writer()
	defer func() { queueHTTPClient = previousClient; logger.SetOutput(previousOutput) }()
	var logs bytes.Buffer
	logger.SetOutput(&logs)
	queueHTTPClient = &http.Client{Transport: settingsTransport(func(*http.Request) (*http.Response, error) {
		return nil, errors.New("Authorization: Bearer " + key)
	})}
	req := httptest.NewRequest("POST", "/api/translate-settings", strings.NewReader(`{"key":"`+key+`"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	translateSettingsHandler(rec, req)
	if rec.Code != 503 {
		t.Fatalf("status %d", rec.Code)
	}
	if strings.Contains(rec.Body.String()+logs.String(), key) || strings.Contains(rec.Body.String()+logs.String(), key[len(key)-4:]) {
		t.Fatal("credential leaked in error response or logs")
	}
}
