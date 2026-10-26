/** Test-only composition: controlled contract results are NOT acoustic accuracy evidence. */
import { createRoot } from 'react-dom/client';
import { useState } from 'react';
import { PinyinShop } from '../../src/app/pinyin-shop';
import type { PronunciationService } from '../../src/domain/pronunciation';
import type { Curriculum } from '../../src/domain/learning-api';
import curriculum from '../../content/curriculum.json';
import '../../src/app/styles.css';

const parameters = new URLSearchParams(location.search);
const mock = parameters.get('evidence') === 'mock';
const service: PronunciationService = {
  async match(request) {
    const mode = parameters.get('result') ?? 'matched';
    const delay = Number(parameters.get('delay') ?? '0');
    if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    if (mode === 'exception') throw new Error('TEST_NETWORK_FAILURE');
    const context = {
      contractVersion: 1 as const,
      requestId: mode === 'stale' ? 'old' : request.requestId,
      targetId: request.targetId,
      evidence: mock ? ('mock' as const) : ('acoustic' as const),
      toneAssessed: false,
    };
    if (request.audio.type !== 'audio/wav' || request.audio.size <= 44)
      throw new Error('INVALID_TEST_CAPTURE');
    const header = new DataView(await request.audio.arrayBuffer());
    if (
      header.getUint32(24, true) !== 16000 ||
      header.getUint16(22, true) !== 1 ||
      header.getUint16(34, true) !== 16
    )
      throw new Error('INVALID_TEST_WAV');
    if (mode === 'uncertain' || mode === 'unavailable')
      return { ...context, status: mode, reason: 'insufficient-evidence' };
    return { ...context, status: mode === 'retry' ? 'retry' : 'matched', reason: null };
  },
  async recognize() {
    throw new Error('not used');
  },
};
function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <main className="home-page">
      {open ? (
        <PinyinShop
          curriculum={curriculum as unknown as Curriculum}
          lessonId={parameters.get('lesson') ?? 'lesson-14'}
          recognition={{ service, mock }}
          onExit={() => setOpen(false)}
        />
      ) : (
        <p>测试场景已退出</p>
      )}
    </main>
  );
}
createRoot(document.getElementById('shop-root')!).render(<Harness />);
