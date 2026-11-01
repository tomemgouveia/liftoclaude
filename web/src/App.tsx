import ConnectPage from "./ConnectPage";
import SyncPage from "./SyncPage";

export default function App() {
  const settings = location.pathname.replace(/\/$/, "") === "/connect";
  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">
          {settings ? "Settings" : "Sync to Strava"}
        </h1>
        <a href={settings ? "/" : "/connect"} className="text-sm text-slate-500 hover:underline">
          {settings ? "← Back to sync" : "Settings"}
        </a>
      </header>
      {settings ? <ConnectPage /> : <SyncPage />}
    </main>
  );
}
