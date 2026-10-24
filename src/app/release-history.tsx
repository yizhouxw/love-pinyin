import { useId, useRef } from 'react';
import product from '../../package.json';
import changelog from '../../content/changelog.json';
import './styles/release-history.css';

export function ReleaseHistory({ contentVersion }: { contentVersion?: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  return (
    <div className="release-history">
      <button
        className="quiet version-trigger"
        ref={trigger}
        onClick={() => dialog.current?.showModal()}
      >
        版本 {product.version}
      </button>
      <dialog ref={dialog} aria-labelledby={titleId} onClose={() => trigger.current?.focus()}>
        <div className="release-heading">
          <h2 id={titleId}>爱拼音 · 版本与更新</h2>
          <form method="dialog">
            <button className="quiet" autoFocus>
              关闭
            </button>
          </form>
        </div>
        <p>产品版本 {product.version}</p>
        {contentVersion && <p>教学内容版本：{contentVersion}</p>}
        <p>产品版本记录功能变化；教学内容版本单独管理。更新说明保存在家庭 Mac，无需联网查看。</p>
        {changelog.releases.map((release) => (
          <section key={release.version}>
            <h3>
              {release.version} · {release.title}
            </h3>
            <ul>
              {release.changes.map((change) => (
                <li key={change}>{change}</li>
              ))}
            </ul>
          </section>
        ))}
        <p>从此版本开始记录更新说明；未追补此前版本的发布日期。</p>
      </dialog>
    </div>
  );
}
