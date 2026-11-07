import { useEffect, useState } from 'react';
import playback from '../../content/playback.json';
import type { Curriculum } from '../domain/learning-api';
import { readGuidancePreference, saveGuidancePreference } from '../platform/guidance-preference';
import { readPlaybackPreference, savePlaybackPreference } from '../platform/playback-preference';
import { iosOperation } from '../platform/ios-app';
import { audioPlayer } from '../platform/audio/browser-audio-player';
import { DailyReadingPage } from './daily-reading';
import { GuidanceSwitch } from './guidance-switch';
import { type LearningAudio } from './learning-voice';
import { LessonDetail } from './lesson-detail';
import { WordPractice } from './word-practice';

type Library = { curriculum: Curriculum; sounds: LearningAudio };

export function IOSListeningLibrary() {
  const [library, setLibrary] = useState<Library | null>(null);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [page, setPage] = useState('home');
  const [guidanceEnabled, setGuidance] = useState(() => readGuidancePreference()?.enabled ?? true);
  const defaultGap = playback.gap.defaultSeconds;
  const [gapSeconds, setGap] = useState(() => readPlaybackPreference(false)?.seconds ?? defaultGap);
  const onGuidanceChange = (enabled: boolean) => {
    setGuidance(enabled);
    saveGuidancePreference({ enabled, familyDefault: true });
  };
  const onGapChange = (seconds: number) => {
    setGap(seconds);
    savePlaybackPreference({ seconds, familyDefault: defaultGap }, false);
  };
  const open = (next: string) => {
    audioPlayer.stop();
    setPage(next);
  };

  useEffect(() => {
    let current = true;
    iosOperation<Library>('library').then(
      (value) => {
        if (current) setLibrary(value);
      },
      () => {
        if (current) setFailed(true);
      },
    );
    const interrupt = () => audioPlayer.stop();
    window.addEventListener('lp-ios-audio-interrupted', interrupt);
    return () => {
      current = false;
      window.removeEventListener('lp-ios-audio-interrupted', interrupt);
      interrupt();
    };
  }, [retry]);

  useEffect(() => {
    if (library) void iosOperation('libraryReady').catch(() => undefined);
  }, [library]);

  const lesson = library?.curriculum.lessons.find((item) => item.id === page);
  const reading = {
    guidanceEnabled,
    onGuidanceChange,
    gapSeconds,
    onGapChange,
    onBack: () => open('home'),
  };
  return (
    <main className="home-page">
      {!library ? (
        failed ? (
          <div role="alert">
            <p>本机课程暂时无法读取。</p>
            <button
              onClick={() => {
                setFailed(false);
                setRetry(retry + 1);
              }}
            >
              重试
            </button>
          </div>
        ) : (
          <p role="status">正在打开本机课程…</p>
        )
      ) : page === 'daily' ? (
        <DailyReadingPage {...reading} />
      ) : page === 'words' ? (
        <WordPractice {...reading} />
      ) : lesson ? (
        <LessonDetail
          key={lesson.id}
          lesson={lesson}
          knowledge={library.curriculum.knowledgeItems.filter((item) =>
            lesson.knowledgeIds.includes(item.id),
          )}
          audioRequirements={library.curriculum.audioRequirements}
          familyAudio={library.sounds.lessons[lesson.id]}
          writingCatalog={library.curriculum.writing}
          illustrations={library.curriculum.illustrations}
          soundEnabled={guidanceEnabled}
          masteryById={new Map()}
          busy={false}
          withinCurrentRange={true}
          canPractice={false}
          listeningOnly
          onGuidanceChange={onGuidanceChange}
          onBack={() => open('home')}
        />
      ) : (
        <>
          <header className="topbar">
            <h1>爱拼音</h1>
            <GuidanceSwitch enabled={guidanceEnabled} onChange={onGuidanceChange} />
          </header>
          <p>离线听读验证版 · 课堂作答、学习记录和游戏将在后续接入。</p>
          <nav aria-label="天天练" className="lesson-activities">
            <button onClick={() => open('daily')}>天天练拼音</button>
            <button onClick={() => open('words')}>词语天天练</button>
          </nav>
          <h2>课堂听写</h2>
          <nav aria-label="选择课程" className="knowledge-grid">
            {library.curriculum.lessons.map((item) => (
              <button className="quiet" key={item.id} onClick={() => open(item.id)}>
                第 {item.order} 课 · {item.title}
              </button>
            ))}
          </nav>
        </>
      )}
    </main>
  );
}
