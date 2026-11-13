import { chromium, expect } from '@playwright/test';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { playScene } from '../../tests/support/scene-actions.ts';

const adb = process.env.ANDROID_HOME
  ? `${process.env.ANDROID_HOME}/platform-tools/adb`
  : `${process.env.HOME}/Library/Android/sdk/platform-tools/adb`;
const serial = process.env.ANDROID_SERIAL;
if (!serial) throw new Error('Set ANDROID_SERIAL to the authorized test device');
const run = (...args) => execFileSync(adb, ['-s', serial, ...args], { encoding: 'utf8' }).trim();
const pid = run('shell', 'pidof', 'org.lovepinyin.android');
if (!/^\d+$/.test(pid))
  throw new Error('Start the debuggable app with an isolated verificationId first');
run('forward', 'tcp:9237', `localabstract:webview_devtools_remote_${pid}`);
const browser = await chromium.connectOverCDP('http://127.0.0.1:9237');
const page = browser
  .contexts()[0]
  .pages()
  .find((p) => p.url().startsWith('https://app.lovepinyin.invalid'));
if (!page) throw new Error('Installed Android WebView is unavailable');
const out = 'build/android/verification';
mkdirSync(out, { recursive: true });
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
const checks = [];
const shot = (name) =>
  writeFileSync(
    `${out}/${name}.png`,
    execFileSync(adb, ['-s', serial, 'exec-out', 'screencap', '-p'], {
      maxBuffer: 16 * 1024 * 1024,
    }),
  );
const content = JSON.parse(
  readFileSync('deploy/android/app/src/main/assets/pack/Data/classroom.json'),
);
const games = JSON.parse(readFileSync('content/games.json')).games;

async function bridge(operation, fields = {}) {
  return page.evaluate(
    async ({ operation, fields }) => {
      if (!window.__qaPending) {
        window.__qaPending = new Map();
        const previous = window.__lovePinyinAndroidReply;
        window.__lovePinyinAndroidReply = (reply) => {
          const handler = window.__qaPending.get(reply.requestId);
          if (handler) {
            window.__qaPending.delete(reply.requestId);
            handler(reply);
          } else previous?.(reply);
        };
      }
      const requestId = 'qa-' + crypto.randomUUID();
      return new Promise((resolve, reject) => {
        window.__qaPending.set(requestId, (reply) =>
          reply.error ? reject(new Error(reply.error)) : resolve(reply.result),
        );
        window.LovePinyinAndroid.postMessage(
          JSON.stringify({ ...fields, version: 1, requestId, operation }),
        );
      });
    },
    { operation, fields },
  );
}
const api = (path, method = 'GET', body = {}) =>
  bridge('classroom', { path, method, payload: JSON.stringify(body) });
