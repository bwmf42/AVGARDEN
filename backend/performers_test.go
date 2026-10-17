package main

import (
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
)

func TestPerformerDescriptionsKeepRawTextAndFormalNames(t *testing.T) {
	item := map[string]interface{}{"actresses": []interface{}{"京香 大学生モデル", "真央 19さい", "鈴村あいり"}}
	normalizePerformerFields(item)
	if !reflect.DeepEqual(item["actresses"], []interface{}{"鈴村あいり"}) || !reflect.DeepEqual(item["performerNotes"], []interface{}{"京香 大学生モデル", "真央 19さい"}) {
		t.Fatalf("incorrect separation: %#v", item)
	}
	normalizePerformerFields(item)
	if len(item["performerNotes"].([]interface{})) != 2 {
		t.Fatal("normalization duplicated descriptions")
	}
}

func TestProfileCannotBeAddedToActorPreferences(t *testing.T) {
	for _, endpoint := range []struct {
		path    string
		handler http.HandlerFunc
	}{{"/api/block-actress/真央 19さい", blockActressHandler}, {"/api/fav-actress/京香 大学生モデル", favActressHandler}} {
		request := httptest.NewRequest(http.MethodPost, "/", nil)
		request.URL.Path = endpoint.path
		response := httptest.NewRecorder()
		endpoint.handler(response, request)
		if response.Code != http.StatusBadRequest {
			t.Fatalf("expected rejection, got %d", response.Code)
		}
	}
}
