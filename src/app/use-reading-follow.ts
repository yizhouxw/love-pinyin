import { useLayoutEffect, type RefObject } from 'react';

/** Reveal within this pane only; never scroll ancestors or steal keyboard focus. */
export function revealReadingItem(pane: HTMLElement, target: HTMLElement) {
  const bounds = pane.getBoundingClientRect();
  const item = target.getBoundingClientRect();
  const top = bounds.top + pane.clientTop + 8;
  const bottom = bounds.top + pane.clientTop + pane.clientHeight - 8;
  if (item.height > bottom - top || item.top < top) pane.scrollTop += item.top - top;
  else if (item.bottom > bottom) pane.scrollTop += item.bottom - bottom;
}

export function useReadingFollow(
  ref: RefObject<HTMLElement | null>,
  key: string,
  selector: string,
) {
  useLayoutEffect(() => {
    const pane = ref.current;
    if (!pane) return;
    const follow = () => {
      const target = pane.querySelector<HTMLElement>(selector);
      if (target) revealReadingItem(pane, target);
    };
    follow();
    const observer = new ResizeObserver(follow);
    observer.observe(pane);
    return () => observer.disconnect();
  }, [ref, key, selector]);
}