async function home() {
  await expect(
    page
      .getByRole('button', {
        name: /保存并退出游戏|返回首页|返回小岛|回到学习|返回学习|家长管理|退出练习/,
      })
      .first(),
  ).toBeVisible({ timeout: 20000 });
  const exitGame = page.getByRole('button', { name: /保存并退出游戏/ });
  if (await exitGame.isVisible()) {
    await exitGame.click();
    await expect(page.locator('.scene-nav')).toHaveCount(0);
  }
  const back = page.getByRole('button', { name: /返回首页|返回小岛|回到学习|返回学习/ }).first();
  if (await back.isVisible()) await back.click();
  else if (await page.getByRole('button', { name: '退出练习', exact: true }).isVisible())
    await page.getByRole('button', { name: '退出练习', exact: true }).click();
  await expect(page.getByRole('button', { name: '家长管理', exact: true })).toBeVisible();
}
async function probe() {
  await page.evaluate(() => {
    if (window.__qaMedia) return;
    window.__qaMedia = [];
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function (...args) {
      const sample = {
        source: this.dataset.learningSource,
        started: false,
        ended: false,
        duration: 0,
        maxTime: 0,
      };
      window.__qaMedia.push(sample);
      this.addEventListener(
        'playing',
        () => {
          sample.started = true;
          sample.duration = this.duration;
          sample.source = this.dataset.learningSource;
        },
        { once: true },
      );
      this.addEventListener(
        'timeupdate',
        () => (sample.maxTime = Math.max(sample.maxTime, this.currentTime)),
      );
      this.addEventListener('ended', () => (sample.ended = true), { once: true });
      return play.apply(this, args);
    };
  });
}
async function played(button) {
  const count = await page.evaluate(() => window.__qaMedia.length);
  await button.click();
  await page.waitForFunction(
    (n) => window.__qaMedia.slice(n).some((s) => s.ended && s.duration > 0.1),
    count,
    { timeout: 30000 },
  );
}
try {
  await probe();
  const mode = process.argv[2] ?? 'reading';
  if (mode === 'reading') {
    await home();
    await page.getByRole('button', { name: /词语天天练/ }).click();
    await page.getByRole('button', { name: '词语拼读', exact: true }).click();
    await played(page.getByRole('button', { name: /^听读/ }).first());
    checks.push('word pronunciation media decoded, played and ended on device');
    await page.getByRole('button', { name: /选择课程/ }).click();
    await page.getByRole('button', { name: '选择金木水火土', exact: true }).click();
    await page.getByRole('button', { name: '词语听写', exact: true }).click();
    await expect(page.getByRole('button', { name: '揭晓答案', exact: true })).toBeVisible();
    await played(page.getByRole('button', { name: '🔊 听词语 / 重听', exact: true }));
    await page.getByRole('button', { name: '揭晓答案', exact: true }).click();
    await expect(page.getByRole('button', { name: '收起答案', exact: true })).toBeVisible();
    await page.getByRole('button', { name: '下一个', exact: true }).click();
    await expect(page.getByRole('button', { name: '揭晓答案', exact: true })).toBeVisible();
    checks.push('dictation plays, reveals, and hides next answer');
    await page.getByRole('button', { name: '拓展朗读', exact: true }).click();
    await played(page.getByRole('button', { name: '听第1段', exact: true }));
    await page.getByRole('button', { name: '隐藏短文', exact: true }).click();
    shot('reading-hidden');
    checks.push('passage audio and hidden reading');
    await home();
    await page.getByRole('button', { name: /天天练拼音/ }).click();
    writeFileSync(
      `${out}/daily-controls.json`,
      JSON.stringify(
        await page
          .getByRole('button')
          .evaluateAll((items) =>
            items.map((x) => ({ text: x.textContent, label: x.getAttribute('aria-label') })),
          ),
        null,
        2,
      ),
    );
    shot('daily');
    checks.push('daily practice opened with bundled content');
  } else if (mode === 'marks-save' || mode === 'marks-check') {
    if (mode === 'marks-save') {
      await home();
      await page.getByRole('button', { name: /词语天天练/ }).click();
      const mark = page.getByRole('button', { name: '这部分我练习过了', exact: true });
      if (await mark.isVisible()) await mark.click();
      await expect(page.getByRole('button', { name: '本部分已练习 ✓', exact: true })).toBeVisible();
      await home();
      await page.getByRole('button', { name: /天天练拼音/ }).click();
      await page.getByRole('button', { name: '开始第 1 份跟读', exact: true }).click();
      await played(page.getByRole('button', { name: /开始跟读/ }));
      await page.getByRole('button', { name: /读过了，下一条/ }).click();
    }
    const marks = await page.evaluate(() =>
      Object.fromEntries(
        ['word:original', 'daily:original'].map((key) => [
          key,
          JSON.parse(window.LovePinyinAndroid.practiceProgress(key, '')),
        ]),
      ),
    );
    for (const value of Object.values(marks)) {
      expect(value.error).toBeNull();
      expect(Object.keys(value.result).length).toBeGreaterThan(0);
    }
    if (mode === 'marks-save') writeFileSync(`${out}/saved-marks.json`, JSON.stringify(marks));
    else expect(marks).toEqual(JSON.parse(readFileSync(`${out}/saved-marks.json`)));
    checks.push(
      mode === 'marks-save'
        ? 'word and daily marks saved through visible controls'
        : 'word and daily marks survived actual force-stop and cold launch',
    );
  } else if (mode === 'rotation') {
    await home();
    const before = await api('/profiles/progress');
    try {
      run('shell', 'wm', 'user-rotation', 'lock', '1');
      await page.waitForFunction(() => innerWidth > innerHeight);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      shot('landscape');
    } finally {
      run('shell', 'wm', 'user-rotation', 'lock', '0');
    }
    await page.waitForFunction(() => innerHeight > innerWidth);
    expect((await api('/profiles/progress')).attemptCount).toBe(before.attemptCount);
    checks.push(
      'real landscape/portrait rotation preserves progress and has no horizontal overflow',
    );
  } else if (mode === 'audio') {
    await home();
    await page.getByText('查看全部课程', { exact: true }).click();
    await page.locator('button[data-lesson-id]').first().click();
    await page.getByRole('button', { name: /播放课程录音/ }).click();
    const slider = page.getByRole('slider', { name: '课程录音播放进度' });
    await expect(slider).toBeVisible();
    await expect.poll(() => slider.inputValue()).not.toBe('0');
    await page.getByRole('button', { name: /暂停课程录音/ }).click();
    await expect(page.getByRole('button', { name: /播放课程录音/ })).toBeVisible();
    await expect(slider).toBeEnabled();
    await slider.fill('10');
    await expect.poll(async () => Number(await slider.inputValue())).toBeGreaterThanOrEqual(9);
    await page.getByRole('button', { name: /播放课程录音/ }).click();
    run('shell', 'input', 'keyevent', 'KEYCODE_HOME');
    run('shell', 'am', 'start', '-n', 'org.lovepinyin.android/.MainActivity');
    await expect(page.getByRole('button', { name: /播放课程录音/ })).toBeVisible();
    shot('lesson-audio');
    checks.push('native lesson audio plays, pauses, seeks, and stays paused after background');
  } else if (mode === 'backup-export' || mode === 'backup-import') {
    await home();
    await page.getByRole('button', { name: '家长管理', exact: true }).click();
    const parentGate = page.getByRole('button', { name: '我是家长，继续', exact: true });
    if (await parentGate.isVisible()) await parentGate.click();
    const action = page.getByRole('button', {
      name: mode === 'backup-export' ? '导出学习备份' : '从 Android 备份恢复',
      exact: true,
    });
    await action.click();
    console.log('Opened Android system document picker');
    await browser.close();
    process.exit(0);
  } else if (mode === 'inspect') {
    console.log(await page.locator('body').innerText());
  } else if (mode === 'games') {
    await home();
    await api('/rest/complete', 'POST');
    const progress = await api('/profiles/progress');
    await api('/household/current-lesson', 'PUT', {
      lessonId: content.lessons.at(-1).id,
      expectedRevision: progress.revision,
    });
    await page.evaluate(
      (ids) =>
        ids.forEach((id) =>
          localStorage.setItem(
            `love-pinyin.scene.${id}`,
            JSON.stringify({ difficulty: 'gentle', speed: 'slow', taskCount: 3 }),
          ),
        ),
      games.map((g) => g.id),
    );
    await page.reload();
    await probe();
    await page.getByRole('button', { name: /进入游戏乐园|拼音游戏乐园/ }).click();
    for (const game of games) {
      await api('/rest/complete', 'POST');
      await page.reload();
      await probe();
      await page.getByRole('button', { name: `开始${game.title}` }).click();
      await expect(page.locator('.adventure-canvas')).toBeVisible({ timeout: 20000 });
      const session = await api('/sessions/current');
      shot(`game-${game.id}`);
      for (const [index, task] of session.tasks.entries()) {
        await expect(page.locator('.scene-nav')).toContainText(
          new RegExp(`任务 ${index + 1}\\s*/\\s*3`),
          { timeout: 25000 },
        );
        const question = content.eligible.find(
          (row) => row.exercise.id === task.exercise.id,
        ).exercise;
        await playScene(page, question.answer.optionId);
      }
      await expect(page.locator('.scene-nav')).toHaveCount(0, { timeout: 25000 });
      checks.push(`${game.id}: three real task answers completed through visible controls`);
      console.log(checks.at(-1));
      const finish = page.getByRole('button', { name: /完成|返回游戏乐园|回到游戏乐园/ }).first();
      if (await finish.isVisible()) await finish.click();
      if (await page.getByRole('button', { name: /进入游戏乐园|拼音游戏乐园/ }).isVisible())
        await page.getByRole('button', { name: /进入游戏乐园|拼音游戏乐园/ }).click();
    }
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  writeFileSync(
    `${out}/${mode}-results.json`,
    JSON.stringify({ checks, errors, audio: await page.evaluate(() => window.__qaMedia) }, null, 2),
  );
  console.log(JSON.stringify({ checks, errors }));
} catch (error) {
  try {
    shot('failure');
  } catch {
    /* Device may have disconnected. */
  }
  console.error(await page.locator('body').innerText());
  throw error;
} finally {
  await browser.close();
}
