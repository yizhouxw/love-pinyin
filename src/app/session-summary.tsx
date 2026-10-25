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
  const results = Object.values(session.results as Record<string, Json>);
  const pending = results.filter((item) => item.clockPending && !item.skipped).length;
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
            {results.filter((item) => item.firstTryCorrect && !item.clockPending).length} 题
          </li>
          <li>
            提示后答对：
            {
              results.filter(
                (item) =>
                  item.correct && !item.firstTryCorrect && !item.skipped && !item.clockPending,
              ).length
            }{' '}
            题
          </li>
          <li>
            首次待巩固：
            {
              results.filter((item) => !item.skipped && !item.correct && !item.clockPending).length
            }{' '}
            题
          </li>
          <li>
            跳过：
            {results.filter((item) => item.skipped).length} 题
          </li>
          {pending > 0 && <li>待校时，不计成绩：{pending} 题</li>}
        </ul>
        <button className="next-button" disabled={busy} onClick={onFinish}>
          {session.gameId ? '回到游戏乐园' : '回到小岛'}
        </button>
      </section>
      <Notice error={error} onReconnect={onReconnect} />
    </main>
  );
}
