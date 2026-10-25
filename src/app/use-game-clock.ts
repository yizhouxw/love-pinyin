import { useCallback, useEffect, useRef, useState } from 'react';
import { gameCatalog, type GameClock } from '../domain/games';
import { api } from '../platform/api-client';

/** A monotonic local deadline may only shorten the server's short authorization. */
export function useGameClock(enabled: boolean, stopVoice: () => void) {
  const [clock, setClock] = useState<GameClock | null>(null);
  const [paused, setPaused] = useState(true);
  const [reason, setReason] = useState('');
  const deadline = useRef(0);
  const expiryReason = useRef('GAME_PAUSED');
  const hold = useRef(true);
  const inFlight = useRef(false);
  const request = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const stop = useRef(stopVoice);
  useEffect(() => {
    stop.current = stopVoice;
  }, [stopVoice]);
  const pause = useCallback((message: string) => {
    epoch.current += 1;
    request.current?.abort();
    hold.current = true;
    deadline.current = 0;
    setPaused(true);
    setReason(message);
    stop.current();
  }, []);
  const resume = useCallback(async () => {
    if (inFlight.current || document.hidden) return;
    const generation = epoch.current;
    inFlight.current = true;
    const started = performance.now();
    const controller = new AbortController();
    request.current = controller;
    const timeout = window.setTimeout(
      () => controller.abort(),
      gameCatalog.policy.requestTimeoutSeconds * 1000,
    );
    try {
      const next = (await api('/games/heartbeat', {
        method: 'POST',
        signal: controller.signal,
      })) as GameClock;
      if (generation !== epoch.current) return;
      setClock(next);
      const until = started + next.leaseSeconds * 1000;
      if (next.reason || until <= performance.now()) pause(next.reason ?? 'GAME_PAUSED');
      else {
        expiryReason.current =
          next.remainingSeconds <= next.leaseSeconds + 0.05
            ? next.dailyMinutes * 60 - next.dailySeconds <=
              next.sessionMinutes * 60 - next.sessionSeconds
              ? 'GAME_DAILY_LIMIT'
              : 'GAME_SESSION_LIMIT'
            : 'GAME_PAUSED';
        deadline.current = until;
        hold.current = false;
        setPaused(false);
        setReason('');
      }
    } catch (error) {
      if (generation === epoch.current)
        pause(
          controller.signal.aborted
            ? 'MAC_UNREACHABLE'
            : error instanceof Error
              ? error.message
              : 'MAC_UNREACHABLE',
        );
    } finally {
      window.clearTimeout(timeout);
      if (request.current === controller) request.current = null;
      inFlight.current = false;
    }
  }, [pause]);
  useEffect(() => {
    epoch.current += 1;
    if (!enabled) return;
    hold.current = true;
    queueMicrotask(() => {
      pause('');
      void resume();
    });
    const renew = window.setInterval(() => {
      if (!hold.current && !document.hidden) void resume();
    }, gameCatalog.policy.heartbeatSeconds * 1000);
    const check = window.setInterval(() => {
      if (!hold.current && performance.now() >= deadline.current) pause(expiryReason.current);
    }, 100);
    const visible = () => {
      if (document.hidden) pause('GAME_PAUSED');
      // Returning to the tab still requires an explicit renewal before answering.
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      epoch.current += 1;
      request.current?.abort();
      window.clearInterval(renew);
      window.clearInterval(check);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [enabled, pause, resume]);
  return { clock, paused: enabled && paused, reason, resume, pause };
}
