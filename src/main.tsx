import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { lazy, Suspense } from 'react';
import { isIOSApp } from './platform/ios-app';
import { App } from './app/App';
import './app/styles.css';

const IOSListeningLibrary = lazy(() =>
  import('./app/ios-listening-library').then((module) => ({ default: module.IOSListeningLibrary })),
);
const root = document.getElementById('root');
if (!root) throw new Error('缺少应用挂载节点');
createRoot(root).render(
  <StrictMode>
    {isIOSApp() ? (
      <Suspense fallback={<p role="status">正在打开本机课程…</p>}>
        <IOSListeningLibrary />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>,
);
