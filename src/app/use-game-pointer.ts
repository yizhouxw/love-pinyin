import { useEffect, useRef, type PointerEvent } from 'react';
import type { Action, Scene } from '../domain/scene-game';
import { gameCatalog } from '../domain/games';

/** Pointer capture keeps holds local; releasing or leaving the page cannot leave a paddle held. */
export function useGamePointer(enabled: boolean, scene: Scene, fire: (action: Action) => void) {
  const current = useRef({ enabled, fire });
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    current.current = { enabled, fire };
  });
  function release() {
    if (timer.current !== null) clearInterval(timer.current);
    timer.current = null;
  }
  useEffect(() => {
    if (!enabled) release();
  }, [enabled]);
  useEffect(() => {
    window.addEventListener('blur', release);
    document.addEventListener('visibilitychange', release);
    return () => {
      release();
      window.removeEventListener('blur', release);
      document.removeEventListener('visibilitychange', release);
    };
  }, []);
  return (action: Action) => ({
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0 || !current.current.enabled) return;
      event.preventDefault();
      release();
      event.currentTarget.setPointerCapture(event.pointerId);
      current.current.fire(action);
      if (scene === 'drum' || (scene === 'runner' && action === 'act')) return;
      timer.current = setInterval(() => {
        if (current.current.enabled) current.current.fire(action);
        else release();
      }, gameCatalog.input.repeatMilliseconds);
    },
    onPointerUp: release,
    onPointerCancel: release,
    onLostPointerCapture: release,
    onClick: (event: React.MouseEvent<HTMLButtonElement>) => {
      if (event.detail === 0 && current.current.enabled) current.current.fire(action);
    },
  });
}
