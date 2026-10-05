export type WritingStroke = {
  d: string;
  start: number[];
  guide: string;
  instruction: string;
};
export type WritingGlyph = {
  symbol: string;
  lessonId: string;
  sourcePage: number;
  placement: string;
  description: string;
  strokes: WritingStroke[];
};
export type WritingTarget = {
  id: string;
  label: string;
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

/** Presentation only: the authored catalog owns glyph order, strokes and geometry. */
export function writingSteps(target: WritingTarget, catalog: WritingCatalog) {
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
