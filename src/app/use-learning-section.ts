import { useEffect, useState } from 'react';

type Section = 'games' | 'daily-reading' | 'word-practice';
type Route = Section | 'home';

function readRoute(): Route {
  switch (location.hash) {
    case '#games':
      return 'games';
    case '#daily-reading':
      return 'daily-reading';
    case '#word-practice':
      return 'word-practice';
    default:
      return 'home';
  }
}

export function useLearningSection() {
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const sync = () => setRoute(readRoute());
    window.addEventListener('popstate', sync);
    window.addEventListener('hashchange', sync);
    return () => {
      window.removeEventListener('popstate', sync);
      window.removeEventListener('hashchange', sync);
    };
  }, []);

  function open(section: Section) {
    if (readRoute() === section) return;
    if (readRoute() === 'home') history.pushState({ learningHomeBehind: true }, '', '#' + section);
    else history.replaceState(history.state, '', '#' + section);
    setRoute(section);
  }

  function close() {
    if (history.state?.learningHomeBehind === true) history.back();
    else {
      history.replaceState(null, '', location.pathname + location.search);
      setRoute('home');
    }
  }

  return { route, open, close };
}
