import { readFile } from 'node:fs/promises';
import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test('VOICE-09: Qwen Chinese voices all decode through the real local API', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(120000);
  const manifest = JSON.parse(await readFile('resources/audio/manifest.json', 'utf8')) as {
    assets: {
      id: string;
      file: string;
      purpose: string;
      sourceType: string;
      voice?: string;
      speaker?: string;
      modelRevision?: string;
    }[];
  };
  const narration = manifest.assets.filter((asset) => asset.purpose === 'chinese-instruction');
  expect(narration).toHaveLength(1270);
  expect(narration.every((asset) => asset.sourceType === 'local-open-tts')).toBe(true);
  expect(narration.every((asset) => asset.voice === 'Qwen3-TTS-12Hz-1.7B-CustomVoice')).toBe(true);
  expect(narration.every((asset) => asset.speaker === 'Serena')).toBe(true);
  expect(
    narration.every((asset) => asset.modelRevision === '52f4770fd9726457eae3d3b6aa92047a25a10776'),
  ).toBe(true);
  const ids = [...new Map(narration.map((asset) => [asset.file, asset.id])).values()];
  expect(ids).toHaveLength(436);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  const decoded = await page.evaluate(async (ids) => {
    const context = new AudioContext();
    try {
      for (const id of ids) {
        const response = await fetch(`/api/v1/guest/voice/${id}`);
        if (!response.ok) throw new Error(`missing:${id}`);
        const voice = await context.decodeAudioData(await response.arrayBuffer());
        if (voice.duration < 0.1 || voice.numberOfChannels !== 1) throw new Error(`invalid:${id}`);
      }
      return ids.length;
    } finally {
      await context.close();
    }
  }, ids);
  expect(decoded).toBe(436);
  const intro = page.waitForResponse(
    (response) => response.url().endsWith('/voice/daily-ui-intro') && response.ok(),
  );
  await page.getByRole('button', { name: '听每日跟读说明', exact: true }).click();
  await intro;
  await expect(page.getByRole('button', { name: '停止听每日跟读说明', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await expect(page.getByRole('heading', { name: '天天练拼音', exact: true })).toBeVisible();
});
