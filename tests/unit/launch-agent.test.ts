import { describe, expect, it } from 'vitest';
import { buildLaunchAgentPlist, launchctlServiceIsLoaded } from '../../scripts/launch-agent.mjs';

function fixture(workingDirectory = '/Users/family/love-pinyin') {
  return buildLaunchAgentPlist({
    nodePath: '/opt/homebrew/bin/node',
    scriptPath: '/Users/family/love-pinyin/scripts/serve-lan.mjs',
    workingDirectory,
    stdoutPath: '/Users/family/love-pinyin/private/logs/stdout.log',
    stderrPath: '/Users/family/love-pinyin/private/logs/stderr.log',
    env: {
      HOME: '/Users/family',
      LOVE_PINYIN_BIND_IP: '192.168.1.20',
      LOVE_PINYIN_TLS_CERT: '/Users/family/certs/mac-studio.pem',
      LOVE_PINYIN_TLS_KEY: '/Users/family/certs/mac-studio-key.pem',
    },
    pathValue: '/Users/family/.local/bin:/opt/homebrew/bin:/usr/bin:/bin',
  });
}

describe('Mac LaunchAgent 配置', () => {
  it('使用固定 Node 入口、项目工作目录和经校验的家庭 LAN TLS 配置', () => {
    const plist = fixture();
    expect(plist).toContain('<string>com.lovepinyin.server</string>');
    expect(plist).toContain('<string>/opt/homebrew/bin/node</string>');
    expect(plist).toContain('<string>/Users/family/love-pinyin</string>');
    expect(plist).toContain(
      '<key>LOVE_PINYIN_BIND_IP</key>\n        <string>192.168.1.20</string>',
    );
    expect(plist).toContain('<key>LOVE_PINYIN_TLS_KEY</key>');
    expect(plist).toContain('<key>UV_PYTHON_DOWNLOADS</key>\n        <string>never</string>');
    expect(plist).toContain('<key>RunAtLoad</key>\n  <true/>');
    expect(plist).toContain('<key>ThrottleInterval</key>\n  <integer>30</integer>');
  });

  it('XML-escapes paths so filenames cannot corrupt the launchd property list', () => {
    const plist = fixture('/Users/A & B/love<pinyin>');
    expect(plist).toContain('<string>/Users/A &amp; B/love&lt;pinyin&gt;</string>');
    expect(plist).not.toContain('<string>/Users/A & B/love<pinyin></string>');
  });

  it('区分 LaunchAgent 未加载与 launchctl 的真实错误', () => {
    expect(launchctlServiceIsLoaded({ status: 0, stdout: 'service = com.lovepinyin.server' })).toBe(
      true,
    );
    expect(
      launchctlServiceIsLoaded({
        status: 113,
        stderr: 'Could not find service "com.lovepinyin.server" in domain for uid: 501',
      }),
    ).toBe(false);
    expect(() =>
      launchctlServiceIsLoaded({ status: 1, stderr: 'Operation not permitted' }),
    ).toThrow('Operation not permitted');
    expect(() =>
      launchctlServiceIsLoaded({ status: null, error: new Error('spawn failed') }),
    ).toThrow('spawn failed');
  });
});
