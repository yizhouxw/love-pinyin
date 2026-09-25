import { describe, expect, it } from 'vitest';
import { resolveLanConfig } from '../../scripts/serve-lan.mjs';

const interfaces = {
  en0: [
    {
      address: '192.168.1.20',
      netmask: '255.255.255.0',
      family: 'IPv4',
      mac: '',
      internal: false,
      cidr: '192.168.1.20/24',
    },
  ],
  lo0: [
    {
      address: '127.0.0.1',
      netmask: '255.0.0.0',
      family: 'IPv4',
      mac: '',
      internal: true,
      cidr: '127.0.0.1/8',
    },
  ],
};

describe('Mac 家庭局域网启动配置', () => {
  it('仅绑定显式指定且属于本机的 IPv4，并传递 HTTPS 证书', () => {
    expect(
      resolveLanConfig(
        {
          LOVE_PINYIN_BIND_IP: '192.168.1.20',
          LOVE_PINYIN_TLS_CERT: 'certs/lan.pem',
          LOVE_PINYIN_TLS_KEY: 'certs/lan-key.pem',
        },
        interfaces,
      ),
    ).toMatchObject({
      host: '192.168.1.20',
      port: 8443,
      cert: expect.stringMatching(/certs\/lan\.pem$/u),
      key: expect.stringMatching(/certs\/lan-key\.pem$/u),
    });
  });

  it.each(['', '0.0.0.0', '127.0.0.1', '192.168.1.21', 'mac-studio.local'])(
    '拒绝不适合绑定的地址 %s',
    (host) => {
      expect(() =>
        resolveLanConfig(
          {
            LOVE_PINYIN_BIND_IP: host,
            LOVE_PINYIN_TLS_CERT: 'cert.pem',
            LOVE_PINYIN_TLS_KEY: 'key.pem',
          },
          interfaces,
        ),
      ).toThrow();
    },
  );

  it('要求 HTTPS 密钥，并拒绝无效或低位系统端口', () => {
    const base = {
      LOVE_PINYIN_BIND_IP: '192.168.1.20',
      LOVE_PINYIN_TLS_CERT: 'cert.pem',
      LOVE_PINYIN_TLS_KEY: 'key.pem',
    };
    expect(() => resolveLanConfig({ ...base, LOVE_PINYIN_TLS_KEY: '' }, interfaces)).toThrow(
      /TLS_CERT and LOVE_PINYIN_TLS_KEY/u,
    );
    expect(() => resolveLanConfig({ ...base, LOVE_PINYIN_PORT: '70000' }, interfaces)).toThrow(
      /1024 to 65535/u,
    );
  });
});
