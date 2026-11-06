import { isGuest } from './guest';
const key = 'love-pinyin-word-practice-v1';
let guest: string[] = [];
export function readWordProgress(): string[] {
  if (isGuest()) return guest;
  const value: unknown = JSON.parse(localStorage.getItem(key) ?? '[]');
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string'))
    throw new Error('INVALID_WORD_PROGRESS');
  return value as string[];
}
export function saveWordProgress(value: string[]) {
  if (isGuest()) guest = value;
  else localStorage.setItem(key, JSON.stringify(value));
}
