export function GuidanceSwitch({
  enabled,
  onChange,
}: {
  enabled: boolean;
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
      <span>语音引导：{enabled ? '开' : '关'}</span>
    </label>
  );
}
