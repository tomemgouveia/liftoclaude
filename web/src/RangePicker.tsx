import { daysAgo, toInputDate } from "./dates";

export type Range = { start: string; end: string };

const PRESETS = [
  { label: "7 days", days: 6 },
  { label: "30 days", days: 29 },
  { label: "90 days", days: 89 },
];

export function presetRange(days: number): Range {
  return { start: daysAgo(days), end: toInputDate(new Date()) };
}

const inputClass =
  "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm " +
  "focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-500/30 " +
  "dark:border-slate-700 dark:bg-slate-900";

export function RangePicker({
  range,
  onChange,
}: {
  range: Range;
  onChange: (range: Range) => void;
}) {
  const today = toInputDate(new Date());
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="flex gap-1.5">
        {PRESETS.map(({ label, days }) => {
          const preset = presetRange(days);
          const active = preset.start === range.start && preset.end === range.end;
          return (
            <button
              key={label}
              type="button"
              onClick={() => onChange(preset)}
              className={
                "rounded-full px-3 py-1.5 text-sm font-medium transition " +
                (active
                  ? "bg-orange-600 text-white"
                  : "bg-slate-200 text-slate-700 hover:bg-slate-300 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700")
              }
            >
              {label}
            </button>
          );
        })}
      </div>
      <label className="text-xs font-medium text-slate-500">
        From
        <input
          type="date"
          className={`${inputClass} mt-1 block`}
          value={range.start}
          max={range.end}
          onChange={(e) => e.target.value && onChange({ ...range, start: e.target.value })}
        />
      </label>
      <label className="text-xs font-medium text-slate-500">
        To
        <input
          type="date"
          className={`${inputClass} mt-1 block`}
          value={range.end}
          min={range.start}
          max={today}
          onChange={(e) => e.target.value && onChange({ ...range, end: e.target.value })}
        />
      </label>
    </div>
  );
}
