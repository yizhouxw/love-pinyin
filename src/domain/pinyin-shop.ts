import shop from '../../content/pinyin-shop.json';
import illustrations from '../../content/illustrations.json';
import type { Curriculum } from './learning-api';
import type { PronunciationMatchResult, PronunciationTarget } from './pronunciation';
import type { IllustrationCatalog } from './illustrations';

export const shopRules = shop;
const pictures = illustrations as IllustrationCatalog;
export type ShopProduct = (typeof shop.products)[number] & {
  target: PronunciationTarget;
  audioRef: string;
  audioKind: 'standard' | 'daily';
};
export function shopProducts(curriculum: Curriculum, lessonId: string): ShopProduct[] {
  const order = curriculum.lessons.find((lesson) => lesson.id === lessonId)?.order ?? 0;
  const learned = new Set(curriculum.lessons.filter((l) => l.order <= order).map((l) => l.id));
  return shop.products.flatMap((product) => {
    const item = pictures.items[product.targetId];
    if (!item || !learned.has(item.lessonId)) return [];
    return [
      {
        ...product,
        target: {
          id: product.targetId,
          pinyin: item.pinyin,
          task: product.id.startsWith('gift-') ? ('final' as const) : ('syllable' as const),
        },
        audioRef: item.audioRef,
        audioKind: item.audioKind ?? 'standard',
      },
    ];
  });
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
