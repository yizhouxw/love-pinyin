export function resolveLanConfig(
  env: Record<string, string | undefined>,
  interfaces: Record<
    string,
    Array<{ address: string; family: string | number; internal: boolean }> | undefined
  >,
): { host: string; port: number; cert: string; key: string };
