// MCP server management — wraps /api/mcp/* (Claude Code user-scope servers).
import { api } from "./client";

export interface MCPServer {
  name: string;
  type: string;        // "stdio" | "http" | "sse"
  command: string;
  args: string[];
  url: string;
  env_keys: string[];
}

export async function listMCPServers(): Promise<MCPServer[]> {
  const { data } = await api.get<{ servers: MCPServer[] }>("/mcp/servers");
  return data.servers;
}

export async function addMCPServer(name: string, config: Record<string, unknown>): Promise<void> {
  await api.post("/mcp/servers", { name, config });
}

export async function removeMCPServer(name: string): Promise<void> {
  await api.delete(`/mcp/servers/${encodeURIComponent(name)}`);
}
