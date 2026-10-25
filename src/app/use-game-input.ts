import { useEffect, useRef } from 'react';
import type { Action, Scene } from '../domain/scene-game';
import { gameCatalog } from '../domain/games';

/** Active-game keyboard adapter. Editing, dialogs and native button activation stay native. */
export function useGameInput({
  enabled,
  scene,
  onAction,
  onPause,
  focus,
}: {
  enabled: boolean;
  scene: Scene;
  onAction: (a: Action) => void;
  onPause: () => void;
  focus: () => void;
}) {
  const handlers = useRef({ enabled, onAction, onPause, focus });
  useEffect(() => {
    handlers.current = { enabled, onAction, onPause, focus };
  }, [enabled, onAction, onPause, focus]);
  useEffect(() => {
    const held = new Map<string, { action: Action; last: number }>();
    const clear = () => held.clear();
    const down = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        document.hidden ||
        event.ctrlKey ||
        event.altKey ||
        event.metaKey ||
        document.querySelector('dialog[open]')
      )
        return;
      if (
        target instanceof HTMLElement &&
        target.closest('input,textarea,select,[contenteditable="true"]')
      )
        return;
      if (gameCatalog.input.pause.includes(event.code)) {
        if (!event.repeat) {
          event.preventDefault();
          clear();
          handlers.current.onPause();
        }
        return;
      }
      const action = (['left', 'right', 'act', 'pass'] as const).find((a) =>
        gameCatalog.input[a].includes(event.code),
      );
      if (!action) return;
      // Space/Enter on a normal UI button remains an accessible button activation.
      if (
        event.code === 'Space' &&
        target instanceof HTMLElement &&
        target.closest('button,a,summary') &&
        !target.closest('.scene-controls')
      )
        return;
      event.preventDefault();
      if (!handlers.current.enabled || event.repeat) return;
      handlers.current.focus();
      const actual =
        scene === 'drum' && (action === 'left' || action === 'right') ? 'pass' : action;
      held.set(event.code, { action: actual, last: performance.now() });
      handlers.current.onAction(actual);
    };
    const up = (event: KeyboardEvent) => {
      held.delete(event.code);
    };
    const repeat = window.setInterval(() => {
      if (!handlers.current.enabled) {
        clear();
        return;
      }
      const now = performance.now();
      for (const value of held.values()) {
        if (scene === 'drum' || (scene === 'runner' && value.action === 'act')) continue;
        if (now - value.last >= gameCatalog.input.repeatMilliseconds) {
          value.last = now;
          handlers.current.onAction(value.action);
        }
      }
    }, 40);
    window.addEventListener('keydown', down, true);
    window.addEventListener('keyup', up, true);
    window.addEventListener('blur', clear);
    document.addEventListener('visibilitychange', clear);
    return () => {
      clear();
      window.clearInterval(repeat);
      window.removeEventListener('keydown', down, true);
      window.removeEventListener('keyup', up, true);
      window.removeEventListener('blur', clear);
      document.removeEventListener('visibilitychange', clear);
    };
  }, [scene]);
}
