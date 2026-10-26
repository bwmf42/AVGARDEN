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

func TestTitleTranslateForwarding(t *testing.T) {
	previousClient, previousURL := queueHTTPClient, queueAPI
	defer func() { queueHTTPClient, queueAPI = previousClient, previousURL }()
	queueAPI = "http://queue.test/"
	for _, method := range []string{"GET", "POST"} {
		for _, status := range []int{200, 202, 400, 409, 500} {
			body := ""
			if method == "POST" {
				body = `{"items":[{"code":"ABC-123","title":"UNIQUE_REQUEST_TITLE"}]}`
			}
			called := false
			response := `{"state":"running","total":1}`
			queueHTTPClient = &http.Client{Transport: settingsTransport(func(r *http.Request) (*http.Response, error) {
				called = true
				got, err := io.ReadAll(r.Body)
				if err != nil || string(got) != body || r.Method != method || r.URL.String() != "http://queue.test/api/title-translate" {
					t.Fatal("incorrect request forwarding")
				}
				if r.Header.Get("Content-Type") != "application/json" {
					t.Fatal("missing upstream JSON type")
				}
				return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(response))}, nil
			})}
			req := httptest.NewRequest(method, "/api/title-translate", strings.NewReader(body))
			if method == "POST" {
				req.Header.Set("Content-Type", "application/json; charset=utf-8")
			}
			rec := httptest.NewRecorder()
			titleTranslateHandler(rec, req)
			if !called || rec.Code != status || rec.Body.String() != response {
				t.Fatalf("incorrect proxy response: %d %s", rec.Code, rec.Body.String())
			}
			if rec.Header().Get("Cache-Control") != "no-store" {
				t.Fatal("job state must not be cached")
			}
		}
	}
}

func TestTitleTranslateRejectsInvalidRequests(t *testing.T) {
	previous := queueHTTPClient
	defer func() { queueHTTPClient = previous }()
	queueHTTPClient = &http.Client{Transport: settingsTransport(func(*http.Request) (*http.Response, error) {
		t.Fatal("invalid request reached upstream")
		return nil, errors.New("unexpected")
	})}
	mux := http.NewServeMux()
	mux.HandleFunc("/api/title-translate", titleTranslateHandler)
	mux.HandleFunc("/api/title-translate/", titleTranslateHandler)
	for _, method := range []string{"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"} {
		for _, path := range []string{"/api/title-translate/", "/api/title-translate/extra", "/api/title-translate?x=1", "/api/title-translate?", "/api/title-translate-other", "/api/title%2Dtranslate"} {
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, httptest.NewRequest(method, path, nil))
			if rec.Code != 404 {
				t.Errorf("%s %s: status %d", method, path, rec.Code)
			}
		}
		if method != "GET" && method != "POST" {
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, httptest.NewRequest(method, "/api/title-translate", nil))
			if rec.Code != 405 {
				t.Errorf("%s: status %d", method, rec.Code)
			}
		}
	}
	for _, contentType := range []string{"", "text/plain", "invalid"} {
		req := httptest.NewRequest("POST", "/api/title-translate", strings.NewReader(`{}`))
		req.Header.Set("Content-Type", contentType)
		rec := httptest.NewRecorder()
		titleTranslateHandler(rec, req)
		if rec.Code != 415 {
			t.Errorf("type %q: status %d", contentType, rec.Code)
		}
	}
	for _, method := range []string{"GET", "POST"} {
		for _, unknownLength := range []bool{false, true} {
			req := httptest.NewRequest(method, "/api/title-translate", strings.NewReader(strings.Repeat("x", 65537)))
			req.Header.Set("Content-Type", "application/json")
			if unknownLength {
				req.ContentLength = -1
			}
			rec := httptest.NewRecorder()
			titleTranslateHandler(rec, req)
			if rec.Code != 413 {
				t.Errorf("oversized %s: status %d", method, rec.Code)
			}
		}
	}
}

func TestTitleTranslateProxyFailureDoesNotLeakBody(t *testing.T) {
	const title = "UNIQUE_REQUEST_TITLE_K5r"
	previousClient, previousOutput := queueHTTPClient, logger.Writer()
	defer func() { queueHTTPClient = previousClient; logger.SetOutput(previousOutput) }()
	var logs bytes.Buffer
	logger.SetOutput(&logs)
	queueHTTPClient = &http.Client{Transport: settingsTransport(func(*http.Request) (*http.Response, error) {
		return nil, errors.New(title)
	})}
	req := httptest.NewRequest("POST", "/api/title-translate", strings.NewReader(`{"items":[{"code":"ABC-123","title":"`+title+`"}]}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	titleTranslateHandler(rec, req)
	if rec.Code != 503 || strings.Contains(rec.Body.String()+logs.String(), title) {
		t.Fatal("proxy failure status or body privacy is incorrect")
	}
}
