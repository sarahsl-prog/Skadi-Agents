"""Shared API client for the Analyst Console."""

import { useCallback, useState } from "react";

const API_BASE = "";
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "dev-token-do-not-use-in-production";

async function apiFetch(path: string, init?: RequestInit) {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Token": API_TOKEN,
      ...(init?.headers || {}),
    },
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`API error ${resp.status}: ${body}`);
  }
  return resp.json();
}

export async function listCases(statusFilter?: string) {
  const qs = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  return apiFetch(`/api/cases${qs}`);
}

export async function getCase(caseId: string) {
  return apiFetch(`/api/cases/${encodeURIComponent(caseId)}`);
}

export async function getTimeline(caseId: string) {
  return apiFetch(`/api/cases/${encodeURIComponent(caseId)}/timeline`);
}

export async function getVerdict(caseId: string) {
  return apiFetch(`/api/cases/${encodeURIComponent(caseId)}/verdict`);
}

export async function reviewQueue() {
  return apiFetch("/api/review/queue");
}

export async function approveCase(caseId: string) {
  return apiFetch(`/api/review/${encodeURIComponent(caseId)}/approve`, { method: "POST" });
}

export async function escalateCase(caseId: string) {
  return apiFetch(`/api/review/${encodeURIComponent(caseId)}/escalate`, { method: "POST" });
}

export async function closeBenign(caseId: string) {
  return apiFetch(`/api/review/${encodeURIComponent(caseId)}/close_benign`, { method: "POST" });
}

export async function continueHunt(caseId: string) {
  return apiFetch(`/api/review/${encodeURIComponent(caseId)}/continue_hunt`, { method: "POST" });
}

export async function showRaw(caseId: string, field: string) {
  return apiFetch(
    `/api/cases/${encodeURIComponent(caseId)}/show-raw?field=${encodeURIComponent(field)}`,
    { method: "POST" }
  );
}

export function useWebSocket(caseId: string | null) {
  const [messages, setMessages] = useState<any[]>([]);
  const [connected, setConnected] = useState(false);

  const connect = useCallback(() => {
    if (!caseId) return;
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/cases/${encodeURIComponent(caseId)}`);
    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ type: "auth", token: API_TOKEN }));
    };
    ws.onmessage = (ev) => {
      setMessages((prev) => [...prev, JSON.parse(ev.data)]);
    };
    ws.onclose = () => setConnected(false);
    return () => ws.close();
  }, [caseId]);

  return { messages, connected, connect };
}
