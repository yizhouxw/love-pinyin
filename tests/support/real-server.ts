import { execFileSync, spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test as base } from '@playwright/test';

// One isolated server/database per test. Browser actions create household data;
// seedReview only supplies explicitly requested historical due-state for review tests.
export const test = base.extend<{
  appUrl: string;
  dataDirectory: string;
  seedReview: (knowledgeId: string) => Promise<void>;
  selectedPinyinSource: boolean;
  serverControl: { url: string; stop: () => Promise<void>; start: () => Promise<void> };
}>({
  selectedPinyinSource: [false, { option: true }],
  // eslint-disable-next-line no-empty-pattern
  dataDirectory: async ({}, use) => {
    const directory = await mkdtemp(join(tmpdir(), 'love-pinyin-live-'));
    try {
      await use(directory);
    } finally {
      await rm(directory, { recursive: true });
    }
  },
  seedReview: async ({ dataDirectory }, use) => {
    await use(async (knowledgeId) => {
      execFileSync(
        'uv',
        [
          'run',
          '--locked',
          'python',
          '-c',
          `
import sys
from datetime import date, timedelta
from server import storage
from server.content import map_by_id
k = map_by_id('knowledgeItems')[sys.argv[1]]
with storage.transaction() as db:
    row = db.execute('SELECT id FROM household').fetchone()
    assert row, 'Pair the test household first'
    db.execute('UPDATE household SET selected_lesson_id=? WHERE id=?', (k['lessonId'], row['id']))
    db.execute('INSERT OR REPLACE INTO review_plans(household_id,knowledge_id,stage,due_date,updated_at) VALUES(?,?,?,?,?)', (row['id'], k['id'], 0, (date.today()-timedelta(days=1)).isoformat(), storage.now_iso()))
`,
          knowledgeId,
        ],
        { env: { ...process.env, LOVE_PINYIN_DATA_DIR: dataDirectory } },
      );
    });
  },
  appUrl: async ({ serverControl }, use) => {
    await use(serverControl.url);
  },
  serverControl: async ({ dataDirectory: directory, selectedPinyinSource }, use) => {
    let child: ReturnType<typeof spawn> | undefined;
    let stopped = Promise.resolve();
    let url = '';
    async function stop() {
      if (!child) return;
      const current = child;
      current.kill('SIGTERM');
      const killTimer = setTimeout(() => current.kill('SIGKILL'), 5_000);
      await stopped;
      clearTimeout(killTimer);
      child = undefined;
    }
    async function start() {
      if (child) throw new Error('Test server is already started');
      child = spawn(
        'uv',
        [
          'run',
          '--locked',
          'uvicorn',
          'server.main:app',
          '--host',
          '127.0.0.1',
          '--port',
          url ? new URL(url).port : '0',
          '--no-access-log',
        ],
        {
          env: {
            ...process.env,
            LOVE_PINYIN_DATA_DIR: directory,
            LOVE_PINYIN_SOURCE_AUDIO_DIR: selectedPinyinSource
              ? join(process.cwd(), 'private/pinyinsound')
              : join(directory, 'source-audio'),
          },
          stdio: ['ignore', 'pipe', 'pipe'],
        },
      );
      const current = child;
      stopped = new Promise<void>((resolve) => current.once('close', () => resolve()));
      let output = '';
      url = await new Promise<string>((resolve, reject) => {
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
        current.stdout!.on('data', collect);
        current.stderr!.on('data', collect);
        current.once('error', (error) => {
          clearTimeout(timer);
          reject(error);
        });
        current.once('close', () => {
          clearTimeout(timer);
          reject(new Error(`Server exited: ${output}`));
        });
      });
    }
    try {
      await start();
      await use({ url, stop, start });
    } finally {
      await stop();
    }
  },
});
