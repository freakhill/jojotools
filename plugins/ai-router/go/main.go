package main

// ai-router (Go prototype) — stdio MCP server.
// Single static binary; models.json is embedded. Cross-compile with `make all`.

import (
	"context"
	"log"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

const version = "2.0.0-go"

func main() {
	if err := loadCatalog(); err != nil {
		log.Fatalf("ai-router: %v", err)
	}
	s := mcp.NewServer(&mcp.Implementation{Name: "ai-router", Version: version}, nil)
	registerTools(s)
	if err := s.Run(context.Background(), &mcp.StdioTransport{}); err != nil {
		log.Fatalf("ai-router: server exited: %v", err)
	}
}
