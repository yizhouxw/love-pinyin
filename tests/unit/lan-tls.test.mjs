import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { execFileSync, spawnSync } from 'node:child_process';
import { generateKeyPairSync, X509Certificate } from 'node:crypto';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { networkInterfaces, tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { validateLanTls } from '../../scripts/serve-lan.mjs';

const localHost = Object.values(networkInterfaces())
  .flatMap((rows) => rows ?? [])
  .find((row) => row.family === 'IPv4' && !row.internal)?.address;
const host = localHost ?? '192.168.1.20';
let directory;
let config;
let certificate;
let env;

beforeAll(() => {
  directory = mkdtempSync(join(tmpdir(), 'love-pinyin-tls-'));
  config = { host, cert: join(directory, 'lan.pem'), key: join(directory, 'lan-key.pem') };
  execFileSync(
    'openssl',
    [
      'req',
      '-x509',
      '-newkey',
      'rsa:2048',
      '-nodes',
      '-days',
      '2',
      '-subj',
      '/CN=Love Pinyin temporary test',
      '-addext',
      `subjectAltName=IP:${host}`,
      '-keyout',
      config.key,
      '-out',
      config.cert,
    ],
    { stdio: 'pipe' },
  );
  certificate = new X509Certificate(readFileSync(config.cert));
  env = {
    ...process.env,
    HOME: directory,
    LOVE_PINYIN_BIND_IP: host,
    LOVE_PINYIN_TLS_CERT: config.cert,
    LOVE_PINYIN_TLS_KEY: config.key,
  };
});
afterAll(() => {
  if (directory) rmSync(directory, { recursive: true, force: true });
});

describe('LAN TLS preflight with real temporary PEM files', () => {
  it('accepts matching certificate, private key, IP SAN and current validity', () => {
    expect(validateLanTls(config)).toEqual({ expiresAt: certificate.validToDate.toISOString() });
  });

  it('rejects expired and not-yet-valid certificates', () => {
    expect(() => validateLanTls(config, certificate.validToDate)).toThrow(/expired/u);
    expect(() => validateLanTls(config, new Date(certificate.validFromDate.getTime() - 1))).toThrow(
      /not yet valid/u,
    );
  });

  it('rejects an IP absent from the certificate SAN', () => {
    expect(() => validateLanTls({ ...config, host: '192.0.2.123' })).toThrow(/IP SAN 192.0.2.123/u);
  });

  it('rejects a different real private key', () => {
    const key = join(directory, 'wrong-key.pem');
    const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
    writeFileSync(key, privateKey.export({ type: 'pkcs8', format: 'pem' }), { mode: 0o600 });
    expect(() => validateLanTls({ ...config, key })).toThrow(/does not match/u);
  });

  it('rejects encrypted keys without prompting or logging their content', () => {
    const key = join(directory, 'encrypted-key.pem');
    const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
    writeFileSync(
      key,
      privateKey.export({
        type: 'pkcs8',
        format: 'pem',
        cipher: 'aes-256-cbc',
        passphrase: 'temporary-test-only',
      }),
      { mode: 0o600 },
    );
    expect(() => validateLanTls({ ...config, key })).toThrow(/unencrypted PEM/u);
  });

  it('rejects missing, directory and malformed files with actionable errors', () => {
    expect(() => validateLanTls({ ...config, cert: join(directory, 'missing') })).toThrow(
      /readable file/u,
    );
    expect(() => validateLanTls({ ...config, key: directory })).toThrow(/readable file/u);
    const invalid = join(directory, 'invalid.pem');
    writeFileSync(invalid, 'do-not-echo-secret-material', { mode: 0o600 });
    expect(() => validateLanTls({ ...config, cert: invalid })).toThrow(
      'TLS certificate is not a valid PEM certificate.',
    );
    expect(() => validateLanTls({ ...config, key: invalid })).toThrow(
      'TLS private key must be a valid unencrypted PEM private key.',
    );
  });

  it.skipIf(!localHost)(
    'checks deployment via CLI without starting a process or changing trust',
    () => {
      const result = spawnSync(process.execPath, ['scripts/serve-lan.mjs', '--check'], {
        env,
        encoding: 'utf8',
        timeout: 5000,
      });
      expect(result.error).toBeUndefined();
      expect(result.status).toBe(0);
      expect(result.stdout).toContain(`https://${host}:8443`);
      expect(result.stdout).toContain('No server started. Client certificate trust');
    },
  );

  it.skipIf(!localHost)('invalid normal startup exits before attempting to spawn uv', () => {
    const bin = join(directory, 'bin');
    mkdirSync(bin);
    const marker = join(directory, 'spawned-uv');
    writeFileSync(join(bin, 'uv'), '#!/bin/sh\nprintf started > "$HOME/spawned-uv"\n', {
      mode: 0o700,
    });
    const result = spawnSync(process.execPath, ['scripts/serve-lan.mjs'], {
      env: { ...env, PATH: bin, LOVE_PINYIN_TLS_KEY: config.cert },
      encoding: 'utf8',
      timeout: 5000,
    });
    expect(result.status).toBe(2);
    expect(result.stderr).toContain('unencrypted PEM private key');
    expect(result.stderr).not.toContain('BEGIN CERTIFICATE');
    expect(existsSync(marker)).toBe(false);
  });

  it.skipIf(!localHost || process.platform !== 'darwin')(
    'failed installation leaves the existing LaunchAgent untouched',
    () => {
      const agents = join(directory, 'Library', 'LaunchAgents');
      mkdirSync(agents, { recursive: true });
      const plist = join(agents, 'com.lovepinyin.server.plist');
      writeFileSync(plist, 'existing-service-preserved', { mode: 0o600 });
      const result = spawnSync(process.execPath, ['scripts/launch-agent.mjs', 'install'], {
        env: { ...env, LOVE_PINYIN_TLS_KEY: config.cert },
        encoding: 'utf8',
        timeout: 5000,
      });
      expect(result.status).toBe(1);
      expect(result.stderr).toContain('unencrypted PEM private key');
      expect(readFileSync(plist, 'utf8')).toBe('existing-service-preserved');
      expect(resolve(plist).startsWith(directory)).toBe(true);
    },
  );
});
