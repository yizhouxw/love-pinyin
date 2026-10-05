import { execFileSync } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test('DISASTER-01: online SQLite backup restores pairing and saved learning after corruption', async ({
  page,
  appUrl,
  dataDirectory,
  serverControl,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const python = (code: string) =>
    execFileSync('uv', ['run', '--locked', 'python', '-c', code], {
      env: { ...process.env, LOVE_PINYIN_DATA_DIR: dataDirectory },
      encoding: 'utf8',
    }).trim();
  const exportState = async () => {
    const response = await page.request.get(`${appUrl}/api/v1/profiles/export`);
    expect(response.ok()).toBe(true);
    return response.json();
  };
  const answer = async () => {
    const choice = page.getByRole('group', { name: '选择答案' }).getByRole('button').first();
    await expect(choice).toBeEnabled({ timeout: 15_000 });
    await choice.press('Enter');
    await expect(page.locator('.feedback')).toBeVisible();
  };
  const exitRound = async () => {
    await page.getByRole('button', { name: '退出练习' }).click();
    // Finish includes a bootstrap refresh; wait before stopping or reloading the server page.
    await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeEnabled();
  };

  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await answer();
  await exitRound();
  const saved = await exportState();
  expect(saved.attempts).toHaveLength(1);
  // Explicit destination keeps the real backup implementation inside this test's directory.
  const backupPath = python(`
from server import storage
from server.backup import backup_database
import sqlite3
p = backup_database(storage.DATA_DIR / 'backups')
assert p.stat().st_mode & 0o777 == 0o600
assert p.parent.stat().st_mode & 0o777 == 0o700
with sqlite3.connect(f'file:{p}?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1
print(p)
`);
  expect(realpathSync(dirname(backupPath))).toBe(realpathSync(join(dataDirectory, 'backups')));

  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await answer();
  await exitRound();
  expect((await exportState()).attempts).toHaveLength(2);
  await serverControl.stop();
  await expect(fetch(`${appUrl}/api/v1/health`)).rejects.toThrow();

  // Rehearse the documented stopped-service procedure, including preserving damaged files.
  const recovery = JSON.parse(
    python(`
import hashlib, json, os, shutil, sqlite3
from server import storage
root = storage.DATA_DIR
live = storage.DATABASE_PATH
backup = next((root / 'backups').glob('*.sqlite3'))
staged = live.with_suffix('.sqlite3.restore')
original_digest = hashlib.sha256(live.read_bytes()).hexdigest()
bad = root / 'damaged-backup.sqlite3'
bad.write_bytes(b'not a SQLite backup')
shutil.copyfile(bad, staged)
os.chmod(staged, 0o600)
try:
    with sqlite3.connect(f'file:{staged}?mode=ro', uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
except sqlite3.DatabaseError:
    staged.unlink()
else:
    raise AssertionError('Damaged candidate was not rejected')
assert hashlib.sha256(live.read_bytes()).hexdigest() == original_digest
# Fault injection is confined to the disposable database after the process stopped.
live.write_bytes(b'disaster drill: damaged household database')
shutil.copyfile(backup, staged)
os.chmod(staged, 0o600)
with sqlite3.connect(f'file:{staged}?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 5
archive = root / 'before-restore'
archive.mkdir(mode=0o700)
for suffix in ('', '-wal', '-shm'):
    path = root / (live.name + suffix)
    if path.exists():
        path.rename(archive / path.name)
assert (archive / live.name).read_bytes().startswith(b'disaster drill:')
assert not (root / (live.name + '-wal')).exists()
assert not (root / (live.name + '-shm')).exists()
with staged.open('r+b') as f:
    os.fsync(f.fileno())
os.replace(staged, live)
assert live.stat().st_mode & 0o777 == 0o600
print(json.dumps({'badBackupRejected': True, 'damagedDatabasePreserved': True,
                  'atomicRestoreComplete': True}))
`),
  );
  expect(recovery).toEqual({
    badBackupRejected: true,
    damagedDatabasePreserved: true,
    atomicRestoreComplete: true,
  });

  await serverControl.start();
  await page.reload();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  const restored = await exportState();
  for (const field of [
    'profile',
    'attempts',
    'sessions',
    'exerciseInstances',
    'skippedInstances',
    'reviewPlans',
  ])
    expect(restored[field]).toEqual(saved[field]);
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await answer();
  await exitRound();
  const continued = await exportState();
  expect(continued.attempts).toHaveLength(2);
  expect(continued.attempts.find((row: { id: string }) => row.id === saved.attempts[0].id)).toEqual(
    saved.attempts[0],
  );
  await page.reload();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeEnabled();
  expect((await exportState()).attempts).toEqual(continued.attempts);
  expect(errors).toEqual([]);
});
