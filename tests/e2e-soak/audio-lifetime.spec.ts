import { optionById } from '../support/options';
import { writeFile } from 'node:fs/promises';
import { platform, release } from 'node:os';
import { expect } from '@playwright/test';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import { test } from '../support/real-server';

type MediaSample = {
  mediaStates: {
    src: string | null;
    currentSrc: string;
    readyState: number;
    networkState: number;
    paused: boolean;
  }[];
  trackedMedia: number;
  loadedMedia: number;
  playingMedia: number;
  openContexts: number;
  blobUrls: number;
  plays: number;
  standardPlays: number;
  latencies: { standard: boolean; ms: number }[];
};
declare global {
  interface Window {
    soakSample: () => MediaSample;
  }
}

test.use({ selectedPinyinSource: true });

test('SOAK-01: sustained real learning releases media and records playback latency', async ({
  page,
  browser,
  browserName,
  appUrl,
}, info) => {
  const seconds = Number(process.env.LOVE_PINYIN_SOAK_SECONDS ?? 1200);
  expect(Number.isInteger(seconds) && seconds >= 30 && seconds <= 1500).toBe(true);
  const errors: string[] = [];
  const external: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (request.url().startsWith('http') && new URL(request.url()).origin !== appUrl)
      external.push(request.url());
  });
  await page.addInitScript(() => {
    const media = new Map<number, WeakRef<HTMLMediaElement>>();
    const ids = new WeakMap<HTMLMediaElement, number>();
    const pending = new WeakMap<HTMLMediaElement, () => void>();
    const contexts: WeakRef<AudioContext>[] = [];
    const blobs = new Set<string>();
    const latencies: { standard: boolean; ms: number }[] = [];
    let sequence = 0;
    let plays = 0;
    let standardPlays = 0;
    const nativePlay = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      pending.get(this)?.();
      if (!ids.has(this)) {
        ids.set(this, ++sequence);
        media.set(sequence, new WeakRef(this));
      }
      const start = performance.now();
      const standard = new URL(this.src, location.href).pathname.startsWith('/api/v1/audio/');
      plays++;
      if (standard) standardPlays++;
      const playing = () => {
        latencies.push({ standard, ms: performance.now() - start });
        clean();
      };
      const emptied = () => {
        // Initial source selection can emit emptied after play(); it is not a cancellation.
        if (!this.getAttribute('src')) clean();
      };
      const clean = () => {
        this.removeEventListener('playing', playing);
        this.removeEventListener('emptied', emptied);
        this.removeEventListener('error', clean);
        if (pending.get(this) === clean) pending.delete(this);
      };
      pending.set(this, clean);
      this.addEventListener('playing', playing, { once: true });
      this.addEventListener('emptied', emptied);
      this.addEventListener('error', clean, { once: true });
      try {
        const result = nativePlay.call(this);
        void result.catch(clean);
        return result;
      } catch (error) {
        clean();
        throw error;
      }
    };
    window.AudioContext = new Proxy(window.AudioContext, {
      construct(target, args) {
        const context = Reflect.construct(target, args) as AudioContext;
        contexts.push(new WeakRef(context));
        return context;
      },
    });
    const create = URL.createObjectURL;
    const revoke = URL.revokeObjectURL;
    URL.createObjectURL = (value) => {
      const url = create(value);
      blobs.add(url);
      return url;
    };
    URL.revokeObjectURL = (url) => {
      blobs.delete(url);
      revoke(url);
    };
    window.soakSample = () => {
      const mediaStates: MediaSample['mediaStates'] = [];
      let loadedMedia = 0;
      let playingMedia = 0;
      for (const [id, ref] of media) {
        const audio = ref.deref();
        if (!audio) media.delete(id);
        else {
          mediaStates.push({
            src: audio.getAttribute('src'),
            currentSrc: audio.currentSrc,
            readyState: audio.readyState,
            networkState: audio.networkState,
            paused: audio.paused,
          });
          // currentSrc may retain the previous URL after load() resets to NETWORK_EMPTY.
          if (audio.getAttribute('src') || audio.readyState !== 0 || audio.networkState !== 0)
            loadedMedia++;
          if (!audio.paused && !audio.ended) playingMedia++;
        }
      }
      return {
        mediaStates,
        trackedMedia: media.size,
        loadedMedia,
        playingMedia,
        openContexts: contexts.filter((ref) => {
          const context = ref.deref();
          return context && context.state !== 'closed';
        }).length,
        blobUrls: blobs.size,
        plays,
        standardPlays,
        latencies: [...latencies],
      };
    };
  });
  const cdp = browserName === 'chromium' ? await page.context().newCDPSession(page) : null;
  await cdp?.send('Performance.enable');
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeEnabled();
  const startedAt = Date.now();
  let completed = false;
  let rounds = 0;
  let answers = 0;
  const transitions: number[] = [];
  const samples: Array<Record<string, unknown>> = [];
  try {
    do {
      const restBeforeLesson = page.getByRole('button', {
        name: '休息好了，继续学习',
        exact: true,
      });
      if (await restBeforeLesson.isVisible()) await restBeforeLesson.click();
      await expect(page.getByRole('button', { name: '开始今天的练习', exact: true })).toBeEnabled();
      const lesson = curriculum.lessons[rounds % curriculum.lessons.length]!;
      await page.getByRole('button', { name: '家长管理' }).click();
      await page.getByRole('button', { name: '我是家长，继续' }).click();
      await page.getByRole('combobox').selectOption(lesson.id);
      await page.getByRole('button', { name: '保存', exact: true }).click();
      await expect(page.getByRole('button', { name: '保存', exact: true })).toBeEnabled();
      await page.getByRole('button', { name: '返回学习', exact: true }).click();
      const rest = page.getByRole('button', { name: '休息好了，继续学习', exact: true });
      if (await rest.isVisible()) await rest.click();
      const begun = page.waitForResponse(
        (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
        { timeout: 15_000 },
      );
      await page.getByRole('button', { name: '开始今天的练习' }).click();
      const session = await (await begun).json();
      const tasks = session.tasks as { exercise: { id: string } }[];
      for (const [index, task] of tasks.entries()) {
        const question = curriculum.exercises.find((q) => q.id === task.exercise.id)!;
        await expect(page.locator('.play-nav strong')).toHaveText(
          `第 ${index + 1} / ${tasks.length} 关`,
        );
        await expect(page.getByRole('button', { name: '听题目', exact: true })).toBeVisible({
          timeout: 20_000,
        });
        if (question.audioRef)
          await page.getByRole('button', { name: '听拼音', exact: true }).click();
        const choice = optionById(page, question.answer.optionId);
        await expect(choice).toBeEnabled({ timeout: 20_000 });
        await choice.click();
        if (question.type === 'blend-choice')
          await page.getByRole('button', { name: '确认拼读', exact: true }).click();
        await expect(page.locator('.feedback')).toContainText('答对啦');
        answers++;
        // Let real feedback finish as well, so the workload does not only abort every sound.
        await expect(page.getByRole('button', { name: '听结果', exact: true })).toBeVisible({
          timeout: 20_000,
        });
        const transition = Date.now();
        await page.getByRole('button', { name: '继续 →', exact: true }).click();
        if (index < tasks.length - 1) {
          await expect(page.locator('.play-nav strong')).toHaveText(
            `第 ${index + 2} / ${tasks.length} 关`,
          );
          transitions.push(Date.now() - transition);
        }
      }
      await expect(page.getByLabel('本次练习小结')).toBeVisible();
      await page.getByRole('button', { name: '回到小岛', exact: true }).click();
      // Finish refresh can replace a briefly rendered home with the two-round rest page.
      await expect(
        page
          .getByRole('button', { name: '开始今天的练习', exact: true })
          .or(page.getByRole('button', { name: '休息好了，继续学习', exact: true })),
      ).toBeEnabled();
      await expect
        .poll(
          async () => {
            const s = await page.evaluate(() => window.soakSample());
            return s.loadedMedia + s.playingMedia + s.openContexts + s.blobUrls;
          },
          { timeout: 20_000 },
        )
        .toBe(0);
      if (cdp) await cdp.send('HeapProfiler.collectGarbage');
      const media = await page.evaluate(() => window.soakSample());
      const heap = cdp ? await cdp.send('Performance.getMetrics') : null;
      const dom = cdp ? await cdp.send('Memory.getDOMCounters') : null;
      const counts = {
        trackedMedia: media.trackedMedia,
        loadedMedia: media.loadedMedia,
        playingMedia: media.playingMedia,
        openContexts: media.openContexts,
        blobUrls: media.blobUrls,
        plays: media.plays,
        standardPlays: media.standardPlays,
      };
      samples.push({
        elapsedMs: Date.now() - startedAt,
        rounds: ++rounds,
        answers,
        lesson: lesson.id,
        ...counts,
        heapBytesAfterGc: heap?.metrics.find((m) => m.name === 'JSHeapUsedSize')?.value ?? null,
        domAfterGc: dom,
      });
      console.log(
        `${info.project.name}: ${Math.round((Date.now() - startedAt) / 1000)}s, ${rounds} rounds, ${answers} answers, loaded media ${media.loadedMedia}`,
      );
      expect(errors).toEqual([]);
      expect(external).toEqual([]);
    } while (Date.now() - startedAt < seconds * 1000);
    const exported = await page.request.get(`${appUrl}/api/v1/profiles/export`);
    expect(exported.ok()).toBe(true);
    expect((await exported.json()).attempts).toHaveLength(answers);
    const finalMedia = await page.evaluate(() => window.soakSample());
    expect(finalMedia.standardPlays).toBeGreaterThan(0);
    expect(finalMedia.latencies.filter((sample) => sample.standard)).toHaveLength(
      finalMedia.standardPlays,
    );
    await page.screenshot({ path: info.outputPath('after-soak.png'), fullPage: true });
    completed = true;
  } finally {
    const media = await page.evaluate(() => window.soakSample());
    const report = {
      instrumentationVersion: 2,
      project: info.project.name,
      browser: browser.version(),
      os: `${platform()} ${release()}`,
      requestedSeconds: seconds,
      elapsedMs: Date.now() - startedAt,
      completed,
      qualifiesFor20MinuteRun: completed && seconds >= 1200 && Date.now() - startedAt >= 1_200_000,
      rounds,
      answers,
      errors,
      external,
      samples,
      playback: media,
      transitionMs: transitions,
      method:
        'Real UI/API/audio; concurrent isolated engine runs; play-to-playing event latency; Chrome heap/DOM sampled after explicit GC. Not hardware output latency or all native memory.',
    };
    await writeFile(info.outputPath('soak-report.json'), JSON.stringify(report, null, 2));
    await info.attach('soak-report', {
      body: JSON.stringify(report),
      contentType: 'application/json',
    });
    await cdp?.detach();
  }
});
