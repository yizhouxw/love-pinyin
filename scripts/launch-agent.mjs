import { spawnSync } from 'node:child_process';
import {
  accessSync,
  chmodSync,
  constants,
  existsSync,
  mkdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { networkInterfaces } from 'node:os';
import { delimiter, dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolveLanConfig } from './serve-lan.mjs';

const label = 'com.lovepinyin.server';
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const serverScript = join(projectRoot, 'scripts', 'serve-lan.mjs');
const launchAgentsDirectory = join(process.env.HOME ?? '', 'Library', 'LaunchAgents');
const plistPath = join(launchAgentsDirectory, `${label}.plist`);

function xml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

export function buildLaunchAgentPlist({
  nodePath,
  scriptPath,
  workingDirectory,
  stdoutPath,
  stderrPath,
  env,
  pathValue,
}) {
  const keys = [
    ['HOME', env.HOME],
    ['PATH', pathValue],
    ['LOVE_PINYIN_BIND_IP', env.LOVE_PINYIN_BIND_IP],
    ['LOVE_PINYIN_PORT', env.LOVE_PINYIN_PORT ?? '8443'],
    ['LOVE_PINYIN_TLS_CERT', resolve(env.LOVE_PINYIN_TLS_CERT)],
    ['LOVE_PINYIN_TLS_KEY', resolve(env.LOVE_PINYIN_TLS_KEY)],
    ['UV_PYTHON_DOWNLOADS', 'never'],
  ];
  const environment = keys
    .map(([key, value]) => `        <key>${xml(key)}</key>\n        <string>${xml(value)}</string>`)
    .join('\n');
  const args = [nodePath, scriptPath]
    .map((value) => `      <string>${xml(value)}</string>`)
    .join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
${args}
  </array>
  <key>WorkingDirectory</key>
  <string>${xml(workingDirectory)}</string>
  <key>EnvironmentVariables</key>
  <dict>
${environment}
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>30</integer>
  <key>StandardOutPath</key>
  <string>${xml(stdoutPath)}</string>
  <key>StandardErrorPath</key>
  <string>${xml(stderrPath)}</string>
</dict>
</plist>
`;
}

function findExecutable(name, searchPath = process.env.PATH ?? '') {
  for (const directory of searchPath.split(delimiter)) {
    if (!directory) continue;
    const candidate = join(directory, name);
    try {
      accessSync(candidate, constants.X_OK);
      if (statSync(candidate).isFile()) return resolve(candidate);
    } catch {
      // Continue searching the caller's PATH.
    }
  }
  throw new Error(`Could not find ${name} on PATH. Install it before enabling the Mac service.`);
}

function runLaunchctl(args, { allowMissing = false } = {}) {
  const result = spawnSync('/bin/launchctl', args, { encoding: 'utf8' });
  if (result.error) throw result.error;
  if (result.status === 0) return result.stdout.trim();
  const message = `${result.stderr}${result.stdout}`;
  if (allowMissing && /Could not find service|service not found|No such process/iu.test(message))
    return '';
  throw new Error(message.trim() || `launchctl ${args.join(' ')} exited ${result.status}`);
}

function assertMac() {
  if (process.platform !== 'darwin') throw new Error('The LaunchAgent is available only on macOS.');
  if (typeof process.getuid !== 'function' || process.getuid() === 0)
    throw new Error('Run this as the signed-in Mac user, not as root or with sudo.');
}

function install() {
  assertMac();
  if (!existsSync(join(projectRoot, 'dist', 'index.html')))
    throw new Error('Build the web application first with npm run build.');
  const home = process.env.HOME;
  if (!home) throw new Error('HOME is not set for the current macOS user.');
  const env = { ...process.env, HOME: home };
  const config = resolveLanConfig(env, networkInterfaces());
  for (const [path, labelText] of [
    [config.cert, 'TLS certificate'],
    [config.key, 'TLS private key'],
  ]) {
    accessSync(path, constants.R_OK);
    if (!statSync(path).isFile()) throw new Error(`${labelText} must be a regular file: ${path}`);
  }
  const uvPath = findExecutable('uv');
  const pathValue = [
    dirname(uvPath),
    '/opt/homebrew/bin',
    '/usr/local/bin',
    '/usr/bin',
    '/bin',
  ].join(delimiter);
  const logDirectory = join(projectRoot, 'private', 'logs');
  mkdirSync(logDirectory, { recursive: true, mode: 0o700 });
  chmodSync(logDirectory, 0o700);
  mkdirSync(launchAgentsDirectory, { recursive: true, mode: 0o755 });

  const content = buildLaunchAgentPlist({
    nodePath: process.execPath,
    scriptPath: serverScript,
    workingDirectory: projectRoot,
    stdoutPath: join(logDirectory, 'server.stdout.log'),
    stderrPath: join(logDirectory, 'server.stderr.log'),
    env,
    pathValue,
  });
  const temporaryPath = `${plistPath}.${process.pid}.tmp`;
  writeFileSync(temporaryPath, content, { mode: 0o600, flag: 'wx' });
  try {
    chmodSync(temporaryPath, 0o600);
    renameSync(temporaryPath, plistPath);
    const domain = `gui/${process.getuid()}`;
    runLaunchctl(['bootout', domain, plistPath], { allowMissing: true });
    runLaunchctl(['bootstrap', domain, plistPath]);
  } catch (error) {
    rmSync(temporaryPath, { force: true });
    throw error;
  }
  process.stdout.write(
    `Installed and started ${label} for ${config.host}:${config.port}.\n` +
      `Logs: ${join(logDirectory, 'server.stderr.log')}\n` +
      `Check: npm run lan-service:status\n`,
  );
}

function status() {
  assertMac();
  process.stdout.write(runLaunchctl(['print', `gui/${process.getuid()}/${label}`]) + '\n');
}

function uninstall() {
  assertMac();
  runLaunchctl(['bootout', `gui/${process.getuid()}`, plistPath], { allowMissing: true });
  rmSync(plistPath, { force: true });
  process.stdout.write(`Stopped and removed ${label}. Logs and family data were kept.\n`);
}

export function main(command = process.argv[2]) {
  try {
    if (command === 'install') install();
    else if (command === 'status') status();
    else if (command === 'uninstall') uninstall();
    else {
      process.stderr.write('Usage: node scripts/launch-agent.mjs <install|status|uninstall>\n');
      process.exitCode = 2;
    }
  } catch (error) {
    process.stderr.write(`Mac service ${command ?? 'command'} failed: ${error.message}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main();
