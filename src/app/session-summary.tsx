import type { Json, Session } from '../domain/learning-api';
import type { useLearningVoice } from './learning-voice';
import { VoiceButton, VoiceFailure } from './learning-voice';
import { Notice } from './notice';
export function SessionSummary({
  session,
  voice,
  busy,
  error,
  onFinish,
  onReconnect,
}: {
  session: Session;
  voice: ReturnType<typeof useLearningVoice>;
  busy: boolean;
  error: string;
  onFinish: () => void;
  onReconnect: () => void;
}) {
  return (
    <main className="play-page summary-page">
      <section className="question-card">
        <div className="mascot">🎉</div>
        <h1>今天的探索完成啦！</h1>
        <p>你认真完成了这一小段练习，休息一下也很好。</p>
        <VoiceButton id="ui-summary" voice={voice} label="听小结" />
        <VoiceFailure voice={voice} />
        <ul className="session-summary" aria-label="本次练习小结">
          <li>
            独立答对：
            {
              Object.values(session.results as Record<string, Json>).filter(
                (item) => item.firstTryCorrect,
              ).length
            }{' '}
            题
          </li>
          <li>
            提示后答对：
            {
              Object.values(session.results as Record<string, Json>).filter(
                (item) => item.correct && !item.firstTryCorrect && !item.skipped,
              ).length
            }{' '}
            题
          </li>
          <li>
            跳过：
            {
              Object.values(session.results as Record<string, Json>).filter((item) => item.skipped)
                .length
            }{' '}
            题
          </li>
        </ul>
        <button className="next-button" disabled={busy} onClick={onFinish}>
          回到小岛
        </button>
      </section>
      <Notice error={error} onReconnect={onReconnect} />
    </main>
  );
}
