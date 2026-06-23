package main

// http_test.go — end-to-end wire-format tests via httptest (mirrors the
// mock_or_client capability tests), plus op-field key selection and the
// Kimi model validation / dir reader.

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPickKeys(t *testing.T) {
	orFields := []opField{{ID: "notesPlain", Value: "ignore"}, {ID: "credential", Value: "sk-or-v1-abc"}}
	if got := pickORKey(orFields); got != "sk-or-v1-abc" {
		t.Errorf("pickORKey by prefix = %q", got)
	}
	// no sk-or value → fall back to credential id
	if got := pickORKey([]opField{{ID: "credential", Value: "raw-or-key"}}); got != "raw-or-key" {
		t.Errorf("pickORKey by id = %q", got)
	}
	if got := pickKimiKey([]opField{{ID: "x", Value: "sk-kimi-123"}}); got != "sk-kimi-123" {
		t.Errorf("pickKimiKey by prefix = %q", got)
	}
	if got := pickKimiKey([]opField{{ID: "notesPlain", Value: "note-key"}}); got != "note-key" {
		t.Errorf("pickKimiKey by notesPlain = %q", got)
	}
	if got := pickGLMKey([]opField{{ID: "notesPlain", Value: "glm-xyz"}}); got != "glm-xyz" {
		t.Errorf("pickGLMKey = %q", got)
	}
	if got := pickORKey(nil); got != "" {
		t.Errorf("pickORKey(nil) = %q want empty", got)
	}
}

func TestResolveKimiModel(t *testing.T) {
	if m, _ := resolveKimiModel("", true); m != "kimi-k2.7" {
		t.Errorf("default general = %q", m)
	}
	if m, _ := resolveKimiModel("", false); m != "kimi-for-coding" {
		t.Errorf("default coding = %q", m)
	}
	if m, _ := resolveKimiModel("moonshotai/kimi-k2.6", true); m != "kimi-k2.6" {
		t.Errorf("strip prefix = %q", m)
	}
	if _, err := resolveKimiModel("deepseek/deepseek-v4-pro", true); err == nil {
		t.Error("non-kimi id should be rejected")
	}
	if _, err := resolveKimiModel("openai/gpt-5", true); err == nil {
		t.Error("banned id should be rejected by kimi resolver")
	}
}

// captureServer returns a server that records the last JSON body and replies with content.
func captureServer(t *testing.T, reply string) (*httptest.Server, *map[string]any) {
	t.Helper()
	var got map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&got)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(reply))
	}))
	t.Cleanup(srv.Close)
	return srv, &got
}

func TestOrChatWireFormatAndZDR(t *testing.T) {
	srv, got := captureServer(t, `{"choices":[{"message":{"content":"hello-from-or"}}]}`)
	orBaseURL = srv.URL
	orKey = "sk-or-test"
	t.Cleanup(func() { orBaseURL = "https://openrouter.ai/api/v1"; orKey = "" })

	out, err := orChat(context.Background(), []map[string]string{{"role": "user", "content": "hi"}},
		"deepseek/deepseek-v4-pro", 123, "be terse", false)
	if err != nil {
		t.Fatalf("orChat error: %v", err)
	}
	if out != "hello-from-or" {
		t.Errorf("content = %q", out)
	}
	if (*got)["model"] != "deepseek/deepseek-v4-pro" {
		t.Errorf("model = %v", (*got)["model"])
	}
	prov, _ := (*got)["provider"].(map[string]any)
	if prov["data_collection"] != "deny" {
		t.Errorf("ZDR not enforced: provider=%v", (*got)["provider"])
	}
	// system prepended
	m0 := (*got)["messages"].([]any)[0].(map[string]any)
	if m0["role"] != "system" || m0["content"] != "be terse" {
		t.Errorf("system message not prepended: %v", m0)
	}
}

func TestOrChatRefusesBannedAndBlocked(t *testing.T) {
	orKey = "sk-or-test"
	t.Cleanup(func() { orKey = "" })
	if _, err := orChat(context.Background(), nil, "openai/gpt-5", 10, "", false); err == nil || !strings.Contains(err.Error(), "banned") {
		t.Errorf("banned model not refused: %v", err)
	}
	if _, err := orChat(context.Background(), nil, "anthropic/claude-opus", 10, "", false); err == nil || !strings.Contains(err.Error(), "blocked from OpenRouter") {
		t.Errorf("blocked model not refused: %v", err)
	}
}

func TestKimiChatPinsTemperature(t *testing.T) {
	srv, got := captureServer(t, `{"choices":[{"message":{"content":"ok"}}]}`)
	kimiBaseURL = srv.URL
	kimiKey = "sk-kimi-test"
	t.Cleanup(func() { kimiBaseURL = "https://api.kimi.com/coding/v1"; kimiKey = "" })

	if _, err := kimiChat(context.Background(), msgs("", "hi"), kimiOpts{maxTokens: 10, useGeneral: true}); err != nil {
		t.Fatalf("kimiChat error: %v", err)
	}
	if (*got)["temperature"] != float64(1) {
		t.Errorf("Kimi temperature not pinned to 1: %v", (*got)["temperature"])
	}
	if (*got)["model"] != "kimi-k2.7" {
		t.Errorf("kimi model = %v", (*got)["model"])
	}
}

func TestReadDir(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "main.go"), []byte("package x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "logo.png"), []byte("binary"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(dir, "node_modules"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "node_modules", "dep.js"), []byte("skip me"), 0o644); err != nil {
		t.Fatal(err)
	}
	out := readDir(dir, 900_000)
	if !strings.Contains(out, "main.go") || !strings.Contains(out, "package x") {
		t.Errorf("source file not included:\n%s", out)
	}
	if strings.Contains(out, "logo.png") {
		t.Error("binary file should be skipped")
	}
	if strings.Contains(out, "skip me") {
		t.Error("node_modules should be pruned")
	}
	if got := readDir(filepath.Join(dir, "nope"), 100); !strings.HasPrefix(got, "Error:") {
		t.Errorf("missing dir should error: %q", got)
	}
}

func TestOrCompareFiltersBlocked(t *testing.T) {
	orKey = "sk-or-test"
	srv, _ := captureServer(t, `{"choices":[{"message":{"content":"r"}}]}`)
	orBaseURL = srv.URL
	t.Cleanup(func() { orBaseURL = "https://openrouter.ai/api/v1"; orKey = "" })

	out := orCompare(context.Background(), OrCompareInput{
		Prompt: "x", Models: []string{"openai/gpt-5", "anthropic/claude", "deepseek/deepseek-v4-pro"},
	})
	if !strings.Contains(out, "Removed blocked/banned models") {
		t.Errorf("block note missing:\n%s", out)
	}
	if !strings.Contains(out, "deepseek/deepseek-v4-pro") {
		t.Error("kept model missing from comparison")
	}
	out2 := orCompare(context.Background(), OrCompareInput{Prompt: "x", Models: []string{"openai/gpt-5", "x-ai/grok"}})
	if !strings.Contains(out2, "All requested models are blocked or banned") {
		t.Errorf("all-blocked case wrong:\n%s", out2)
	}
}
