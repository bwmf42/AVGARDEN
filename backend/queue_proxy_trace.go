package main

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net/http"
	"net/http/httptrace"
	"os"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Diagnostics for the /api/queue proxy hop only. Nothing here changes routing,
// timeouts or retry behaviour: it just records where a request spent its time
// so a 15s client timeout can be attributed to DNS, connect, write, TTFB, or
// the upstream handler itself.
const queueProxyLogThresholdDefaultMs = 500

var queueRequestIDRe = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,64}$`)

func queueProxyLogThresholdMs() int64 {
	if raw := strings.TrimSpace(os.Getenv("QUEUE_PROXY_LOG_MS")); raw != "" {
		if value, err := strconv.ParseInt(raw, 10, 64); err == nil && value >= 0 {
			return value
		}
	}
	return queueProxyLogThresholdDefaultMs
}

// queueProxyTraceAll logs every proxied request, including fast ones.
func queueProxyTraceAll() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("AVGARDEN_QUEUE_TRACE"))) {
	case "1", "all", "true", "yes", "on":
		return true
	}
	return false
}

func newQueueRequestID() string {
	var buf [8]byte
	if _, err := rand.Read(buf[:]); err != nil {
		return fmt.Sprintf("q-%d", time.Now().UnixNano())
	}
	return "q-" + hex.EncodeToString(buf[:])
}

// queueRequestID reuses a safe inbound X-Request-ID or generates a new one.
func queueRequestID(r *http.Request) string {
	if r != nil {
		if raw := strings.TrimSpace(r.Header.Get("X-Request-ID")); raw != "" && queueRequestIDRe.MatchString(raw) {
			return raw
		}
	}
	return newQueueRequestID()
}

// queueProxyPhases collects client-side phases of one proxied request.
// Zero values mean "phase never reached" and are reported as -1.
type queueProxyPhases struct {
	mu        sync.Mutex
	start     time.Time
	dnsStart  time.Time
	dnsDone   time.Time
	connStart time.Time
	connMs    int64
	conns     int
	gotConn   time.Time
	wroteReq  time.Time
	firstByte time.Time
}

func newQueueProxyPhases() *queueProxyPhases {
	return &queueProxyPhases{start: time.Now()}
}

func (p *queueProxyPhases) mark(dst *time.Time) {
	p.mu.Lock()
	if dst.IsZero() {
		*dst = time.Now()
	}
	p.mu.Unlock()
}

func (p *queueProxyPhases) trace() *httptrace.ClientTrace {
	return &httptrace.ClientTrace{
		DNSStart:     func(httptrace.DNSStartInfo) { p.mark(&p.dnsStart) },
		DNSDone:      func(httptrace.DNSDoneInfo) { p.mark(&p.dnsDone) },
		ConnectStart: func(_, _ string) { p.mark(&p.connStart) },
		ConnectDone: func(_, _ string, _ error) {
			p.mu.Lock()
			if !p.connStart.IsZero() {
				p.connMs += time.Since(p.connStart).Milliseconds()
				p.connStart = time.Time{}
			}
			p.conns++
			p.mu.Unlock()
		},
		GotConn:              func(httptrace.GotConnInfo) { p.mark(&p.gotConn) },
		WroteRequest:         func(httptrace.WroteRequestInfo) { p.mark(&p.wroteReq) },
		GotFirstResponseByte: func() { p.mark(&p.firstByte) },
	}
}

// log prints the phase summary. It is called on both success and failure so a
// timeout still reports every phase that did complete.
func (p *queueProxyPhases) log(requestID, method, path string, status int, err error) {
	p.mu.Lock()
	dnsMs := int64(-1)
	if !p.dnsStart.IsZero() && !p.dnsDone.IsZero() {
		dnsMs = p.dnsDone.Sub(p.dnsStart).Milliseconds()
	}
	connectMs := int64(-1)
	if p.conns > 0 {
		connectMs = p.connMs
	}
	gotConnMs := int64(-1)
	if !p.gotConn.IsZero() {
		gotConnMs = p.gotConn.Sub(p.start).Milliseconds()
	}
	writeMs := int64(-1)
	if !p.wroteReq.IsZero() {
		base := p.gotConn
		if base.IsZero() {
			base = p.start
		}
		writeMs = p.wroteReq.Sub(base).Milliseconds()
	}
	ttfbMs := int64(-1)
	if !p.firstByte.IsZero() {
		ttfbMs = p.firstByte.Sub(p.start).Milliseconds()
	}
	conns := p.conns
	totalMs := time.Since(p.start).Milliseconds()
	p.mu.Unlock()

	shouldLog := err != nil || totalMs >= queueProxyLogThresholdMs() || queueProxyTraceAll()
	if !shouldLog {
		return
	}
	errText := ""
	if err != nil {
		errText = err.Error()
	}
	logger.Printf(
		"[QueueProxy] request=%s method=%s path=%s dns_ms=%d connect_ms=%d conns=%d gotconn_ms=%d write_ms=%d ttfb_ms=%d total_ms=%d status=%d error=%q",
		requestID, method, path, dnsMs, connectMs, conns, gotConnMs, writeMs, ttfbMs, totalMs, status, errText,
	)
}
