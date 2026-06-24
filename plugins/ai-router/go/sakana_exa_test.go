package main

// sakana_exa_test.go — wire-format + selection tests for the Sakana Fugu and
// Exa providers, mirroring http_test.go (httptest capture + key-var test seam).

import (
	"context"
	"strings"
	"testing"
)

func TestPickSakanaExaKeys(t *testing.T) {
	// no-prefix pickers: credential/password/notesPlain first, else any value.
	if got := pickSakanaKey([]opField{{ID: "username", Value: "user"}, {ID: "credential", Value: "sak-123"}}); got != "sak-123" {
		t.Errorf("pickSakanaKey = %q", got)
	}
	if got := pickExaKey([]opField{{ID: "password", Value: "exa-abc"}}); got != "exa-abc" {
		t.Errorf("pickExaKey by password = %q", got)
	}
	if got := pickExaKey([]opField{{ID: "weird", Value: "fallback-val"}}); got != "fallback-val" {
		t.Errorf("pickExaKey fallback = %q", got)
	}
	if got := pickSakanaKey(nil); got != "" {
		t.Errorf("pickSakanaKey(nil) = %q want empty", got)
	}
}

func TestResolveSakanaModel(t *testing.T) {
	if m, _ := resolveSakanaModel(""); m != "fugu" {
		t.Errorf("default = %q want fugu", m)
	}
	if m, _ := resolveSakanaModel("fugu-ultra"); m != "fugu-ultra" {
		t.Errorf("fugu-ultra = %q", m)
	}
	if m, _ := resolveSakanaModel("sakana/fugu-ultra-20260615"); m != "fugu-ultra-20260615" {
		t.Errorf("strip prefix = %q", m)
	}
	if _, err := resolveSakanaModel("glm-5.1"); err == nil {
		t.Error("non-Sakana id should be rejected")
	}
	if _, err := resolveSakanaModel("kimi-k2.7"); err == nil {
		t.Error("kimi id should be rejected by sakana resolver")
	}
}

func TestSakanaChatWireFormat(t *testing.T) {
	srv, got := captureServer(t, `{"choices":[{"message":{"content":"fugu-says-hi"}}]}`)
	sakanaBaseURL = srv.URL
	sakanaKey = "sak-test"
	t.Cleanup(func() { sakanaBaseURL = "https://api.sakana.ai/v1"; sakanaKey = "" })

	out, err := sakanaChat(context.Background(), msgs("be terse", "hi"), 321, 0.4, "fugu-ultra", "xhigh", false)
	if err != nil {
		t.Fatalf("sakanaChat error: %v", err)
	}
	if out != "fugu-says-hi" {
		t.Errorf("content = %q", out)
	}
	if (*got)["model"] != "fugu-ultra" {
		t.Errorf("model = %v", (*got)["model"])
	}
	if (*got)["reasoning_effort"] != "xhigh" {
		t.Errorf("reasoning_effort = %v", (*got)["reasoning_effort"])
	}
	if (*got)["max_tokens"] != float64(321) {
		t.Errorf("max_tokens = %v", (*got)["max_tokens"])
	}
}

func TestSakanaChatOmitsEffortWhenBlank(t *testing.T) {
	srv, got := captureServer(t, `{"choices":[{"message":{"content":"ok"}}]}`)
	sakanaBaseURL = srv.URL
	sakanaKey = "sak-test"
	t.Cleanup(func() { sakanaBaseURL = "https://api.sakana.ai/v1"; sakanaKey = "" })

	if _, err := sakanaChat(context.Background(), msgs("", "hi"), 0, 0.7, "", "", false); err != nil {
		t.Fatalf("sakanaChat error: %v", err)
	}
	if _, present := (*got)["reasoning_effort"]; present {
		t.Errorf("reasoning_effort should be omitted when blank, got %v", (*got)["reasoning_effort"])
	}
	if (*got)["model"] != "fugu" {
		t.Errorf("default model = %v want fugu", (*got)["model"])
	}
}

