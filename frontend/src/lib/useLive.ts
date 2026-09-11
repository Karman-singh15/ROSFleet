"use client";

/**
 * Live fleet updates over the backend's WebSocket, with polling as a
 * fallback.
 *
 * Why both: the WebSocket gives instant updates while it is up, but a
 * dashboard that silently freezes when the socket drops is worse than one
 * that is a few seconds stale. Polling continues regardless and is the
 * safety net.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { WS_URL } from "./api";
import type { LiveMessage } from "./types";

export function useLive(onMessage: (message: LiveMessage) => void) {
  const [connected, setConnected] = useState(false);
  // Keep the latest callback in a ref so reconnection logic does not restart
  // every time the parent re-renders with a new closure.
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let keepalive: ReturnType<typeof setInterval> | null = null;
    let closed = false;

    const connect = () => {
      if (closed) return;
      try {
        socket = new WebSocket(WS_URL);
      } catch {
        retry = setTimeout(connect, 3000);
        return;
      }

      socket.onopen = () => {
        setConnected(true);
        // The server reads to notice disconnects; send something periodically
        // so an idle proxy does not time the connection out.
        keepalive = setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
        }, 20000);
      };

      socket.onmessage = (event) => {
        try {
          handler.current(JSON.parse(event.data) as LiveMessage);
        } catch {
          /* ignore anything that is not JSON we understand */
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (keepalive) clearInterval(keepalive);
        if (!closed) retry = setTimeout(connect, 3000);
      };

      socket.onerror = () => socket?.close();
    };

    connect();

    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      if (keepalive) clearInterval(keepalive);
      socket?.close();
    };
  }, []);

  return connected;
}

/** Re-run `load` on an interval, and once immediately. */
export function usePoll(load: () => void | Promise<void>, ms = 3000) {
  const saved = useRef(load);
  saved.current = load;

  useEffect(() => {
    let active = true;
    const run = () => {
      if (active) void saved.current();
    };
    run();
    const timer = setInterval(run, ms);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [ms]);
}

/** Load once, with loading and error state. Used by the simpler pages. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const saved = useRef(load);
  saved.current = load;

  const refresh = useCallback(async () => {
    try {
      const result = await saved.current();
      setData(result);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, refresh };
}
