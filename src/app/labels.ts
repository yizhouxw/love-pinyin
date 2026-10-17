import narrationData from '../../content/narration.json';
import type { AttemptRecord, Narration } from '../domain/learning-api';

export const narration: Narration = narrationData;

export const categoryLabels: Record<string, string> = {
  initial: '声母',
  final: '韵母',
  tone: '声调',
  'whole-syllable': '整体认读音节',
  'orthographic-letter': '拼写字母',
  rule: '拼写规则',
};

export const exerciseModeLabels: Record<string, string> = {
  'listen-choice': '听辨',
  'symbol-choice': '字形',
  'tone-choice': '声调',
  'blend-choice': '拼读',
};

export function attemptOutcome(attempt: AttemptRecord) {
  if (attempt.clockPending) return '待校时，不计入掌握度';
  if (!attempt.dueCredit) return '日内重复练习，不计入掌握样本';
  if (attempt.firstTryCorrect) return '独立首次答对';
  if (attempt.hintUsed) return '使用过提示，未独立首次答对';
  return '首次未独立答对';
}

export function formatAttemptTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return '时间未知';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).format(date);
}