func TestSakanaChatClampsMinTokens(t *testing.T) {
	srv, got := captureServer(t, `{"choices":[{"message":{"content":"ok"}}]}`)
	sakanaBaseURL = srv.URL
	sakanaKey = "sak-test"
	t.Cleanup(func() { sakanaBaseURL = "https://api.sakana.ai/v1"; sakanaKey = "" })

	// Fugu rejects max_tokens < 16 — the chat fn must clamp a small caller value.
	if _, err := sakanaChat(context.Background(), msgs("", "hi"), 5, 0.7, "", "", false); err != nil {
		t.Fatalf("sakanaChat error: %v", err)
	}
	if (*got)["max_tokens"] != float64(16) {
		t.Errorf("max_tokens not clamped to 16: %v", (*got)["max_tokens"])
	}
}

func TestProbeModelsEndpoint(t *testing.T) {
	srv, _ := captureServer(t, `{"object":"list","data":[{"id":"fugu"}]}`)
	if got := probeModelsEndpoint(context.Background(), srv.URL, map[string]string{}, "SAKANA_API_KEY"); got != "OK ✓" {
		t.Errorf("probeModelsEndpoint = %q want OK", got)
	}
}

func TestExaSearchWireAndFormat(t *testing.T) {
	reply := `{"requestId":"r1","searchType":"auto","costDollars":{"total":0.0071},
		"results":[{"title":"Quantum news","url":"https://a.test","publishedDate":"2026-06-01","highlights":["breakthrough one","detail two"]}],
		"output":{"content":{"summary":"all good"},"grounding":[{"field":"summary","citations":[{"url":"https://a.test"}],"confidence":"high"}]}}`
	srv, got := captureServer(t, reply)
	exaBaseURL = srv.URL
	exaKey = "exa-test"
	t.Cleanup(func() { exaBaseURL = "https://api.exa.ai"; exaKey = "" })

	out := exaSearch(context.Background(), ExaSearchInput{Query: "quantum computing", OutputSchema: `{"type":"object"}`})

	// request shape
	if (*got)["query"] != "quantum computing" {
		t.Errorf("query = %v", (*got)["query"])
	}
	if (*got)["type"] != "auto" {
		t.Errorf("type = %v want auto", (*got)["type"])
	}
	if (*got)["numResults"] != float64(10) {
		t.Errorf("numResults default = %v want 10", (*got)["numResults"])
	}
	contents, _ := (*got)["contents"].(map[string]any)
	if contents["highlights"] != true {
		t.Errorf("contents.highlights = %v want true", contents["highlights"])
	}
	if sch, ok := (*got)["outputSchema"].(map[string]any); !ok || sch["type"] != "object" {
		t.Errorf("outputSchema not forwarded: %v", (*got)["outputSchema"])
	}
	// response formatting
	for _, want := range []string{"Quantum news", "https://a.test", "breakthrough one", "$0.0071", "Synthesized output"} {
		if !strings.Contains(out, want) {
			t.Errorf("formatted output missing %q:\n%s", want, out)
		}
	}
}

func TestExaContentsTopLevelFields(t *testing.T) {
	srv, got := captureServer(t, `{"results":[{"title":"T","url":"https://u.test","text":"body"}]}`)
	exaBaseURL = srv.URL
	exaKey = "exa-test"
	t.Cleanup(func() { exaBaseURL = "https://api.exa.ai"; exaKey = "" })

	out := exaContents(context.Background(), ExaContentsInput{Urls: []string{"https://u.test"}, Text: true, MaxCharacters: 500})

	urls, _ := (*got)["urls"].([]any)
	if len(urls) != 1 || urls[0] != "https://u.test" {
		t.Errorf("urls = %v", (*got)["urls"])
	}
	// /contents takes text/highlights top-level, NOT nested under "contents".
	if _, nested := (*got)["contents"]; nested {
		t.Error("/contents must not nest content options under a contents object")
	}
	textObj, ok := (*got)["text"].(map[string]any)
	if !ok || textObj["maxCharacters"] != float64(500) {
		t.Errorf("text.maxCharacters = %v", (*got)["text"])
	}
	if !strings.Contains(out, "https://u.test") || !strings.Contains(out, "body") {
		t.Errorf("contents output missing fields:\n%s", out)
	}
}

func TestExaContentsObj(t *testing.T) {
	if c := exaContentsObj(false, 0); c["highlights"] != true {
		t.Errorf("highlights mode = %v", c)
	}
	c := exaContentsObj(true, 0)
	tx, _ := c["text"].(map[string]any)
	if tx["maxCharacters"] != exaDefaultMaxChars {
		t.Errorf("default maxCharacters = %v want %d", tx["maxCharacters"], exaDefaultMaxChars)
	}
}
