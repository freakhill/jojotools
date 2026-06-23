package main

// catalog.go — models.json is embedded into the binary (go:embed) so each
// cross-compiled artifact is fully self-contained: no config file to ship
// alongside. Mirrors server.py:_load_model_catalog / _apply_routing_config.

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"
)

//go:embed models.json
var modelsJSON []byte

type ORModel struct {
	ID             string   `json:"id"`
	Name           string   `json:"name"`
	InputCostPerM  float64  `json:"input_cost_per_m"`
	OutputCostPerM float64  `json:"output_cost_per_m"`
	ContextK       int      `json:"context_k"`
	ZDREligible    bool     `json:"zdr_eligible"`
	Strengths      []string `json:"strengths"`
	BestFor        string   `json:"best_for"`
	Tier           string   `json:"tier"`
	NoTraining     bool     `json:"no_training"`
}

type Tier2Entry struct {
	Provider  string   `json:"provider"`
	Prefix    string   `json:"prefix"`
	ModelIDs  []string `json:"model_ids"`
	EnvVar    string   `json:"env_var"`
	MCPTools  []string `json:"mcp_tools"`
	TaskHints []string `json:"task_hints"`
}

type RoutingConfig struct {
	Tier1 struct {
		Prefixes  []string `json:"prefixes"`
		ModelIDs  []string `json:"model_ids"`
		Note      string   `json:"note"`
		TaskHints []string `json:"task_hints"`
	} `json:"tier_1_host_native"`
	Tier2 struct {
		Entries []Tier2Entry `json:"entries"`
	} `json:"tier_2_subscription_api"`
	Banned struct {
		Prefixes []string `json:"prefixes"`
		ModelIDs []string `json:"model_ids"`
	} `json:"banned_providers"`
}

type Profile struct {
	Description   string `json:"description"`
	CostTarget    string `json:"cost_target"`
	PrimaryModel  string `json:"primary_model"`
	FallbackModel string `json:"fallback_model"`
	Note          string `json:"note"`
}

type Catalog struct {
	Version     string                     `json:"version"`
	Updated     string                     `json:"updated"`
	ORModels    []ORModel                  `json:"openrouter_models"`
	ImageModels []json.RawMessage          `json:"image_generation_models"`
	// Profiles stays RawMessage: the map also holds a "_comment" string value that
	// would fail to unmarshal into Profile. Decode named profiles on demand.
	Profiles map[string]json.RawMessage `json:"profiles"`
	Routing  RoutingConfig              `json:"routing_config"`
}

func getProfile(name string) (Profile, bool) {
	raw, ok := catalog.Profiles[name]
	if !ok {
		return Profile{}, false
	}
	var p Profile
	if json.Unmarshal(raw, &p) != nil {
		return Profile{}, false
	}
	return p, true
}

// Routing globals — start at the safe hardcoded defaults from server.py, then
// applyRoutingConfig() overrides them from models.json's routing_config.
var (
	catalog           Catalog
	catalogByID       = map[string]ORModel{}
	orBlockedPrefixes = []string{"anthropic/", "moonshotai/", "zai/"} // tier 1+2 defaults
	orBlockedIDs      = map[string]bool{}
	bannedPrefixes    = []string{"openai/", "x-ai/"}
	bannedIDs         = map[string]bool{}
)

func loadCatalog() error {
	if err := json.Unmarshal(modelsJSON, &catalog); err != nil {
		return fmt.Errorf("parse embedded models.json: %w", err)
	}
	applyRoutingConfig()
	for _, m := range catalog.ORModels {
		catalogByID[m.ID] = m
	}
	return nil
}

func applyRoutingConfig() {
	rc := catalog.Routing
	var prefixes []string
	ids := map[string]bool{}

	prefixes = append(prefixes, rc.Tier1.Prefixes...)
	for _, id := range rc.Tier1.ModelIDs {
		ids[id] = true
	}
	if len(rc.Tier1.TaskHints) > 0 {
		hostCapableHints = rc.Tier1.TaskHints
	}

	for _, e := range rc.Tier2.Entries {
		if e.Prefix != "" && !contains(prefixes, e.Prefix) {
			prefixes = append(prefixes, e.Prefix)
		}
		for _, id := range e.ModelIDs {
			ids[id] = true
		}
		if e.Provider == "moonshotai" && len(e.TaskHints) > 0 {
			kimiSubHints = e.TaskHints
		}
	}

	if len(prefixes) > 0 {
		orBlockedPrefixes = prefixes
	}
	if len(ids) > 0 {
		orBlockedIDs = ids
	}
	if len(rc.Banned.Prefixes) > 0 {
		bannedPrefixes = rc.Banned.Prefixes
	}
	if len(rc.Banned.ModelIDs) > 0 {
		bannedIDs = map[string]bool{}
		for _, id := range rc.Banned.ModelIDs {
			bannedIDs[id] = true
		}
	}
}

// --- ban / block (server.py:_is_banned / _is_blocked_from_or) ---

func isBanned(model string) bool {
	if bannedIDs[model] {
		return true
	}
	for _, p := range bannedPrefixes {
		if strings.HasPrefix(model, p) {
			return true
		}
	}
	return false
}

func isBlockedFromOR(model string) bool {
	if orBlockedIDs[model] {
		return true
	}
	for _, p := range orBlockedPrefixes {
		if strings.HasPrefix(model, p) {
			return true
		}
	}
	return false
}

func blockedFromORReason(model string) string {
	for _, p := range orBlockedPrefixes {
		if strings.HasPrefix(model, p) {
			return fmt.Sprintf("'%s*' models are blocked from OpenRouter (tier-1/2 subscription). "+
				"Edit routing_config in models.json to change this.", p)
		}
	}
	return "Model is in the OR blocked list. Edit routing_config.tier_1_host_native or " +
		"tier_2_subscription_api in models.json."
}

func contains(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}
