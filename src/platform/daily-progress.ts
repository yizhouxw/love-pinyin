import type { ReadingMark } from '../domain/daily-reading';
import { isAndroidApp } from './android-app';
import { androidProgress } from './android-progress';

export function readDailyProgress(source: string): Record<string, ReadingMark> {
  if (!isAndroidApp()) return {};
  return androidProgress<Record<string, ReadingMark>>(`daily:${source}`) ?? {};
}
export function saveDailyProgress(source: string, marks: Record<string, ReadingMark>) {
  if (isAndroidApp()) androidProgress(`daily:${source}`, marks);
}
