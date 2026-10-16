import { spawn } from 'node:child_process';
import { createPrivateKey, X509Certificate } from 'node:crypto';
import { createSecureContext } from 'node:tls';
import { isIP } from 'node:net';
import { networkInterfaces } from 'node:os';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { accessSync, constants, readFileSync, statSync } from 'node:fs';

export function resolveLanConfig(env, interfaces) {
  const host = env.LOVE_PINYIN_BIND_IP;
  if (!host || isIP(host) !== 4 || host.startsWith('127.') || host === '0.0.0.0') {
    throw new Error('Set LOVE_PINYIN_BIND_IP to a non-loopback IPv4 address assigned to this Mac.');
  }

  const localAddresses = Object.values(interfaces)
    .flatMap((entries) => entries ?? [])
    .filter(
      (entry) =>
        !entry.internal &&
        (entry.family === 'IPv4' || entry.family === 4) &&
        isIP(entry.address) === 4,
    )
    .map((entry) => entry.address);
  if (!localAddresses.includes(host)) {
    throw new Error(`LOVE_PINYIN_BIND_IP ${host} is not assigned to a local network interface.`);
  }

  const cert = env.LOVE_PINYIN_TLS_CERT;
  const key = env.LOVE_PINYIN_TLS_KEY;
  if (!cert || !key) throw new Error('Set LOVE_PINYIN_TLS_CERT and LOVE_PINYIN_TLS_KEY.');

  const port = Number(env.LOVE_PINYIN_PORT ?? '8443');
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new Error('LOVE_PINYIN_PORT must be an integer from 1024 to 65535.');
  }

  return { host, port, cert: resolve(cert), key: resolve(key) };
}

function assertReadableFile(path, label) {
  try {
    accessSync(path, constants.R_OK);
    if (!statSync(path).isFile()) throw new Error('not a file');
  } catch {
    throw new Error(`${label} must name an existing readable file: ${path}`);
  }
}

export function validateLanTls(config, now = new Date()) {
  assertReadableFile(config.cert, 'TLS certificate');
  assertReadableFile(config.key, 'TLS private key');
  const cert = readFileSync(config.cert);
  const key = readFileSync(config.key);
  let certificate;
  let privateKey;
  try {
    certificate = new X509Certificate(cert);
  } catch {
    throw new Error('TLS certificate is not a valid PEM certificate.');
  }
  if (now < certificate.validFromDate) {
    throw new Error('TLS certificate is not yet valid. Check the Mac clock and certificate dates.');
  }
  if (now >= certificate.validToDate) {
    throw new Error('TLS certificate has expired. Renew it before starting the LAN server.');
  }
  if (!certificate.checkIP(config.host)) {
    throw new Error(
      `TLS certificate must include IP SAN ${config.host}. Regenerate it for this Mac address.`,
    );
  }
  try {
    privateKey = createPrivateKey(key);
  } catch {
    throw new Error('TLS private key must be a valid unencrypted PEM private key.');
  }
  if (!certificate.checkPrivateKey(privateKey)) {
    throw new Error('TLS private key does not match the certificate. Select the matching pair.');
  }
  try {
    createSecureContext({ cert, key });
  } catch {
    throw new Error(
      'TLS certificate and key cannot create a secure context. Check their PEM encoding and TLS compatibility.',
    );
  }
  return { expiresAt: certificate.validToDate.toISOString() };
}

function main() {
  let config;
  try {
    if (process.argv.slice(2).some((arg) => arg !== '--check')) {
      throw new Error('Usage: node scripts/serve-lan.mjs [--check]');
    }
    config = resolveLanConfig(process.env, networkInterfaces());
    const tls = validateLanTls(config);
    if (process.argv.includes('--check')) {
      process.stdout.write(
        `LAN configuration checked: https://${config.host}:${config.port}\n` +
          `Certificate expires: ${tls.expiresAt}\n` +
          'No server started. Client certificate trust and device connectivity still require verification.\n',
      );
      return;
    }
  } catch (error) {
    process.stderr.write(`LAN server not started: ${error.message}\n`);
    process.exitCode = 2;
    return;
  }

  const args = [
    'run',
    '--locked',
    'uvicorn',
    'server.main:app',
    '--host',
    config.host,
    '--port',
    String(config.port),
    '--ssl-certfile',
    config.cert,
    '--ssl-keyfile',
    config.key,
    '--no-access-log',
    '--no-proxy-headers',
  ];
  const server = spawn('uv', args, { stdio: 'inherit' });
  let stopping = false;
  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.once(signal, () => {
      stopping = true;
      server.kill(signal);
    });
  }
  server.once('error', (error) => {
    process.stderr.write(`Could not start the local API server: ${error.message}\n`);
    process.exitCode = 1;
  });
  server.once('exit', (code, signal) => {
    process.exitCode = stopping && signal ? (signal === 'SIGINT' ? 130 : 143) : (code ?? 1);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main();
