package main

// routing.go — pure routing logic ported 1:1 from server.py. These are the
// "crown jewels" the README calls out: host-redirect, the OR routing table,
// profile precedence, and the GPT-5.5 audit gate. All deterministic → unit-tested.

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Sentinels distinct from any real model id (NUL-prefixed → can't collide).
const (
	routeKimi      = "\x00kimi" // route to Kimi subscription instead of OR
	profileUseKimi = "\x00kimi"
)

// --- host self-handle (server.py:_should_redirect_to_host) ---

var hostCapableHints = []string{
	"reasoning", "coding", "analysis", "summarization", "summarise", "summarize",
	"qa", "q&a", "math", "maths", "planning", "structured output", "instruction",
	"brainstorm", "edit", "proofread", "rewrite", "explain", "research",
}

var orRequiredHints = []string{
	"image", "image generation", "image_generation", "visual", "thumbnail",
	"youtube thumbnail", "creative image", "ultra long context", "ultra_long_context",
	"2m context", "2m tokens", "minimax", "creative", "story", "fiction", "narrative",
}

func shouldRedirectToHost(taskHint string, hostPressure bool) bool {
	if hostPressure {
		return false // host constrained → offload
	}
	hl := strings.ToLower(strings.TrimSpace(taskHint))
	if containsAny(hl, orRequiredHints) {
		return false
	}
	if containsAny(hl, hostCapableHints) {
		return true
	}
	return false
}

// --- OR routing table (server.py:_route_or_model + _OR_ROUTING) ---

type routeRule struct {
	keys  []string
	model string // "" → image entry (caller shows alternatives)
}

var orRouting = []routeRule{
	{[]string{"image", "image generation", "thumbnail", "youtube thumbnail", "visual", "picture", "photo", "illustration"}, ""},
	{[]string{"creative", "story", "fiction", "narrative", "creative writing"}, "minimax/minimax-m2.7"},
	{[]string{"ultra long", "ultra_long", "2m context", "2m tokens", "very long document", "massive context"}, "deepseek/deepseek-v4-pro"},
	{[]string{"premium", "strongest", "hardest", "frontier"}, "xiaomi/mimo-v2.5-pro"},
	{[]string{"fast", "cheap", "quick", "batch", "high volume"}, "deepseek/deepseek-v4-flash"},
	{[]string{"reasoning", "math", "proof", "logic"}, "deepseek/deepseek-v4-pro"},
	{[]string{"coding", "code", "debug", "refactor", "agentic"}, "deepseek/deepseek-v4-pro"},
}

var kimiSubHints = []string{
	"coding", "code", "debug", "refactor", "agentic", "analysis",
	"codebase", "analyze", "reasoning", "math", "research", "batch",
}

// routeORModel mirrors _route_or_model. matched=false → caller shows the
// alternatives table (Python None); model==routeKimi → use Kimi subscription.
func routeORModel(taskHint string, hasKimi bool) (model string, matched bool) {
	hl := strings.ToLower(strings.TrimSpace(taskHint))
	if hasKimi && containsAny(hl, kimiSubHints) {
		return routeKimi, true
	}
	for _, r := range orRouting {
		if containsAny(hl, r.keys) {
			if r.model == "" {
				return "", false // image table entry → alternatives
			}
			return r.model, true
		}
	}
	return "", false
}

// --- ambiguous/creative (server.py:_is_ambiguous_creative) ---

var ambiguousHints = []string{
	"creative", "story", "fiction", "narrative", "creative writing", "write", "writing",
	"general", "chat", "conversation", "mixed", "storytelling", "poem", "poetry",
	"blog", "essay", "script",
}

func isAmbiguousCreative(taskHint string) bool {
	return containsAny(strings.ToLower(strings.TrimSpace(taskHint)), ambiguousHints)
}

// --- profile resolution (server.py:_resolve_profile_model) ---

// Ordered so specialist precedence is deterministic (Go map iteration is random).
var specialistHints = []struct{ kw, model string }{
	{"creative", "minimax/minimax-m2.7"},
	{"story", "minimax/minimax-m2.7"},
	{"fiction", "minimax/minimax-m2.7"},
	{"narrative", "minimax/minimax-m2.7"},
}

var subscriptionHints = []string{
	"coding", "code", "debug", "refactor", "agentic", "analysis", "codebase", "analyze",
}

var profileDefaultModels = map[string]string{
	"eco":      "deepseek/deepseek-v4-flash",
	"mid":      "qwen/qwen3.5-plus-20260420",
	"intel":    "deepseek/deepseek-v4-pro",
	"max":      "xiaomi/mimo-v2.5-pro",
	"research": "deepseek/deepseek-v4-pro",
}

var maxReasoningHints = []string{"reasoning", "math", "proof", "logic", "maths"}

// resolveProfileModel returns (modelOrSentinel, note). Empty model → no profile
// resolution (caller falls through to normal routing).
func resolveProfileModel(profile, taskHint string, hasKimi bool) (string, string) {
	def, ok := profileDefaultModels[profile]
	if profile == "" || !ok {
		return "", ""
	}
	hl := strings.ToLower(strings.TrimSpace(taskHint))

	// 1. Subscription-first (no marginal $ — beats any profile)
	if hasKimi && containsAny(hl, subscriptionHints) {
		return profileUseKimi, fmt.Sprintf(
			"[Profile: %s | Routed to Kimi K2.6 subscription — no marginal $, overrides profile]", profile)
	}
	// 2. Specialist override
	for _, s := range specialistHints {
		if strings.Contains(hl, s.kw) {
			return s.model, fmt.Sprintf("[Profile: %s | Specialist override: %s → %s]", profile, s.kw, s.model)
		}
	}
	// 3. max + reasoning → deepseek
	if profile == "max" && containsAny(hl, maxReasoningHints) {
		return "deepseek/deepseek-v4-pro", "[Profile: max | Reasoning task → deepseek-v4-pro (80.6% SWE-bench)]"
	}
	// 4. profile default
	note := fmt.Sprintf("[Profile: %s | Model: %s]", profile, def)
	if profile == "research" && hl != "" &&
		!containsAny(hl, []string{"long", "document", "synthesis", "research", "analyze", "compile", "summarize", "context", "ultra", "large", "corpus", "codebase"}) {
		note = fmt.Sprintf("[Profile: research | Note: research profile targets long-context synthesis "+
			"(1.05M ctx). For short tasks, 'intel' profile is more cost-efficient. Using %s]", def)
	}
	return def, note
}

// --- GPT-5.5 audit gate (server.py:_gpt_audit_*) ---

var gptAuditModelIDs = map[string]bool{"openai/gpt-5.5-pro": true}

func gptAuditEnabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("AI_ROUTER_ALLOW_GPT55_AUDIT"))) {
	case "1", "true", "yes", "on":
		return true
	}
	gate := os.Getenv("AI_ROUTER_GPT_GATE_FILE")
	if gate == "" {
		home, _ := os.UserHomeDir()
		gate = filepath.Join(home, ".config", "ai-router", "gpt55-accepted")
	}
	b, err := os.ReadFile(gate)
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(b)) != ""
}

