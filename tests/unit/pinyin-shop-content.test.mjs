import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { validatePinyinShop } from '../../scripts/validate-pinyin-shop.mjs';
const shop = JSON.parse(readFileSync('content/pinyin-shop.json', 'utf8'));
const pictures = JSON.parse(readFileSync('content/illustrations.json', 'utf8'));
it('SHOP-01: release gate rejects broken and duplicate targets and unbounded rules', () => {
  expect(validatePinyinShop(shop, pictures)).toEqual([]);
  const changed = structuredClone(shop);
  changed.products[0].targetId = 'missing';
  changed.products.push(changed.products[1]);
  changed.basketLimit = 100;
  expect(validatePinyinShop(changed, pictures).length).toBeGreaterThanOrEqual(4);
});
