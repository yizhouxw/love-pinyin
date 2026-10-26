import type { ShopCapture } from './browser-shop-recorder';

/** The explicit simulation does not request microphone access or fabricate acoustic samples. */
export class MockShopCapture implements ShopCapture {
  async start(): Promise<void> {}
  snapshot(): Blob {
    return new Blob([], { type: 'audio/wav' });
  }
  discard(): void {}
}
