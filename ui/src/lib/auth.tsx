"use client";

import {
  createContext,
  FormEvent,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useQueryState } from "nuqs";
import { toast } from "sonner";
import { LogIn } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import { LangGraphLogoSVG } from "@/components/icons/langgraph";
import { resolveApiUrl } from "@/lib/resolve-api-url";

// Login for the Agent Server (../auth.py, ../webapp.py). POST /auth/login returns a signed
// token with the rep inside; every API call sends it as `Authorization: Bearer`. The server
// takes the rep from the token, so the UI never sends rep_id itself and can't pick another rep.

export type SessionUser = { username: string; rep_id: number; name: string };
type Session = { token: string; user: SessionUser; expires_at: number };

type AuthContextType = {
  token: string;
  user: SessionUser;
  signOut: (reason?: string) => void;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// sessionStorage: closing the tab signs you out; per API origin, like the API key.
function storageKey(apiUrl: string): string {
  try {
    return `chinook:session:${new URL(apiUrl).origin}`;
  } catch {
    return `chinook:session:${apiUrl}`;
  }
}

function loadSession(apiUrl: string): Session | null {
  try {
    const raw = window.sessionStorage.getItem(storageKey(apiUrl));
    if (!raw) return null;
    const session = JSON.parse(raw) as Session;
    return session.expires_at * 1000 > Date.now() ? session : null;
  } catch {
    return null;
  }
}

function saveSession(apiUrl: string, session: Session | null): void {
  try {
    if (session) {
      window.sessionStorage.setItem(storageKey(apiUrl), JSON.stringify(session));
    } else {
      window.sessionStorage.removeItem(storageKey(apiUrl));
    }
  } catch {
    // no-op: private mode etc. The session then lasts until the page reloads.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const envApiUrl: string | undefined = process.env.NEXT_PUBLIC_API_URL;
  const [queryApiUrl] = useQueryState("apiUrl", {
    defaultValue: envApiUrl || "",
  });
  const [, setThreadId] = useQueryState("threadId");
  const apiUrl = resolveApiUrl(queryApiUrl, envApiUrl);

  const [session, setSession] = useState<Session | null>(null);
  const [loaded, setLoaded] = useState(false);

  const signOut = useCallback(
    (reason?: string) => {
      saveSession(apiUrl, null);
      setSession(null);
      setThreadId(null);
      if (reason) toast.info(reason);
    },
    [apiUrl, setThreadId],
  );

  // Restore the session for this server, then make sure the server still accepts it.
  useEffect(() => {
    if (!apiUrl) return;
    const stored = loadSession(apiUrl);
    setSession(stored);
    setLoaded(true);
    if (!stored) return;
    fetch(`${apiUrl}/auth/me`, {
      headers: { Authorization: `Bearer ${stored.token}` },
    })
      .then((res) => {
        if (res.status !== 401) return;
        saveSession(apiUrl, null);
        setSession(null);
        toast.info("Your session ended. Sign in again.");
      })
      .catch(() => undefined); // offline: Stream shows its own connection error
  }, [apiUrl]);

  // Sign out when the token expires instead of failing on the next request.
  useEffect(() => {
    if (!session) return;
    const ms = session.expires_at * 1000 - Date.now();
    const timer = setTimeout(
      () => signOut("Your session expired. Sign in again."),
      Math.max(ms, 0),
    );
    return () => clearTimeout(timer);
  }, [session, signOut]);

  // No server chosen yet: let StreamProvider show its setup form first.
  if (!apiUrl) return <>{children}</>;
  if (!loaded) return null;
  if (!session) {
    return (
      <LoginForm
        apiUrl={apiUrl}
        onSignedIn={(s) => {
          saveSession(apiUrl, s);
          setThreadId(null);
          setSession(s);
        }}
      />
    );
  }

  return (
    <AuthContext.Provider
      value={{ token: session.token, user: session.user, signOut }}
    >
      {children}
    </AuthContext.Provider>
  );
}

/** The signed-in session, or null before login (e.g. on the server setup form). */
export function useAuth(): AuthContextType | null {
  return useContext(AuthContext) ?? null;
}

function LoginForm({
  apiUrl,
  onSignedIn,
}: {
  apiUrl: string;
  onSignedIn: (session: Session) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${apiUrl}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: form.get("username"),
          password: form.get("password"),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(body.detail ?? `Sign-in failed (HTTP ${res.status}).`);
        return;
      }
      onSignedIn(body as Session);
    } catch {
      setError(`Can't reach the server at ${apiUrl}.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen w-full items-center justify-center p-4">
      <div className="animate-in fade-in-0 zoom-in-95 bg-background flex w-full max-w-md flex-col rounded-lg border shadow-lg">
        <div className="flex flex-col gap-2 border-b p-6">
          <LangGraphLogoSVG className="h-7 self-start" />
          <h1 className="text-xl font-semibold tracking-tight">
            Chinook Sales Assistant
          </h1>
          <p className="text-muted-foreground text-sm">
            Sign in with your sales rep account. The assistant works on your
            territory and signs mail in your name.
          </p>
        </div>
        <form
          onSubmit={submit}
          className="bg-muted/50 flex flex-col gap-5 p-6"
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              name="username"
              autoComplete="username"
              autoFocus
              required
              className="bg-background"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">Password</Label>
            <PasswordInput
              id="password"
              name="password"
              autoComplete="current-password"
              required
              className="bg-background"
            />
          </div>
          {error && (
            <p
              role="alert"
              className="text-sm text-rose-600"
            >
              {error}
            </p>
          )}
          <div className="flex justify-end">
            <Button
              type="submit"
              size="lg"
              disabled={busy}
            >
              {busy ? "Signing in…" : "Sign in"}
              <LogIn className="size-5" />
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
