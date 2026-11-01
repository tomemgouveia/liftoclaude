import { useEffect, useState } from "react";
import { ApiError, listWorkouts, syncWorkout, type Workout } from "./api";
import { presetRange, RangePicker, type Range } from "./RangePicker";
import { WorkoutCard, type SyncState } from "./WorkoutCard";

type Load =
  | { kind: "loading" }
  | { kind: "ready"; workouts: Workout[] }
  | { kind: "error"; message: string; needsSetup: boolean };

export default function SyncPage() {
  const [range, setRange] = useState<Range>(() => presetRange(6));
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [sync, setSync] = useState<Record<string, SyncState>>({});
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoad({ kind: "loading" });
    listWorkouts(range.start, range.end, controller.signal)
      .then((workouts) => setLoad({ kind: "ready", workouts }))
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        const status = e instanceof ApiError ? e.status : 0;
        setLoad({
          kind: "error",
          message: e instanceof Error ? e.message : "Could not load workouts",
          needsSetup: status === 404,
        });
      });
    return () => controller.abort();
  }, [range]);

  const busy = Object.values(sync).some((s) => s.kind === "syncing");

  async function push(workout: Workout) {
    setNotice(null);
    setSync((s) => ({ ...s, [workout.id]: { kind: "syncing" } }));
    try {
      const text = await syncWorkout(workout.id);
      setSync((s) => ({ ...s, [workout.id]: { kind: "done" } }));
      setNotice({ ok: true, text });
    } catch (e) {
      const message = e instanceof Error ? e.message : "Sync failed";
      // 409: Strava already has it, so there's nothing left to do.
      const duplicate = e instanceof ApiError && e.status === 409;
      setSync((s) => ({
        ...s,
        [workout.id]: duplicate ? { kind: "done" } : { kind: "error", message },
      }));
      setNotice({ ok: duplicate, text: message });
    }
  }

  return (
    <>
      <RangePicker range={range} onChange={setRange} />

      <div aria-live="polite" className="mt-4 min-h-6 text-sm">
        {notice && (
          <p className={notice.ok ? "text-green-700 dark:text-green-400" : "text-red-600 dark:text-red-400"}>
            {notice.text}
          </p>
        )}
      </div>

      <section className="mt-2">
        {load.kind === "loading" && (
          <ul className="space-y-3" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <li key={i} className="h-20 animate-pulse rounded-xl bg-slate-200 dark:bg-slate-800" />
            ))}
          </ul>
        )}
        {load.kind === "error" && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            {load.message}
            {load.needsSetup && (
              <>
                {" "}
                <a href="/connect" className="font-semibold underline">
                  Finish setup
                </a>
              </>
            )}
          </div>
        )}
        {load.kind === "ready" &&
          (load.workouts.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-slate-500 dark:border-slate-700">
              No workouts in this range.
            </p>
          ) : (
            <ul className="space-y-3">
              {load.workouts.map((w) => (
                <WorkoutCard
                  key={w.id}
                  workout={w}
                  state={sync[w.id] ?? { kind: "idle" }}
                  disabled={busy}
                  onSync={() => push(w)}
                />
              ))}
            </ul>
          ))}
      </section>
    </>
  );
}
