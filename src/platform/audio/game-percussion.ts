/** Short local drum synthesis; no recordings, network, music loop or auto-play. */
export class GamePercussion {
  private context: AudioContext | null = null;
  hit() {
    try {
      this.context ??= new AudioContext();
      const ctx = this.context;
      void ctx.resume().catch(() => {});
      const oscillator = ctx.createOscillator(),
        gain = ctx.createGain();
      oscillator.frequency.setValueAtTime(160, ctx.currentTime);
      oscillator.frequency.exponentialRampToValueAtTime(50, ctx.currentTime + 0.12);
      gain.gain.setValueAtTime(0.16, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.16);
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start();
      oscillator.stop(ctx.currentTime + 0.17);
      oscillator.onended = () => {
        oscillator.disconnect();
        gain.disconnect();
      };
    } catch {
      /* Unsupported sound never affects an answer. */
    }
  }
  close() {
    if (this.context) {
      void this.context.close().catch(() => {});
      this.context = null;
    }
  }
}
