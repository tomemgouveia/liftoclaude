import type { Workout } from "./api";
import { formatDate, formatDuration } from "./dates";

export type SyncState =
  | { kind: "idle" }
  | { kind: "syncing" }
  | { kind: "done" }
  | { kind: "error"; message: string };

export function WorkoutCard({
  workout,
  state,
  disabled,
  onSync,
}: {
  workout: Workout;
  state: SyncState;
  disabled: boolean;
  onSync: () => void;
}) {
  const sets = workout.exercises.reduce((n, e) => n + e.sets, 0);
  const done = state.kind === "done";
  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="truncate font-semibold">{workout.name ?? "Workout"}</h2>
          <p className="text-sm text-slate-500">
            {formatDate(workout.date)} · {formatDuration(workout.duration_s)} ·{" "}
            {workout.exercises.length} exercises · {sets} sets
          </p>
        </div>
        <button
          type="button"
          onClick={onSync}
          disabled={disabled || done || state.kind === "syncing"}
          className={
            "shrink-0 rounded-lg px-4 py-1.5 text-sm font-semibold transition disabled:cursor-not-allowed " +
            (done
              ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"
              : "bg-orange-600 text-white hover:bg-orange-700 disabled:opacity-50")
          }
        >
          {state.kind === "syncing" ? "Syncing…" : done ? "Synced ✓" : "Sync"}
        </button>
      </div>
      {workout.exercises.length > 0 && (
        <p className="mt-2 truncate text-sm text-slate-600 dark:text-slate-400">
          {workout.exercises.map((e) => e.name).join(" · ")}
        </p>
      )}
      {state.kind === "error" && (
        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
          {state.message}
        </p>
      )}
    </li>
  );
}
