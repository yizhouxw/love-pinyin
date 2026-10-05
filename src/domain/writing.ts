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
export type WritingTarget = { id: string; label: string; glyphIds: string[] };
export type WritingCatalog = {
  version: number;
  grid: { lines: number[]; letterWidth: number };
  ui: Record<string, string>;
  glyphs: Record<string, WritingGlyph>;
  lessons: Record<string, WritingTarget[]>;
};
export type WritingOption = { glyphId: string; offsetY: number; description: string };

/** Presentation only: the authored catalog owns glyph order, strokes and geometry. */
export function writingSteps(target: WritingTarget, catalog: WritingCatalog) {
  return target.glyphIds.flatMap((id, glyphIndex) =>
    catalog.glyphs[id]!.strokes.map((stroke, strokeIndex) => ({
      glyphId: id,
      glyphIndex,
      strokeIndex,
      stroke,
      audioId: `writing-${id}-stroke-${strokeIndex + 1}`,
    })),
  );
}
