export function GuidanceSwitch({
  enabled,
  onChange,
  label = '语音引导',
}: {
  enabled: boolean;
  label?: string;
  onChange: (enabled: boolean) => void;
}) {
  return (
    <label className="guidance-switch">
      <input
        type="checkbox"
        aria-label="语音引导"
        checked={enabled}
        onChange={(event) => onChange(event.currentTarget.checked)}
      />
      <span>
        {label}：{enabled ? '开' : '关'}
      </span>
    </label>
  );
}
