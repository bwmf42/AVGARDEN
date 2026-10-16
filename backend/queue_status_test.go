package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestQueueStatusPreservesTransferChannelAndCloudPhase(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`[{"code":"AAA-001","status":"downloading","target":"qb","transport":"online","progress_pct":77},{"code":"BBB-002","status":"downloading","target":"115","transport":"115","phase":"submitting"},{"code":"CCC-003","status":"submitted_to_115","target":"115"}]`))
	}))
	defer upstream.Close()
	previousAPI, previousQueue, previousBase := queueAPI, queuePath, basePath
	defer func() { queueAPI, queuePath, basePath = previousAPI, previousQueue, previousBase }()
	queueAPI, queuePath, basePath = upstream.URL, filepath.Join(t.TempDir(), "queue.txt"), t.TempDir()
	failed := []FailedQueueRecord{{Code: "DDD-004", FailedAt: time.Now().Format(time.RFC3339), Reason: "115 拒绝：空间不足"}}
	body, _ := json.Marshal(failed)
	if err := os.WriteFile(filepath.Join(filepath.Dir(queuePath), "failed_queue.json"), body, 0o600); err != nil {
		t.Fatal(err)
	}
	recorder := httptest.NewRecorder()
	queueStatusHandler(recorder, httptest.NewRequest(http.MethodGet, "/api/queue-status", nil))
	var response queueStatusResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if len(response.Active) != 2 || response.Active[0].Transport != "online" || response.Active[1].Phase != "submitting" || response.Active[1].Target != "115" {
		t.Fatalf("lost channel or included submitted cloud task: %#v", response.Active)
	}
	if len(response.Failed) != 1 || response.Failed[0].Message != failed[0].Reason {
		t.Fatalf("lost cloud rejection reason: %#v", response.Failed)
	}
}
