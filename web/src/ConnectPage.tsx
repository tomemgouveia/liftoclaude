import { useEffect, useState, type FormEvent } from "react";
import { getSettings, saveSettings, type Settings } from "./api";

// Status codes arrive from the settings API and, after Strava's OAuth
// redirect, as ?status= in the URL. A fixed table, so nothing from the URL
// is ever shown verbatim.
const MESSAGES: Record<string, { text: string; error: boolean }> = {
  saved: { text: "Settings saved.", error: false },
  strava_connected: { text: "Strava connected.", error: false },
  bad_key: { text: "Liftosaur rejected that API key. Check it and try again.", error: true },
  bad_timezone: { text: "That isn't a valid timezone name, e.g. Europe/London.", error: true },
  strava_denied: { text: "Strava authorization was cancelled.", error: true },
  strava_scope: {
    text: "Strava needs permission to upload activities. Connect again and leave the activity checkboxes ticked.",
    error: true,
  },
  strava_failed: { text: "Connecting to Strava failed. Please try again.", error: true },
  bad_state: { text: "That Strava link expired. Please try connecting again.", error: true },
};

const inputClass =
  "mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm " +
  "focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-500/30 " +
  "dark:border-slate-700 dark:bg-slate-900";

const primaryButton =
  "rounded-lg bg-orange-600 px-4 py-2 text-sm font-semibold text-white transition " +
  "hover:bg-orange-700 disabled:cursor-not-allowed disabled:opacity-50";

function Status({ ok, children }: { ok: boolean; children: string }) {
  return (
    <p className={`text-sm font-medium ${ok ? "text-green-700 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
      {children}
    </p>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <h2 className="mb-3 font-semibold">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

export default function ConnectPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [timezone, setTimezone] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(() => new URLSearchParams(location.search).get("status") ?? "");

  useEffect(() => {
    const controller = new AbortController();
    getSettings(controller.signal)
      .then((s) => {
        setSettings(s);
        setTimezone(s.timezone ?? guessTimezone());
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(e instanceof Error ? e.message : "Could not load settings");
        }
      });
    // Drop ?status= so a reload doesn't repeat the banner.
    if (location.search) history.replaceState(null, "", location.pathname);
    return () => controller.abort();
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const result = await saveSettings({ liftosaur_api_key: key, timezone });
      setStatus(result);
      if (result === "saved") {
        setKey("");
        setSettings((s) => s && { ...s, timezone, liftosaur_set: s.liftosaur_set || key.trim() !== "" });
      }
    } catch {
      setStatus("save_failed");
    } finally {
      setSaving(false);
    }
  }

  if (loadError) return <Status ok={false}>{loadError}</Status>;
  if (!settings) return <div className="h-48 animate-pulse rounded-xl bg-slate-200 dark:bg-slate-800" aria-busy="true" />;

  const banner = MESSAGES[status] ?? (status === "save_failed" ? { text: "Saving failed. Please try again.", error: true } : null);

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-500">
        Signed in as <strong className="text-slate-900 dark:text-slate-100">{settings.email}</strong>
      </p>
      <div aria-live="polite">{banner && <Status ok={!banner.error}>{banner.text}</Status>}</div>

      <form onSubmit={submit}>
        <Card title="Liftosaur">
          <Status ok={settings.liftosaur_set}>
            {settings.liftosaur_set ? "API key saved." : "No API key yet."}
          </Status>
          <label className="block text-sm font-medium">
            API key
            <span className="block text-xs font-normal text-slate-500">
              Liftosaur app: Settings → API Keys (needs Premium)
            </span>
            <input
              className={inputClass}
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Leave blank to keep the current key"
            />
          </label>
          <label className="block text-sm font-medium">
            Timezone
            <input
              className={inputClass}
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              placeholder="Europe/London"
              required
            />
          </label>
          <button type="submit" className={primaryButton} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </Card>
      </form>

      <Card title="Strava">
        <Status ok={settings.strava_connected}>
          {settings.strava_connected ? "Connected." : "Not connected."}
        </Status>
        <a href="/connect/strava" className={`${primaryButton} inline-block`}>
          {settings.strava_connected ? "Reconnect Strava" : "Connect Strava"}
        </a>
      </Card>
    </div>
  );
}

function guessTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "";
  }
}
