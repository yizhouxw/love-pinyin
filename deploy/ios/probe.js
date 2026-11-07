const status = document.querySelector('#status');
const sample = document.querySelector('#sample');
const native = window.webkit.messageHandlers.learning;
const call = (operation) => native.postMessage({ version: 1, operation });
let objectURL;
let shortRequest;

function stopShort() {
  shortRequest?.abort();
  shortRequest = undefined;
  sample.pause();
  sample.removeAttribute('src');
  if (objectURL) URL.revokeObjectURL(objectURL);
  objectURL = undefined;
}

function action(id, run) {
  document.querySelector(id).addEventListener('click', () => {
    run().catch((error) => {
      if (error.name !== 'AbortError') status.textContent = `操作失败：${error.message}`;
    });
  });
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopShort();
});

action('#short', async () => {
  stopShort();
  const request = new AbortController();
  shortRequest = request;
  await call('stop');
  const response = await fetch('./probe-audio', { signal: request.signal });
  if (!response.ok) throw new Error('离线音频不可用');
  const clip = await response.blob();
  if (request.signal.aborted) return;
  objectURL = URL.createObjectURL(clip);
  sample.src = objectURL;
  await sample.play();
  status.textContent = '正在播放拼音示范';
});
action('#long', async () => {
  stopShort();
  await call('playLesson');
  status.textContent = '已请求播放包内课程录音';
});
action('#seek', async () => {
  await call('seekLesson');
  status.textContent = '已请求定位到第 10 秒';
});
action('#stop', async () => {
  stopShort();
  await call('stop');
  status.textContent = '已停止';
});

call('bootstrap').then(
  (data) => {
    status.textContent = `已读取 ${data.lessonCount} 课和 ${data.audioCount} 条登记音频`;
  },
  (error) => {
    status.textContent = `资源读取失败：${error.message}`;
  },
);
