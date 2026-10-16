/** A display suggestion only; never used for identity, permissions, or hardware fingerprinting. */
export function suggestedDeviceModel(
  info: Pick<Navigator, 'userAgent' | 'maxTouchPoints'> = navigator,
): string {
  const agent = info.userAgent;
  const type =
    /iPad/i.test(agent) || (/Macintosh/i.test(agent) && info.maxTouchPoints > 1)
      ? 'iPad'
      : /iPhone/i.test(agent)
        ? 'iPhone'
        : /Android/i.test(agent)
          ? 'Android 设备'
          : /Macintosh|Mac OS X/i.test(agent)
            ? 'Mac'
            : /Windows/i.test(agent)
              ? 'Windows 电脑'
              : /Linux/i.test(agent)
                ? 'Linux 电脑'
                : '';
  return type ? `${type}（浏览器推测，可修改具体型号）` : '';
}
