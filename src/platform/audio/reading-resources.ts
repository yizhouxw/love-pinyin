import type { DailyDay, DailyItem } from '../../domain/daily-reading';
export type ReadingResource = { kind: 'voice' | 'daily-audio'; id: string };

export function itemResources(item: DailyItem): ReadingResource[] {
  return item.narrationId
    ? [{ kind: 'voice', id: item.narrationId }]
    : item.audioIds.map((id) => ({ kind: 'daily-audio', id }));
}

export function dayResources(day: DailyDay, ui: Record<string, string>): ReadingResource[] {
  const resources: ReadingResource[] = [];
  for (const section of day.sections) {
    resources.push({ kind: 'voice', id: `daily-instruction-${section.id}` });
    for (const item of section.items) {
      if (item.available) resources.push(...itemResources(item));
      if (item.wordExample) resources.push({ kind: 'voice', id: item.wordExample.id });
    }
  }
  resources.push(
    ...Object.keys(ui).map((key) => ({ kind: 'voice' as const, id: `daily-ui-${key}` })),
  );
  return [
    ...new Map(resources.map((resource) => [`${resource.kind}/${resource.id}`, resource])).values(),
  ];
}
