"use client";

import { FormEvent, useState } from "react";
import { KeyRound, LogOut } from "lucide-react";

import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export function AuthControls() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [authenticated, setAuthenticated] = useState(() =>
    typeof window !== "undefined" && Boolean(localStorage.getItem("invoice_access_token") || localStorage.getItem("invoice_api_key"))
  );
  const [message, setMessage] = useState("");

  const login = async (event: FormEvent) => {
    event.preventDefault();
    setMessage("");
    try {
      if (apiKey.trim()) {
        localStorage.setItem("invoice_api_key", apiKey.trim());
        localStorage.removeItem("invoice_access_token");
      } else {
        const response = await apiClient.post<{ access_token: string }>("/auth/token", { username, password });
        localStorage.setItem("invoice_access_token", response.data.access_token);
        localStorage.removeItem("invoice_api_key");
      }
      setAuthenticated(true);
      setMessage("Credentials saved. Refreshing data…");
      window.setTimeout(() => window.location.reload(), 400);
    } catch {
      setMessage("Authentication failed. Check the configured credentials.");
    }
  };

  const logout = () => {
    localStorage.removeItem("invoice_access_token");
    localStorage.removeItem("invoice_api_key");
    setAuthenticated(false);
    window.location.reload();
  };

  if (authenticated) {
    return <Button variant="outline" onClick={logout}><LogOut className="h-4 w-4" /> Sign out</Button>;
  }

  return (
    <Dialog>
      <DialogTrigger render={<Button variant="outline" />}><KeyRound className="h-4 w-4" /> API access</DialogTrigger>
      <DialogContent>
        <form onSubmit={login} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Connect to a protected API</DialogTitle>
            <DialogDescription>Use either the configured dashboard login or an API key. Local development works without credentials.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2"><Label htmlFor="username">Username</Label><Input id="username" value={username} onChange={(event) => setUsername(event.target.value)} /></div>
          <div className="space-y-2"><Label htmlFor="password">Password</Label><Input id="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></div>
          <div className="relative py-1 text-center text-xs text-muted-foreground before:absolute before:left-0 before:right-0 before:top-1/2 before:border-t before:border-white/10"><span className="relative bg-popover px-2">or</span></div>
          <div className="space-y-2"><Label htmlFor="api-key">API key</Label><Input id="api-key" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></div>
          {message && <p role="status" className="text-xs text-muted-foreground">{message}</p>}
          <DialogFooter><Button type="submit">Save and connect</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
