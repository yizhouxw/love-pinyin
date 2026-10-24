import { useCallback, useEffect, useRef, useState } from 'react';
import type { IllustrationCatalog } from '../domain/illustrations';
import type { AudioRequirement, Knowledge, Lesson, Progress } from '../domain/learning-api';
import type { WritingCatalog } from '../domain/writing';
import { audioPlayer } from '../platform/audio/browser-audio-player';
import { learningAssetUrl } from '../platform/guest';
import { WordCards } from './illustrations';
import { categoryLabels } from './labels';
import { type LearningAudio } from './learning-voice';
import { WritingWorkshop } from './writing';

export function LessonDetail({
  lesson,
  knowledge,
  audioRequirements,
  familyAudio,
  writingCatalog,
  illustrations,
  soundEnabled,
  masteryById,
  busy,
  withinCurrentRange,
  canPractice,
  onGuidanceChange,
  onBack,
  onReview,
  onStart,
}: {
  lesson?: Lesson;
  knowledge: Knowledge[];
  audioRequirements: AudioRequirement[];
  familyAudio?: LearningAudio['lessons'][string];
  writingCatalog?: WritingCatalog;
  illustrations?: IllustrationCatalog;
  soundEnabled: boolean;
  masteryById: Map<string, Progress['mastery'][number]>;
  busy: boolean;
  withinCurrentRange: boolean;
  canPractice: boolean;
  onGuidanceChange: (enabled: boolean) => void;
  onBack: () => void;
  onReview: (knowledgeId: string) => void;
  onStart: () => void;
}) {
  const [activity, setActivity] = useState<'listen' | 'write' | 'practice'>('listen');
  const courseMedia = useRef<HTMLAudioElement | null>(null);
  const [coursePlaying, setCoursePlaying] = useState(false);
  const [courseError, setCourseError] = useState(false);
  const [playingAudioId, setPlayingAudioId] = useState<string | null>(null);
  const [audioFailureId, setAudioFailureId] = useState<string | null>(null);
  const playback = useRef<{ audioId: string; controller: AbortController } | null>(null);
  const releasePlayback = useCallback(() => {
    const active = playback.current;
    playback.current = null;
    active?.controller.abort();
    audioPlayer.stop();
  }, []);
  const stopPlayback = useCallback(() => {
    releasePlayback();
    setPlayingAudioId(null);
  }, [releasePlayback]);

  useEffect(() => {
    const media = courseMedia.current;
    if (media) return audioPlayer.registerExternalMedia(media);
  }, [activity, familyAudio?.audioId, lesson?.id]);

  useEffect(() => {
    const stopWhenHidden = () => {
      if (document.hidden) stopPlayback();
    };
    document.addEventListener('visibilitychange', stopWhenHidden);
    return () => {
      document.removeEventListener('visibilitychange', stopWhenHidden);
      releasePlayback();
    };
  }, [releasePlayback, stopPlayback]);

  if (!lesson)
    return (
      <section className="lesson-detail" role="status">
        <h2>请选择一课</h2>
        <button className="quiet" onClick={onBack}>
          返回学习路线
        </button>
      </section>
    );
  return (
    <section className="lesson-detail">
      <button className="quiet lesson-back" onClick={onBack}>
        ← 返回学习路线
      </button>
      <p className="eyebrow">第 {lesson.order} 课 · 课程知识卡</p>
      <h2 id={`lesson-heading-${lesson.id}`} tabIndex={-1}>
        {lesson.title}
      </h2>
      <div className="lesson-activities" role="group" aria-label="选择本课活动">
        {(
          [
            ['listen', '听一听'],
            ['write', '写一写'],
            ['practice', '练一练'],
          ] as const
        ).map(([id, label]) => (
          <button
            className="quiet"
            key={id}
            aria-pressed={activity === id}
            onClick={() => {
              stopPlayback();
              courseMedia.current?.pause();
              setActivity(id);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {activity === 'practice' && (
        <div className="lesson-practice">
          <button className="start-button" disabled={!canPractice} onClick={onStart}>
            {canPractice ? '开始本课练习 →' : '练习资料尚未准备好'}
          </button>
          {!withinCurrentRange && <p>请家长把当前学习课调整到这里，再开始练习。</p>}
        </div>
      )}
      {activity === 'listen' && (
        <>
          <section className="family-course-audio" aria-label="家庭课程录音">
            <span className="course-audio-icon" aria-hidden="true">
              🎧
            </span>
            <div>
              <h3>先听老师讲一讲</h3>
              <button
                className="voice-button"
                aria-label={coursePlaying ? '停止播放课程录音' : '播放课程录音'}
                aria-pressed={coursePlaying}
                onClick={() => {
                  const media = courseMedia.current;
                  if (!media) return;
                  if (coursePlaying) media.pause();
                  else {
                    setCourseError(false);
                    if (media.error) media.load();
                    void media.play().catch(() => setCourseError(true));
                  }
                }}
              >
                {coursePlaying ? 'Ⅱ 暂停课程录音' : '▶ 播放课程录音'}
              </button>
              <audio
                ref={courseMedia}
                aria-label="课程录音播放进度"
                controls
                preload="metadata"
                src={learningAssetUrl('voice', familyAudio?.audioId ?? `lesson-${lesson.id}`)}
                onPlay={() => setCoursePlaying(true)}
                onPause={() => setCoursePlaying(false)}
                onEnded={() => setCoursePlaying(false)}
                onError={() => setCourseError(true)}
              />
              {courseError && (
                <p className="audio-error" role="alert">
                  课程录音未能播放，请重试；仍未播放时请家长检查 Mac 上的家庭音频。
                </p>
              )}
              <details>
                <summary>家长查看录音来源</summary>
                <p>
                  家庭提供的旧版整课录音，录音中提到的课次和页码与当前教材可能不同。本课按知识内容对应，不把整课录音当作单个拼音的标准音。
                </p>
                {familyAudio?.title && <p>{familyAudio.title}</p>}
                {!familyAudio?.available && (
                  <p>尚未读取到本课录音，请在 Mac 上完成家庭学习音频准备后重试。</p>
                )}
              </details>
            </div>
          </section>
          {illustrations && <WordCards catalog={illustrations} lessonId={lesson.id} />}
        </>
      )}
      {activity === 'write' && writingCatalog && (
        <WritingWorkshop
          catalog={writingCatalog}
          lessonId={lesson.id}
          soundEnabled={soundEnabled}
          onGuidanceChange={onGuidanceChange}
        />
      )}
      <details className="lesson-knowledge">
        <summary>知识与教学提示</summary>
        <ul className="lesson-objectives">
          {lesson.objectives.map((objective) => (
            <li key={objective}>{objective}</li>
          ))}
        </ul>
        {knowledge.length > 0 ? (
          <div className="knowledge-grid">
            {knowledge.map((item) => {
              const state = masteryById.get(item.id);
              const audio = audioRequirements.find(
                (asset) => asset.knowledgeIds.includes(item.id) && asset.available === true,
              );
              const statusLabel =
                state?.status === 'mastered'
                  ? '已掌握'
                  : state?.status === 'practicing'
                    ? '练习中'
                    : '未开始';
              return (
                <article className="knowledge-card" key={item.id}>
                  <div className="knowledge-card-meta">
                    <span>{categoryLabels[item.category] ?? '拼音知识'}</span>
                    <span>{statusLabel}</span>
                  </div>
                  <h3>{item.symbol}</h3>
                  {state?.reviewDue && (
                    <>
                      <p className="review-due-badge">到期复习 · {state.reviewDueDate}</p>
                      <button
                        className="quiet"
                        disabled={busy || !withinCurrentRange}
                        onClick={() => onReview(item.id)}
                      >
                        开始两题复习
                      </button>
                    </>
                  )}
                  {audio ? (
                    <button
                      className="audio-play-button"
                      aria-label={`${item.symbol} ${playingAudioId === audio.id ? '停止播放' : '播放标准音'}`}
                      aria-pressed={playingAudioId === audio.id}
                      onClick={() => {
                        if (playingAudioId === audio.id) {
                          stopPlayback();
                          return;
                        }
                        stopPlayback();
                        setAudioFailureId(null);
                        const controller = new AbortController();
                        playback.current = { audioId: audio.id, controller };
                        setPlayingAudioId(audio.id);
                        void audioPlayer
                          .play(audio.id, controller.signal)
                          .catch((reason: unknown) => {
                            if (reason instanceof Error && reason.name !== 'AbortError')
                              setAudioFailureId(audio.id);
                          })
                          .finally(() => {
                            if (playback.current?.controller === controller) {
                              playback.current = null;
                              setPlayingAudioId(null);
                            }
                          });
                      }}
                    >
                      {playingAudioId === audio.id ? '■ 停止标准音' : '♫ 播放标准音'}
                    </button>
                  ) : null}
                  {audioFailureId === audio?.id && (
                    <p className="audio-error" role="alert">
                      标准音暂时无法播放，请检查家庭 Mac 上的音频资源。
                    </p>
                  )}
                  <details>
                    <summary>家长教学提示</summary>
                    <p>{item.teachingNote}</p>
                    {audio?.standardSource && (
                      <p>
                        标准音来源：{audio.standardSource.title}。
                        {audio.standardSource.exampleTone &&
                          `这段标准音带第${audio.standardSource.exampleTone}声。`}
                      </p>
                    )}
                  </details>
                </article>
              );
            })}
          </div>
        ) : (
          <p role="status">这课的知识资料还未准备好。</p>
        )}
      </details>
    </section>
  );
}
