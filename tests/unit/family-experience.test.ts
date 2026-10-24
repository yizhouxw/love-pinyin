import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { errorMessage, Notice } from '../../src/app/notice';
import { ReleaseHistory } from '../../src/app/release-history';
import product from '../../package.json';
import changelog from '../../content/changelog.json';

describe('family operation feedback', () => {
  it('explains pairing, permission and restore failures with specific next steps', () => {
    expect(errorMessage('PAIRING_CODE_INVALID')).toContain('重新生成');
    expect(errorMessage('PARENT_LOCAL_REQUIRED')).toContain('127.0.0.1');
    expect(errorMessage('IMPORT_PREVIEW_EXPIRED')).toContain('重新选择');
    expect(errorMessage('BACKUP_ATTEMPT_INVALID')).toContain('JSON');
    expect(errorMessage('SOME_UNKNOWN_ERROR')).not.toContain('SOME_UNKNOWN_ERROR');
    const html = renderToStaticMarkup(
      createElement(Notice, { error: 'PAIRING_CODE_INVALID', onReconnect: () => {} }),
    );
    expect(html).toContain(
      '<details><summary>技术详情</summary><code>PAIRING_CODE_INVALID</code></details>',
    );
  });
  it('uses the product version source and separates content version in local history', () => {
    const html = renderToStaticMarkup(
      createElement(ReleaseHistory, { contentVersion: 'teaching-test' }),
    );
    expect(html).toContain(`版本 ${product.version}`);
    expect(html).toContain('教学内容版本：teaching-test');
    expect(changelog.releases[0]?.version).toBe(product.version);
    expect(html).toContain('<dialog');
    expect(html).not.toContain('https://');
  });
});
