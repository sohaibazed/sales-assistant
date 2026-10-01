import { Client } from "@langchain/langgraph-sdk";

export function createClient(
  apiUrl: string,
  apiKey: string | undefined,
  authScheme: string | undefined,
  token?: string,
) {
  const defaultHeaders: Record<string, string> = {};
  if (authScheme) defaultHeaders["X-Auth-Scheme"] = authScheme;
  // The signed-in rep's session (../lib/auth.tsx); the server reads the rep from it.
  if (token) defaultHeaders["Authorization"] = `Bearer ${token}`;
  return new Client({ apiKey, apiUrl, defaultHeaders });
}
