import { isGuest } from './guest';
const key = 'love-pinyin-word-practice-v1';
let guest: string[] = [];
function storageKey(contentId: string) {
  return contentId === 'household' ? key : `${key}:${contentId}`;
}
export function readWordProgress(contentId: string): string[] {
  if (isGuest()) return guest;
  const value: unknown = JSON.parse(localStorage.getItem(storageKey(contentId)) ?? '[]');
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string'))
    throw new Error('INVALID_WORD_PROGRESS');
  return value as string[];
}
export function saveWordProgress(value: string[], contentId: string) {
  if (isGuest()) guest = value;
  else localStorage.setItem(storageKey(contentId), JSON.stringify(value));
}
