import type { Page } from '@playwright/test';
export type MediaEvent = { source: string; type: 'start' | 'end'; time: number };
declare global {
  interface Window {
    readingMediaEvents: MediaEvent[];
  }
}

/** Observe native playback, including a Blob's original allowlisted learning URL. */
export async function observeReadingMedia(page: Page) {
  await page.addInitScript(() => {
    window.readingMediaEvents = [];
    const calls = new WeakMap<HTMLMediaElement, number>();
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      const call = (calls.get(this) ?? 0) + 1;
      calls.set(this, call);
      const source = this.getAttribute('data-learning-source') || this.src;
      if (source && !source.startsWith('blob:')) {
        for (const [event, type] of [
          ['playing', 'start'],
          ['ended', 'end'],
        ] as const) {
          this.addEventListener(
            event,
            () => {
              if (calls.get(this) === call)
                window.readingMediaEvents.push({ source, type, time: performance.now() });
            },
            { once: true },
          );
        }
      }
      return play.call(this);
    };
  });
}
export function playedReading(page: Page, kind: 'voice' | 'daily-audio') {
  return page.evaluate(
    (kind) =>
      window.readingMediaEvents
        .filter((event) => event.type === 'start' && event.source.includes(`/${kind}/`))
        .map((event) => event.source.split('/').at(-1)!),
    kind,
  );
}
export function clearReadingMedia(page: Page) {
  return page.evaluate(() => {
    window.readingMediaEvents = [];
  });
}
