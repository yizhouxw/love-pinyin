import { spawn } from 'node:child_process';
import { mkdtemp, rm, readFile, mkdir, copyFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test as base } from '@playwright/test';

// One isolated real server/database per test; browser actions create all data.
export const test = base.extend<{ reviewUrl: string }>({
  // Playwright requires a destructured fixture parameter even without dependencies.
  // eslint-disable-next-line no-empty-pattern
  reviewUrl: async ({}, use) => {
    const directory = await mkdtemp(join(tmpdir(), 'love-pinyin-review-'));
    const catalog = JSON.parse(await readFile('private/audio-review/catalog.json', 'utf8'));
    const source = catalog.sources[0];
    await mkdir(join(directory, 'sources'));
    await copyFile(join('private/audio-review', source.file), join(directory, source.file));
    await writeFile(
      join(directory, 'catalog.json'),
      JSON.stringify({
        version: 1,
        sources: [source],
        candidates: catalog.candidates.filter(
          (row: { sourceId: string }) => row.sourceId === source.id,
        ),
      }),
    );
    const child = spawn(
      'uv',
      [
        'run',
        '--locked',
        'python',
        '-m',
        'scripts.audio_review',
        '--work',
        directory,
        '--port',
        '0',
      ],
      {
        env: { ...process.env, LOVE_PINYIN_STANDARD_AUDIO_DIR: join(directory, 'standard') },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
    const stopped = new Promise<void>((resolve) => child.once('close', () => resolve()));
    let output = '';
    try {
      const url = await new Promise<string>((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error(`Server startup timed out: ${output}`)),
          20_000,
        );
        const collect = (chunk: Buffer) => {
          output += chunk.toString();
          const address = output.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/)?.[1];
          if (address) {
            clearTimeout(timer);
            resolve(address);
          }
        };
        child.stdout.on('data', collect);
        child.stderr.on('data', collect);
        child.once('error', (error) => {
          clearTimeout(timer);
          reject(error);
        });
        child.once('close', () => {
          clearTimeout(timer);
          reject(new Error(`Server exited: ${output}`));
        });
      });
      await use(url);
    } finally {
      child.kill('SIGTERM');
      const killTimer = setTimeout(() => child.kill('SIGKILL'), 5_000);
      await stopped;
      clearTimeout(killTimer);
      await rm(directory, { recursive: true });
    }
  },
});
