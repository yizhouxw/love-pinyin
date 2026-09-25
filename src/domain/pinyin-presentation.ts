export function splitPinyinCandidate(label: string, initials: string[]) {
  const normalized = label.normalize('NFC').toLowerCase();
  if (!/^[a-züāáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ]+$/u.test(normalized)) return null;
  const first = [...initials]
    .sort((left, right) => right.length - left.length)
    .find((item) => normalized.startsWith(item));
  if (!first || normalized.length <= first.length) return null;
  return { onset: first, rime: normalized.slice(first.length) };
}

export function pinyinTone(label: string): number | null {
  const ordinal: Record<string, number> = {
    一: 1,
    二: 2,
    三: 3,
    四: 4,
    '1': 1,
    '2': 2,
    '3': 3,
    '4': 4,
  };
  const namedTone = label.match(/第([一二三四1-4])声/u)?.[1];
  if (namedTone) return ordinal[namedTone] ?? null;
  const marks = [...label.normalize('NFD')].map((character) => character.codePointAt(0));
  if (marks.includes(0x0304)) return 1;
  if (marks.includes(0x0301)) return 2;
  if (marks.includes(0x030c)) return 3;
  if (marks.includes(0x0300)) return 4;
  return null;
}
