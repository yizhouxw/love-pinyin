const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="review-token"]').content;
let catalog;
let saved = null;
let previewUrl = null;
const message = (text, error = false) => {
  $('status').textContent = text;
  $('status').classList.toggle('error', error);
};
async function request(path, data, binary = false) {
  const response = await fetch(
    `/api/${path}`,
    data === undefined
      ? {}
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Review-Token': token },
          body: JSON.stringify(data),
        },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    const detail = error?.detail;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : `操作未完成（${response.status}），请检查范围或刷新资料。`,
    );
  }
  return binary ? response.blob() : response.json();
}
function option(select, value, label) {
  const item = document.createElement('option');
  item.value = value;
  item.textContent = label;
  select.append(item);
}
function clip() {
  return {
    sourceId: $('source').value,
    start: Number($('start').value),
    end: Number($('end').value),
  };
}
function resetConfirmation() {
  saved = null;
  for (const id of ['target-ok', 'quality-ok', 'private-ok']) $(id).checked = false;
  $('activate').disabled = true;
  $('draft-status').textContent = '尚未保存当前裁切；修改后必须重新试听和核对。';
  $('preview-audio').pause();
  $('preview-audio').removeAttribute('src');
  $('preview-audio').load();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
}
function activeState() {
  const target = catalog.targets.find((row) => row.id === $('target').value);
  $('active-status').textContent = target?.available
    ? '此目标已有已确认的家庭标准音。新草稿不会替换它，直到重新核对并启用。'
    : '此目标尚未启用家庭标准音。';
  $('deactivate').disabled = !target?.activeSha256;
}
function candidates() {
  const query = $('search').value.trim().toLowerCase();
  $('candidate').replaceChildren();
  for (const row of catalog.candidates.filter(
    (row) =>
      row.sourceId === $('source').value &&
      `${row.id} ${row.transcriptDraft}`.toLowerCase().includes(query),
  )) {
    option(
      $('candidate'),
      row.id,
      `${row.start.toFixed(2)}–${row.end.toFixed(2)}秒 · ${row.transcriptDraft || '无可靠转写，请听原音'}`,
    );
  }
}
function selectSource() {
  $('original').pause();
  $('original').src = `/api/source/${encodeURIComponent($('source').value)}`;
  resetConfirmation();
  candidates();
  const row = catalog.sources.find((item) => item.id === $('source').value);
  $('start').max = $('end').max = String(row.duration);
  $('transcript').textContent = `原文件：${row.name} · ${row.duration.toFixed(2)}秒`;
}
async function run(action) {
  $('workspace').disabled = true;
  try {
    await action();
  } catch (error) {
    message(error.message, true);
  } finally {
    $('workspace').disabled = false;
  }
}
$('source').onchange = selectSource;
$('search').oninput = candidates;
$('candidate').onchange = () => {
  const row = catalog.candidates.find((item) => item.id === $('candidate').value);
  if (!row) return;
  resetConfirmation();
  $('start').value = row.start;
  $('end').value = row.end;
  $('transcript').textContent = `机器转写草稿（可能有误）：${row.transcriptDraft || '无'}`;
};
for (const id of ['start', 'end']) $(id).oninput = resetConfirmation;
$('target').onchange = () => {
  resetConfirmation();
  activeState();
  const draft = catalog.drafts[$('target').value];
  if (draft) {
    $('source').value = draft.sourceId;
    selectSource();
    $('start').value = draft.start;
    $('end').value = draft.end;
    saved = draft;
    $('draft-status').textContent =
      `已加载保存的草稿：${draft.start}–${draft.end}秒；请重新试听后核对。`;
  }
};
$('seek').onclick = () =>
  run(async () => {
    $('preview-audio').pause();
    $('original').currentTime = Number($('start').value);
    await $('original').play();
  });
$('preview').onclick = () =>
  run(async () => {
    $('original').pause();
    $('preview-audio').pause();
    const blob = await request('preview', clip(), true);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob);
    $('preview-audio').src = previewUrl;
    await $('preview-audio').play();
    message('正在试听当前裁切，请核对完整声音和边界。');
  });
$('save').onclick = () =>
  run(async () => {
    if (!$('target').value) throw new Error('请先选择实际听到的标准音目标。');
    saved = await request('draft', {
      ...clip(),
      targetId: $('target').value,
      expectedRevision: catalog.drafts[$('target').value]?.revision ?? null,
    });
    catalog.drafts[saved.id] = saved;
    $('draft-status').textContent = `草稿已保存：${saved.start}–${saved.end}秒；尚未启用。`;
    for (const id of ['target-ok', 'quality-ok', 'private-ok']) $(id).checked = false;
    $('activate').disabled = true;
    message('草稿已保存。请完成教学和音质核对后再启用。');
  });
function canConfirm() {
  $('activate').disabled =
    !saved ||
    !['target-ok', 'quality-ok', 'private-ok'].every((id) => $(id).checked) ||
    !$('teaching').value.trim() ||
    !$('quality').value.trim() ||
    $('teaching').value.trim().toLowerCase() === $('quality').value.trim().toLowerCase();
}
for (const id of ['target-ok', 'quality-ok', 'private-ok', 'teaching', 'quality'])
  $(id).oninput = canConfirm;
$('activate').onclick = () =>
  run(async () => {
    if (!saved) throw new Error('请先保存当前裁切。');
    await request('activate', {
      targetId: saved.id,
      sha256: saved.sha256,
      revision: saved.revision,
      teachingReviewer: $('teaching').value.trim(),
      qualityReviewer: $('quality').value.trim(),
      targetAndPronunciationConfirmed: $('target-ok').checked,
      qualityAndBoundariesConfirmed: $('quality-ok').checked,
      privateUseOnly: $('private-ok').checked,
    });
    catalog = await request('catalog');
    activeState();
    message('已启用到本家庭。孩子的新练习可以使用此标准音；公开发布状态未改变。');
  });
$('deactivate').onclick = () =>
  run(async () => {
    const target = catalog.targets.find((row) => row.id === $('target').value);
    await request('deactivate', { targetId: target.id, sha256: target.activeSha256 });
    catalog = await request('catalog');
    activeState();
    message('已从家庭练习撤下，源音和草稿仍保留。');
  });
for (const [id, other] of [
  ['original', 'preview-audio'],
  ['preview-audio', 'original'],
]) {
  $(id).onplay = () => $(other).pause();
}
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    $('original').pause();
    $('preview-audio').pause();
  }
});
await run(async () => {
  catalog = await request('catalog');
  for (const row of catalog.sources) option($('source'), row.id, row.name);
  for (const row of catalog.targets)
    option($('target'), row.id, `${row.label} · ${row.kind} · ${row.id}`);
  if (catalog.sources.length) selectSource();
  message(
    `${catalog.sources.length}份课程录音，${catalog.candidates.length}段待听候选，${catalog.targets.filter((row) => row.available).length}个目标已启用。`,
  );
});
