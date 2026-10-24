export type WritingStroke = {
  d: string;
  start: number[];
  guide: string;
  instruction: string;
};
export type WritingPronunciation = { kind: 'audio' | 'daily-audio'; id: string };
export type WritingGlyph = {
  symbol: string;
  pronunciation: WritingPronunciation;
  lessonId: string;
  sourcePage: number;
  placement: string;
  description: string;
  strokes: WritingStroke[];
};
export type WritingTarget = {
  id: string;
  label: string;
  pronunciation: WritingPronunciation;
  glyphIds: string[];
  tone?: { markId: string; glyphIndex: number; offsetY: number; omitStrokeIndices: number[] };
  note?: string;
};
export type WritingCatalog = {
  version: number;
  grid: { lines: number[]; letterWidth: number };
  ui: Record<string, string>;
  glyphs: Record<string, WritingGlyph>;
  marks: Record<string, { combining: string; stroke: WritingStroke }>;
  lessons: Record<string, WritingTarget[]>;
};
export type WritingOption = { glyphId: string; offsetY: number; description: string };

/** Standard recordings name the target and written letters; TTS only supplies Chinese prose. */
export function writingIntroduction(target: WritingTarget, catalog: WritingCatalog) {
  const clips: { kind: 'voice' | 'daily-audio' | 'audio'; id: string }[] = [
    { kind: 'voice', id: 'writing-ui-start' },
    target.pronunciation,
  ];
  if (target.glyphIds.length > 1) {
    clips.push({ kind: 'voice', id: 'writing-ui-composition' });
    target.glyphIds.forEach((id, index) => {
      if (index) clips.push({ kind: 'voice', id: 'writing-ui-and' });
      clips.push(catalog.glyphs[id]!.pronunciation);
    });
    clips.push({ kind: 'voice', id: 'writing-ui-joined' });
  }
  return clips;
}

/** Presentation only: the authored catalog owns glyph order, strokes and geometry. */
export function writingSteps(
  target: Pick<WritingTarget, 'glyphIds' | 'tone'>,
  catalog: WritingCatalog,
) {
  const steps = target.glyphIds.flatMap((id, glyphIndex) =>
    catalog.glyphs[id]!.strokes.flatMap((stroke, strokeIndex) =>
      target.tone?.glyphIndex === glyphIndex && target.tone.omitStrokeIndices.includes(strokeIndex)
        ? []
        : [
            {
              glyphId: id,
              glyphIndex,
              strokeIndex,
              stroke,
              kind: 'letter',
              offsetY: 0,
              audioId: `writing-${id}-stroke-${strokeIndex + 1}`,
            },
          ],
    ),
  );
  if (target.tone) {
    const tone = target.tone;
    steps.push({
      glyphId: target.glyphIds[tone.glyphIndex]!,
      glyphIndex: tone.glyphIndex,
      strokeIndex: 0,
      stroke: catalog.marks[tone.markId]!.stroke,
      kind: 'tone',
      offsetY: tone.offsetY,
      audioId: `writing-${tone.markId}`,
    });
  }
  return steps;
}
