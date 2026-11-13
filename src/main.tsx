import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { audioPlayer } from './platform/audio/browser-audio-player';
import { isNativeApp } from './platform/ios-app';
import { App } from './app/App';
import './app/styles.css';

if (isNativeApp()) {
  document.documentElement.dataset.iosApp = '';
  window.addEventListener('lp-ios-audio-interrupted', () => audioPlayer.stop());
  window.addEventListener('lp-native-audio-interrupted', () => audioPlayer.stop());
}
const root = document.getElementById('root');
if (!root) throw new Error('缺少应用挂载节点');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
