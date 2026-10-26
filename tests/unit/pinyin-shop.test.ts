import { describe, expect, it } from 'vitest';
import curriculum from '../../content/curriculum.json';
import illustrations from '../../content/illustrations.json';
import shop from '../../content/pinyin-shop.json';
import {
  addShopProduct,
  shopOutcome,
  shopProducts,
  shopTargets,
  shopPrice,
  shopTotalCents,
} from '../../src/domain/pinyin-shop';
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
  it('offers all 96 goods independently of the learned reading deck', () => {
    expect(shopProducts()).toHaveLength(96);
    expect(
      shop.shelves.every((s) => shopProducts().filter((p) => p.shelfId === s.id).length === 12),
    ).toBe(true);
    expect(shopProducts().every((p) => !('targetId' in p))).toBe(true);
    expect(new Set(shopProducts().map((p) => p.imageIndex)).size).toBe(96);
    const first = shopTargets(course, 'lesson-01');
    expect(first).toHaveLength(3);
    expect(first.every((p) => p.target.task === 'final')).toBe(true);
    expect(shopTargets(course, 'unknown')).toEqual([]);
    expect(shopTargets(course, 'lesson-14')).toHaveLength(shop.targetIds.length);
    for (const task of shopTargets(course, 'lesson-14')) {
      expect(task.audioRef).toBe(
        illustrations.items[task.target.id as keyof typeof illustrations.items].audioRef,
      );
      expect(task.target.pinyin).toBe(task.target.pinyin.normalize('NFC'));
    }
    expect(shopTargets(course, 'lesson-02').some((t) => t.target.pinyin === 'ü')).toBe(true);
  });
  it('totals decorative integer prices exactly without involving pronunciation', () => {
    const ids = shopProducts()
      .slice(0, 6)
      .map((p) => p.id);
    expect(shopTotalCents(ids)).toBe(
      shopProducts()
        .slice(0, 6)
        .reduce((sum, p) => sum + p.priceCents, 0),
    );
    expect(shopTotalCents([])).toBe(0);
    expect(shopPrice(105)).toBe('¥1.05');
    expect(shopPrice(0)).toBe('¥0.00');
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
