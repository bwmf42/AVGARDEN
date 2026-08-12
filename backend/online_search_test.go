package main

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

type deadlineRecorder struct {
	*httptest.ResponseRecorder
	deadline time.Time
}

func (recorder *deadlineRecorder) SetWriteDeadline(deadline time.Time) error {
	recorder.deadline = deadline
	return errors.New("stop after deadline capture")
}

func TestOnlineSearchExtendsWriteDeadline(t *testing.T) {
	queueServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"SIRO-5711"}`))
	}))
	defer queueServer.Close()
	previousQueueAPI := queueAPI
	queueAPI = queueServer.URL
	defer func() { queueAPI = previousQueueAPI }()

	recorder := &deadlineRecorder{ResponseRecorder: httptest.NewRecorder()}
	request := httptest.NewRequest(http.MethodGet, "/api/online-search/SIRO-5711", nil)
	started := time.Now()

	onlineSearchHandler(recorder, request)

	minimum := started.Add(onlineSearchWriteTimeout - time.Second)
	maximum := time.Now().Add(onlineSearchWriteTimeout + time.Second)
	if recorder.deadline.Before(minimum) || recorder.deadline.After(maximum) {
		t.Fatalf("unexpected online-search deadline: %v", recorder.deadline)
	}
}
