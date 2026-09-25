import { useState } from 'react';

export function App() {
  const [checked, setChecked] = useState(false);
  return (
    <main>
      <p className="eyebrow">LOVE PINYIN / DEVELOPMENT BASELINE</p>
      <h1>爱拼音</h1>
      <p className="intro">为一年级孩子，设计一段循序渐进的拼音学习旅程。</p>
      <section aria-labelledby="status-heading">
        <h2 id="status-heading">开发环境已就绪</h2>
        <p>当前是工程验证页。课程、游戏与音频将在下一阶段按 SPEC 实现。</p>
        <p className="pinyin" lang="zh-Latn-pinyin" aria-label="拼音字符显示样例">
          ā á ǎ à · ō ó ǒ ò · ī í ǐ ì · ǖ ǘ ǚ ǜ
        </p>
        <button type="button" onClick={() => setChecked(true)}>
          验证点击与键盘操作
        </button>
        <p role="status">{checked ? '交互验证成功' : '可使用触摸、鼠标，或 Tab 与 Enter。'}</p>
      </section>
      <p className="note">下一步：阅读仓库 README 与 docs/implementation-plan.md。</p>
    </main>
  );
}
