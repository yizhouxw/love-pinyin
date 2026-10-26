import shop from '../../content/pinyin-shop.json';
import illustrations from '../../content/illustrations.json';
import type { Curriculum } from './learning-api';
import type { PronunciationMatchResult, PronunciationTarget } from './pronunciation';
import type { IllustrationCatalog } from './illustrations';

export const shopRules = shop;
const pictures = illustrations as IllustrationCatalog;
export type ShopProduct = (typeof shop.products)[number];
export type ShopTarget = {
  target: PronunciationTarget;
  audioRef: string;
  audioKind: 'standard' | 'daily';
};
/** All 96 goods are decorative: school progress only limits the independent reading deck. */
export function shopProducts(): readonly ShopProduct[] {
  return shop.products;
}
export function shopTargets(curriculum: Curriculum, lessonId: string): ShopTarget[] {
  const order = curriculum.lessons.find((lesson) => lesson.id === lessonId)?.order ?? 0;
  const learned = new Set(curriculum.lessons.filter((l) => l.order <= order).map((l) => l.id));
  const sortedIds = [...shop.targetIds].sort(
    (a, b) =>
      (curriculum.lessons.find((l) => l.id === pictures.items[b]?.lessonId)?.order ?? 0) -
      (curriculum.lessons.find((l) => l.id === pictures.items[a]?.lessonId)?.order ?? 0),
  );
  return sortedIds.flatMap((id) => {
    const item = pictures.items[id];
    if (!item || !learned.has(item.lessonId)) return [];
    return [
      {
        target: {
          id,
          pinyin: item.pinyin,
          task: shop.vowelTargetIds.includes(id) ? ('final' as const) : ('syllable' as const),
        },
        audioRef: item.audioRef,
        audioKind: item.audioKind ?? 'standard',
      },
    ];
  });
}
export function shopTotalCents(basket: readonly string[]): number {
  return basket.reduce(
    (total, id) => total + (shop.products.find((p) => p.id === id)?.priceCents ?? 0),
    0,
  );
}
export function shopPrice(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`;
}

export type ShopOutcome = 'matched' | 'retry' | 'uncertain' | 'unavailable' | 'stale';
/** Only the active correlated request may affect a basket; mock requires explicit development mode. */
export function shopOutcome(
  result: PronunciationMatchResult,
  requestId: string,
  targetId: string,
  mock: boolean,
): ShopOutcome {
  if (
    result.contractVersion !== 1 ||
    result.requestId !== requestId ||
    result.targetId !== targetId
  )
    return 'stale';
  if (result.status === 'matched' || result.status === 'retry') {
    if (result.evidence !== 'acoustic' && !(mock && result.evidence === 'mock'))
      return 'unavailable';
  }
  return result.status;
}

export function addShopProduct(basket: readonly string[], productId: string): string[] {
  return basket.includes(productId) || basket.length >= shop.basketLimit
    ? [...basket]
    : [...basket, productId];
}
