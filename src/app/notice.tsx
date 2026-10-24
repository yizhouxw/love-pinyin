const messages: Record<string, string> = {
  MAC_UNREACHABLE:
    '暂时无法连接家庭 Mac。检查 Mac 是否运行、设备是否连着家庭网络，再重新连接；本次操作尚未确认，重试不会重复计分。',
  PAIRING_CODE_INVALID: '配对码已失效或输入有误。请核对配对码，或在服务器 Mac 重新生成后输入。',
  PAIRING_COOLDOWN: '尝试连接次数较多。请等一分钟，核对配对码后再连接。',
  HOUSEHOLD_NOT_READY: '家庭档案尚未准备好。请在服务器 Mac 重新生成配对码后连接。',
  PAIRING_REQUIRED: '此设备还未连接家庭。请重新打开首页并输入家长配对码。',
  SESSION_EXPIRED: '连接已过期。请重新打开首页并配对，再继续学习。',
  PARENT_AUTH_REQUIRED: '这个操作需要家长权限。请在服务器 Mac 的家长管理中操作。',
  PARENT_LOCAL_REQUIRED: '请在服务器 Mac 打开本机入口 http://127.0.0.1:8000，再进行家长操作。',
  REVISION_CONFLICT: '其他设备已更新家庭记录。请重新连接刷新，再检查并重试刚才的操作。',
  BACKUP_TOO_LARGE: '备份文件超过 1 MiB。请选择由本应用导出的家庭 JSON 备份。',
  BACKUP_INVALID: '这份文件不是可用的家庭备份。请选择由本应用导出的 JSON 备份。',
  IMPORT_PREVIEW_EXPIRED: '备份预览已过期。请重新选择备份文件，检查预览后确认恢复。',
  IMPORT_PREVIEW_MISMATCH: '备份或家庭记录已改变。请重新选择文件并检查恢复预览。',
  IMPORT_PREVIEW_LIMIT: '备份预览次数较多。请稍后重新选择文件。',
  CONFIRMATION_REQUIRED: '确认文字不完整。请按操作旁的要求输入完整文字。',
  DEVICE_NOT_FOUND: '这个设备已被移除。请刷新设备列表。',
  CANNOT_REVOKE_CURRENT_DEVICE: '无法在这里撤销当前设备。可使用下方“退出此设备配对”。',
  CURRENT_LESSON_REQUIRES_SELECTION: '已保存的课程不在当前版本中。请由家长重新选择当前课程。',
  LESSON_NOT_UNLOCKED: '这课还未开放。请学习当前课，或请家长调整学校当前课程。',
  LESSON_NOT_READY: '这课的声音或题目尚未准备好。请家长检查学习音频，暂时选择其他已开放课程。',
  REST_REQUIRED: '已经完成两轮练习，先休息一下，再回到学习页继续。',
  EXERCISE_NOT_READY: '这道题的内容尚未准备好。请先跳过，或请家长检查课程声音。',
  LESSON_NOT_FOUND: '这课已不在当前教材中。已有记录会保留，请家长重新选择当前课程。',
  KNOWLEDGE_NOT_FOUND: '这项学习内容已更新。请返回课程页，选择当前可用的内容。',
  INSTANCE_NOT_FOUND: '这道题已无法继续读取。请重新连接恢复练习。',
  SESSION_NOT_FOUND: '这轮练习已结束或已更新。请回到首页继续学习。',
  SESSION_NOT_ACTIVE: '这轮练习已经结束。请回到首页开始新一轮。',
  INSTANCE_ALREADY_ANSWERED: '这道题已经保存过答案。请重新连接恢复当前进度。',
  INSTANCE_ALREADY_SKIPPED: '这道题已跳过。请重新连接，继续下一题。',
  OPTION_NOT_VALID: '题目选项已变化。请重新连接恢复当前题目，再选择答案。',
  IDEMPOTENCY_KEY_REUSED: '这次提交与上次不一致。请先重新连接恢复上一题，避免重复保存。',
  REVIEW_CONTENT_INSUFFICIENT: '这项复习的题目尚未准备好。可以先按当前课程学习。',
  REVIEW_NOT_DUE: '这项内容暂时不用复习，可以继续当前课程。',
  REVIEW_NOT_SCHEDULED: '这项内容还没有复习安排，可以先按课程练一练。',
  REVIEW_TODAY_EXHAUSTED: '今天已练过这项复习，可以继续其他内容或休息。',
  ATTEMPT_CURSOR_NOT_FOUND: '学习记录已变化。请收起后重新打开这项记录。',
  ATTEMPT_NOT_FOUND: '这条学习记录暂时无法读取。请重新连接后再查看。',
  CLOCK_NOT_RESTORED: 'Mac的时间仍不正常。请家长校准系统时间，再处理待确认记录。',
  GUEST_OPERATION_UNAVAILABLE: '访客体验不能管理家庭档案。请先连接家庭，再由家长在Mac操作。',
  GUEST_CACHE_INVALID: '访客缓存无法读取。请清除并退出访客，再重新体验。',
  GUEST_CACHE_FULL: '访客临时缓存已满或不可用，本次操作未保存。请清除并退出访客后重新体验。',
  CONTENT_VERSION_UNSUPPORTED: '课程版本已更新。请清除并退出访客后重新体验。',
};

export function errorMessage(error: string): string {
  if (messages[error]) return messages[error];
  if (error.startsWith('BACKUP_')) return messages.BACKUP_INVALID!;
  if (error.startsWith('CSRF_') || error === 'ORIGIN_REJECTED')
    return '页面连接验证已失效。请重新打开家庭 Mac 提供的入口，再试一次。';
  if (error.includes('AUDIO_NOT_FOUND'))
    return '声音文件尚未就绪。请家长在 Mac 检查音频；可以重听或跳过，不计为答错。';
  return '这次操作没有完成。请检查输入和家庭 Mac 连接，再重试刚才的操作；若仍失败，可将技术详情提供给家长。';
}

export function Notice({ error, onReconnect }: { error: string; onReconnect: () => void }) {
  return error ? (
    <div className="error-notice" role="alert">
      <p>{errorMessage(error)}</p>
      {[
        'MAC_UNREACHABLE',
        'REVISION_CONFLICT',
        'INSTANCE_NOT_FOUND',
        'INSTANCE_ALREADY_ANSWERED',
        'INSTANCE_ALREADY_SKIPPED',
        'OPTION_NOT_VALID',
        'IDEMPOTENCY_KEY_REUSED',
      ].includes(error) && (
        <button type="button" className="quiet" onClick={onReconnect}>
          重新连接并恢复
        </button>
      )}
      <details>
        <summary>技术详情</summary>
        <code>{error}</code>
      </details>
    </div>
  ) : null;
}
