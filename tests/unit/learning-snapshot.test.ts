import { describe, expect, it } from 'vitest';
import { parseAnswer, parseSession } from '../../src/platform/learning-snapshot';

describe('learning response boundary', () => {
  it('rejects partial and null answer responses before the answer is acknowledged', () => {
    expect(() => parseAnswer(null)).toThrow('LEARNING_RESPONSE_INVALID');
    expect(() => parseAnswer({ correct: true, correctOptionId: 'a', mastery: null })).toThrow(
      'LEARNING_RESPONSE_INVALID',
    );
    expect(
      parseAnswer({ correct: false, correctOptionId: 'a', mastery: { status: 'practicing' } })
        .correct,
    ).toBe(false);
  });

  it('rejects frozen sessions with missing option data', () => {
    expect(() =>
      parseSession({ id: 'round', results: {}, tasks: [{ instanceId: 'one', exercise: null }] }),
    ).toThrow('LEARNING_RESPONSE_INVALID');
  });
});
