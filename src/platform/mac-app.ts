export function isMacApp(): boolean {
  return (
    typeof window !== 'undefined' &&
    (window as Window & { __LOVE_PINYIN_MAC_APP__?: boolean }).__LOVE_PINYIN_MAC_APP__ === true
  );
}
