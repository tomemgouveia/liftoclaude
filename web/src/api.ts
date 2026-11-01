export type Workout = {
  id: string;
  name: string | null;
  date: string;
  start_time: string;
  duration_s: number;
  exercises: { name: string; sets: number }[];
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function failure(response: Response): Promise<ApiError> {
  const text = await response.text();
  try {
    const body = JSON.parse(text);
    if (typeof body?.error === "string") return new ApiError(body.error, response.status);
  } catch {
    // Not JSON: the worker's plain-text message is the best we have.
  }
  return new ApiError(text || `Request failed (${response.status})`, response.status);
}

export async function listWorkouts(
  start: string,
  end: string,
  signal: AbortSignal,
): Promise<Workout[]> {
  const response = await fetch(`/api/workouts?${new URLSearchParams({ start, end })}`, {
    signal,
  });
  if (!response.ok) throw await failure(response);
  return response.json();
}

export async function syncWorkout(id: string): Promise<string> {
  const response = await fetch("/api/sync", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ workout_id: id }),
  });
  if (!response.ok) throw await failure(response);
  return response.text();
}

export type Settings = {
  email: string;
  liftosaur_set: boolean;
  strava_connected: boolean;
  timezone: string | null;
};

export async function getSettings(signal: AbortSignal): Promise<Settings> {
  const response = await fetch("/api/settings", { signal });
  if (!response.ok) throw await failure(response);
  return response.json();
}

/** Resolves with the worker's status code: "saved", "bad_key" or "bad_timezone". */
export async function saveSettings(settings: {
  liftosaur_api_key: string;
  timezone: string;
}): Promise<string> {
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (response.ok || response.status === 422) {
    return (await response.json()).status;
  }
  throw await failure(response);
}
