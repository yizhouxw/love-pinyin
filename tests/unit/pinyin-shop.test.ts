import { describe, expect, it } from 'vitest';
import curriculum from '../../content/curriculum.json';
import illustrations from '../../content/illustrations.json';
import shop from '../../content/pinyin-shop.json';
import { addShopProduct, shopOutcome, shopProducts } from '../../src/domain/pinyin-shop';
import type { Curriculum } from '../../src/domain/learning-api';
import type { PronunciationMatchResult } from '../../src/domain/pronunciation';

const course = curriculum as unknown as Curriculum;
const result: PronunciationMatchResult = {
  contractVersion: 1,
  requestId: 'request',
  targetId: 'target',
  evidence: 'acoustic',
  toneAssessed: false,
  status: 'matched',
  reason: null,
};
describe('SHOP-01/02: bounded basket and correlated pronunciation decisions', () => {
  it('keeps products in learned lessons and supports initial vowel gift packaging', () => {
    const first = shopProducts(course, 'lesson-01');
    expect(first).toHaveLength(3);
    expect(first.every((p) => p.target.task === 'final')).toBe(true);
    expect(shopProducts(course, 'unknown')).toEqual([]);
    const all = shopProducts(course, 'lesson-14');
    expect(all).toHaveLength(shop.products.length);
    expect(new Set(all.map((p) => p.target.id)).size).toBe(all.length);
    for (const product of all) {
      expect(product.audioRef).toBe(
        illustrations.items[product.targetId as keyof typeof illustrations.items].audioRef,
      );
      expect(product.target.pinyin).toBe(product.target.pinyin.normalize('NFC'));
    }
    expect(shopProducts(course, 'lesson-02').some((p) => p.target.pinyin === 'ü')).toBe(true);
  });
  it('rejects late, wrong-target and wrong-version matches', () => {
    expect(shopOutcome(result, 'new-request', 'target', false)).toBe('stale');
    expect(shopOutcome(result, 'request', 'other', false)).toBe('stale');
    expect(
      shopOutcome(
        { ...result, contractVersion: 2 } as unknown as PronunciationMatchResult,
        'request',
        'target',
        false,
      ),
    ).toBe('stale');
  });
  it('requires acoustic evidence in product mode and explicit mock mode for simulation', () => {
    expect(shopOutcome(result, 'request', 'target', false)).toBe('matched');
    expect(shopOutcome({ ...result, evidence: 'mock' }, 'request', 'target', false)).toBe(
      'unavailable',
    );
    expect(shopOutcome({ ...result, evidence: 'none' }, 'request', 'target', true)).toBe(
      'unavailable',
    );
    expect(shopOutcome({ ...result, evidence: 'mock' }, 'request', 'target', true)).toBe('matched');
    expect(shopOutcome({ ...result, status: 'retry' }, 'request', 'target', false)).toBe('retry');
    for (const status of ['uncertain', 'unavailable'] as const)
      expect(
        shopOutcome(
          { ...result, status, reason: 'insufficient-evidence' },
          'request',
          'target',
          false,
        ),
      ).toBe(status);
  });
  it('is idempotent per product, stops at six, and never mutates an earlier basket', () => {
    const original = ['a'];
    expect(addShopProduct(original, 'a')).toEqual(['a']);
    expect(addShopProduct(original, 'b')).toEqual(['a', 'b']);
    expect(original).toEqual(['a']);
    expect(addShopProduct(['a', 'b', 'c', 'd', 'e', 'f'], 'g')).toHaveLength(6);
  });
});
