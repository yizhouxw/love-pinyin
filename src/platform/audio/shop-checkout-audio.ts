/** Local simulation cues only; never contacts a payment provider. */
export type ShopCheckoutCue =
  'checkout-guide' | 'confirm-guide' | 'alipay-receipt' | 'wechat-receipt';

export class ShopCheckoutAudio {
  private audio: HTMLAudioElement | null = null;

  play(cue: ShopCheckoutCue): Promise<void> {
    this.stop();
    this.audio = new Audio(`/shop/${cue}.wav`);
    return this.audio.play();
  }

  replay(): Promise<void> {
    if (!this.audio) return Promise.reject(new Error('No checkout cue'));
    this.audio.currentTime = 0;
    return this.audio.play();
  }

  stop(): void {
    this.audio?.pause();
  }
}
