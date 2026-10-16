import { useRef, useState } from 'react';

export function CopyCode({ code, label }: { code: string; label: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  async function copy() {
    setBusy(true);
    try {
      await navigator.clipboard.writeText(code);
      setStatus('已复制');
    } catch {
      input.current?.focus();
      input.current?.select();
      setStatus('自动复制不可用，已选中配对码，请长按或按复制快捷键。');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="copy-code">
      <input
        ref={input}
        aria-label={label}
        value={code}
        readOnly
        onFocus={(event) => event.target.select()}
      />
      <button className="quiet" type="button" disabled={busy} onClick={() => void copy()}>
        复制配对码
      </button>
      {status && <small role="status">{status}</small>}
    </div>
  );
}
