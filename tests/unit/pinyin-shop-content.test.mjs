import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { validatePinyinShop } from '../../scripts/validate-pinyin-shop.mjs';
const shop = JSON.parse(readFileSync('content/pinyin-shop.json', 'utf8'));
const pictures = JSON.parse(readFileSync('content/illustrations.json', 'utf8'));
it('SHOP-04: release gate verifies a real 96-cell local image and separate reading deck', () => {
  expect(validatePinyinShop(shop, pictures, (src) => readFileSync(`public${src}`))).toEqual([]);
  expect(
    validatePinyinShop(shop, pictures, () => {
      throw new Error('missing');
    }),
  ).toContain('shop: image atlas unavailable');
});
it('SHOP-04/05: gate rejects altered shelf count, fractional price, missing image and linked answers', () => {
  const changed = structuredClone(shop);
  changed.targetIds[0] = 'missing';
  changed.products[0].priceCents = 1.5;
  changed.products[1].imageIndex = changed.products[2].imageIndex;
  changed.products[2].targetId = 'answer';
  changed.products[3].shelfId = 'unknown';
  changed.recognitionTimeoutMs = 15000;
  const errors = validatePinyinShop(changed, pictures);
  for (const phrase of [
    'invalid timing',
    'integer cents',
    'duplicate product image',
    'must not bind',
    'invalid target',
    'needs 12',
  ])
    expect(errors.some((error) => error.includes(phrase))).toBe(true);
});
