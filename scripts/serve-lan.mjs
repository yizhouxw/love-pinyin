import { spawn } from 'node:child_process';
import { isIP } from 'node:net';
import { networkInterfaces } from 'node:os';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { accessSync, constants, statSync } from 'node:fs';

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

function main() {
  let config;
  try {
    config = resolveLanConfig(process.env, networkInterfaces());
    assertReadableFile(config.cert, 'TLS certificate');
    assertReadableFile(config.key, 'TLS private key');
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
