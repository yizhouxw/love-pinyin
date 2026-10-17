import { isGuest } from '../platform/guest';

export function Notice({ error, onReconnect }: { error: string; onReconnect: () => void }) {
  const guestMessages: Record<string, string> = {
    GUEST_CACHE_INVALID: '访客缓存已损坏，无法继续读取。请清除并退出访客，再重新体验。',
    GUEST_CACHE_FULL:
      '访客临时缓存已满或不可用，本次操作未缓存。原记录保持不变；可清除并退出访客后重新体验。',
    CONTENT_VERSION_UNSUPPORTED:
      '课程版本已更新，旧访客缓存无法继续使用。请清除并退出访客后重新体验。',
  };
  const message =
    (isGuest() && guestMessages[error]) ||
    (error === 'MAC_UNREACHABLE'
      ? '暂时无法连接家庭 Mac Studio，本次操作结果未确认。检查 Mac 和家庭局域网后，再点一次刚才的操作；答题会沿用原请求号，不会重复计分。'
      : `操作未完成：${error}。请检查本机服务连接后重试。`);
  return error ? (
    <div className="error-notice" role="alert">
      <p>{message}</p>
      {error === 'MAC_UNREACHABLE' && (
        <button className="quiet" onClick={onReconnect}>
          重新连接并恢复
        </button>
      )}
    </div>
  ) : null;
}
