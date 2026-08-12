package main

import (
	"net/http"
	"testing"
)

type failIfCalledRoundTripper struct {
	called bool
}

func (transport *failIfCalledRoundTripper) RoundTrip(*http.Request) (*http.Response, error) {
	transport.called = true
	return nil, nil
}

func TestGetQBCookieRequiresConfiguredPassword(t *testing.T) {
	originalPassword := qbPass
	originalClient := qbHTTPClient
	defer func() {
		qbPass = originalPassword
		qbHTTPClient = originalClient
	}()

	transport := &failIfCalledRoundTripper{}
	qbPass = ""
	qbHTTPClient = &http.Client{Transport: transport}
	if cookie := getQBCookie(); cookie != "" {
		t.Fatalf("expected empty cookie, got %q", cookie)
	}
	if transport.called {
		t.Fatal("qB login request was sent without a configured password")
	}
}
