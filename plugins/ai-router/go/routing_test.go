package main

// routing_test.go — pure routing/capability logic, mirroring test_routing.py +
// test_capabilities.py. The model-selection decisions are the contract that must
// not drift from the Python server.

import (
	"os"
	"strings"
	"testing"
)

func TestMain(m *testing.M) {
	if err := loadCatalog(); err != nil {
		panic(err)
	}
	m.Run()
}

func TestIsBanned(t *testing.T) {
	banned := []string{"openai/gpt-5", "openai/dall-e-3", "x-ai/grok-4", "x-ai/anything"}
	for _, m := range banned {
		if !isBanned(m) {
			t.Errorf("isBanned(%q)=false want true", m)
		}
	}
	notBanned := []string{"deepseek/deepseek-v4-pro", "minimax/minimax-m2.7", "baidu/ernie-4.5", "xiaomi/mimo-v2.5-pro"}
	for _, m := range notBanned {
		if isBanned(m) {
			t.Errorf("isBanned(%q)=true want false", m)
		}
	}
}

func TestIsBlockedFromOR(t *testing.T) {
	blocked := []string{"anthropic/claude-opus", "anthropic/anything", "moonshotai/kimi-k2", "moonshotai/x", "zai/glm-5"}
	for _, m := range blocked {
		if !isBlockedFromOR(m) {
			t.Errorf("isBlockedFromOR(%q)=false want true", m)
		}
	}
	notBlocked := []string{"deepseek/deepseek-v4-pro", "minimax/minimax-m2.7", "xiaomi/mimo-v2.5-pro"}
	for _, m := range notBlocked {
		if isBlockedFromOR(m) {
			t.Errorf("isBlockedFromOR(%q)=true want false", m)
		}
	}
}

func TestShouldRedirectToHost(t *testing.T) {
	cases := []struct {
		hint     string
		pressure bool
		want     bool
	}{
		{"coding", false, true}, {"coding", true, false}, {"reasoning", false, true},
		{"creative", false, false}, {"image", false, false}, {"", false, false}, {"chinese", false, false},
	}
	for _, c := range cases {
		if got := shouldRedirectToHost(c.hint, c.pressure); got != c.want {
			t.Errorf("shouldRedirectToHost(%q,%v)=%v want %v", c.hint, c.pressure, got, c.want)
		}
	}
}

func TestRouteORModel(t *testing.T) {
	cases := []struct {
		hint        string
		hasKimi     bool
		wantModel   string
		wantMatched bool
	}{
		{"creative", false, "minimax/minimax-m2.7", true},
		{"coding", true, routeKimi, true},
		{"coding", false, "deepseek/deepseek-v4-pro", true},
		{"reasoning", false, "deepseek/deepseek-v4-pro", true},
		{"fast", false, "deepseek/deepseek-v4-flash", true},
		{"premium", false, "xiaomi/mimo-v2.5-pro", true},
		{"ultra long", false, "deepseek/deepseek-v4-pro", true},
		{"very long document", false, "deepseek/deepseek-v4-pro", true},
		{"image", false, "", false},
		{"nonsense", false, "", false},
	}
	for _, c := range cases {
		m, matched := routeORModel(c.hint, c.hasKimi)
		if m != c.wantModel || matched != c.wantMatched {
			t.Errorf("routeORModel(%q,%v)=(%q,%v) want (%q,%v)", c.hint, c.hasKimi, m, matched, c.wantModel, c.wantMatched)
		}
	}
}

func TestResolveProfileModel(t *testing.T) {
	cases := []struct {
		profile string
		hint    string
		hasKimi bool
		want    string
	}{
		{"eco", "", false, "deepseek/deepseek-v4-flash"},
		{"mid", "", false, "qwen/qwen3.5-plus-20260420"},
		{"intel", "", false, "deepseek/deepseek-v4-pro"},
		{"max", "", false, "xiaomi/mimo-v2.5-pro"},
		{"research", "", false, "deepseek/deepseek-v4-pro"},
		{"max", "reasoning", false, "deepseek/deepseek-v4-pro"},
		{"max", "math", false, "deepseek/deepseek-v4-pro"},
		{"max", "proof", false, "deepseek/deepseek-v4-pro"},
		{"max", "logic", false, "deepseek/deepseek-v4-pro"},
		{"max", "narrative", false, "minimax/minimax-m2.7"}, // specialist beats max default
		{"eco", "coding", true, profileUseKimi},
		{"max", "debug", true, profileUseKimi},
		{"eco", "refactor", true, profileUseKimi},
		{"eco", "coding", false, "deepseek/deepseek-v4-flash"}, // no kimi → no subscription bypass
		{"eco", "creative", false, "minimax/minimax-m2.7"},
		{"intel", "creative", false, "minimax/minimax-m2.7"},
		{"bogus", "", false, ""},
		{"", "", false, ""},
	}
	for _, c := range cases {
		got, _ := resolveProfileModel(c.profile, c.hint, c.hasKimi)
		if got != c.want {
			t.Errorf("resolveProfileModel(%q,%q,%v)=%q want %q", c.profile, c.hint, c.hasKimi, got, c.want)
		}
	}
}

func TestProfileNotes(t *testing.T) {
	if _, note := resolveProfileModel("intel", "", false); !strings.Contains(note, "intel") {
		t.Errorf("profile note missing profile name: %q", note)
	}
	if _, snote := resolveProfileModel("eco", "creative", false); !strings.Contains(snote, "creative") {
		t.Errorf("specialist note missing keyword: %q", snote)
	}
}

func TestGPTAuditGate(t *testing.T) {
	t.Setenv("AI_ROUTER_ALLOW_GPT55_AUDIT", "")
	t.Setenv("AI_ROUTER_GPT_GATE_FILE", "/nonexistent/ai-router-gate")
	if gptAuditExceptionAllowed("openai/gpt-5.5-pro") {
		t.Error("audit exception allowed by default — must be off")
	}
	if !isBanned("openai/gpt-5.5-pro") {
		t.Error("openai/gpt-5.5-pro must be banned")
	}
	t.Setenv("AI_ROUTER_ALLOW_GPT55_AUDIT", "1")
	if !gptAuditExceptionAllowed("openai/gpt-5.5-pro") {
		t.Error("env opt-in did not enable the exception")
	}
	if gptAuditExceptionAllowed("openai/gpt-4o") {
		t.Error("non-allowlisted openai id passed the gate")
	}
}

func TestGPTAuditGateFile(t *testing.T) {
	dir := t.TempDir()
	gate := dir + "/gate"
	t.Setenv("AI_ROUTER_ALLOW_GPT55_AUDIT", "")
	t.Setenv("AI_ROUTER_GPT_GATE_FILE", gate)
	if gptAuditEnabled() {
		t.Error("no gate file → must be off")
	}
	if err := os.WriteFile(gate, []byte(""), 0o644); err != nil {
		t.Fatal(err)
	}
	if gptAuditEnabled() {
		t.Error("empty gate file → must be off")
	}
	if err := os.WriteFile(gate, []byte("accepted"), 0o644); err != nil {
		t.Fatal(err)
	}
	if !gptAuditEnabled() {
		t.Error("non-empty gate file → must be on")
	}
}

func TestOutputOrFileInline(t *testing.T) {
	if got := outputOrFile("hello", "t"); got != "hello" {
		t.Errorf("small content not inline: %q", got)
	}
	if got := outputOrFile(strings.Repeat("x", inlineMaxChars+1), "t"); !containsAny(got, []string{"written to file"}) {
		t.Error("large content not written to file")
	}
}