func gptAuditExceptionAllowed(model string) bool {
	return gptAuditModelIDs[model] && gptAuditEnabled()
}

// --- alternatives tables (server.py:_build_alternatives_table / _build_creative_alternatives_table) ---

func buildAlternativesTable(recommended string) string {
	highlights := []string{
		"deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash", "xiaomi/mimo-v2.5-pro",
		"minimax/minimax-m2.7", "qwen/qwen3.5-plus-20260420", "google/gemini-3.1-flash-lite",
	}
	var rows []string
	for _, id := range highlights {
		m, ok := catalogByID[id]
		if !ok {
			continue
		}
		label := m.Name
		if id == recommended {
			label = "**" + m.Name + " (recommended)**"
		}
		rows = append(rows, fmt.Sprintf("| %s | `%s` | %s | $%.3f/M in |",
			label, m.ID, strings.Join(firstN(m.Strengths, 3), ", "), m.InputCostPerM))
	}
	return "## Routing Recommendation\n\nTask type unclear. Top alternatives:\n\n" +
		"| Model | ID | Strengths | Cost |\n|---|---|---|---|\n" +
		"| Kimi K2.6 | `kimi_ask` (subscription) | agentic coding, long-horizon | flat-rate sub (no marginal $) |\n" +
		strings.Join(rows, "\n") +
		"\n\n**Re-call with** `model=\"<model-id>\"` to execute with your chosen model.\n" +
		"**Or** provide `task_hint` (e.g. `\"coding\"`, `\"creative\"`, `\"reasoning\"`, `\"image\"`) for auto-routing."
}

func buildCreativeAlternativesTable(recommendedID, recommendedName, taskHint string) string {
	creativeAlts := []struct{ id, why string }{
		{"minimax/minimax-m2.7", "narrative depth, long-form, creative specialist"},
		{"xiaomi/mimo-v2.5-pro", "strong general-purpose, high usage, balanced"},
		{"deepseek/deepseek-v4-pro", "creative reasoning, structured narrative"},
		{"qwen/qwen3.5-plus-20260420", "balanced creative, multilingual, 1M ctx"},
	}
	seen := map[string]bool{recommendedID: true}
	var rows []string
	if rec, ok := catalogByID[recommendedID]; ok {
		rows = append(rows, fmt.Sprintf("| **%s (recommended)** | `%s` | %s | $%.3f/M in |",
			recommendedName, recommendedID, strings.Join(firstN(rec.Strengths, 3), ", "), rec.InputCostPerM))
	} else {
		rows = append(rows, fmt.Sprintf("| **%s (recommended)** | `%s` | auto-selected for task | see OR |", recommendedName, recommendedID))
	}
	added := 0
	for _, a := range creativeAlts {
		if seen[a.id] || added >= 3 {
			continue
		}
		if m, ok := catalogByID[a.id]; ok {
			rows = append(rows, fmt.Sprintf("| %s | `%s` | %s | $%.3f/M in |", m.Name, a.id, a.why, m.InputCostPerM))
		} else {
			rows = append(rows, fmt.Sprintf("| %s | `%s` | %s | see OR |", lastSeg(a.id), a.id, a.why))
		}
		seen[a.id] = true
		added++
	}
	return fmt.Sprintf("\n\n---\n## Alternatives for `%s` tasks\n\n"+
		"Multiple models excel at creative/writing work. Result above used **%s**.\n\n"+
		"| Model | ID | Strengths | Cost |\n|---|---|---|---|\n%s\n\n"+
		"**Switch model:** re-call with `model=\"<model-id>\"` to use a different one.",
		taskHint, recommendedName, strings.Join(rows, "\n"))
}

// --- small helpers ---

func containsAny(hay string, needles []string) bool {
	for _, n := range needles {
		if strings.Contains(hay, n) {
			return true
		}
	}
	return false
}

func firstN(s []string, n int) []string {
	if len(s) > n {
		return s[:n]
	}
	return s
}

func lastSeg(id string) string {
	if i := strings.LastIndex(id, "/"); i >= 0 {
		return id[i+1:]
	}
	return id
}
