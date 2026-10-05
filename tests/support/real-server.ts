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
  appUrl: async ({ dataDirectory: directory, selectedPinyinSource }, use) => {
    const child = spawn(
      'uv',
      ['run', '--locked', 'uvicorn', 'server.main:app', '--host', '127.0.0.1', '--port', '0'],
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
    }
  },
});
