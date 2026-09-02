import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Grid, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Icon, IconName } from "../components/Icons";
import RadiationPattern from "../components/RadiationPattern";
import SParamPlot, { SParamData } from "../components/SParamPlot";
import { useI18n } from "../i18n";
import { C0, dipolePattern, dipoleResonanceHz, dipoleS11Sweep } from "../lib/dipole";
import { useSocket } from "../lib/socket";

const Dipole: React.FC<{ length: number }> = ({ length }) => {
  const arm = length / 2;
  return (
    <group>
      <mesh position={[0, arm / 2 + length * 0.01, 0]}>
        <cylinderGeometry args={[0.0011, 0.0011, arm, 28]} />
        <meshStandardMaterial color="#dce3df" metalness={0.95} roughness={0.22} />
      </mesh>
      <mesh position={[0, -arm / 2 - length * 0.01, 0]}>
        <cylinderGeometry args={[0.0011, 0.0011, arm, 28]} />
        <meshStandardMaterial color="#dce3df" metalness={0.95} roughness={0.22} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.0017, 24, 24]} />
        <meshStandardMaterial color="#54e6b5" emissive="#54e6b5" emissiveIntensity={2.2} />
      </mesh>
      <pointLight position={[0, 0, 0]} intensity={0.8} color="#54e6b5" distance={0.12} />
    </group>
  );
};

interface SimResultPayload {
  solver_mode?: string;
  s_params?: {
    frequency?: number[];
    s_matrix?: { re: number; im: number }[][][] | number[][][];
  };
}

interface StepProps {
  index: number;
  label: string;
  state: "done" | "active" | "pending";
  last?: boolean;
}

const Step: React.FC<StepProps> = ({ index, label, state, last = false }) => (
  <div className="flex min-w-0 flex-1 items-center">
    <div className="flex min-w-0 items-center gap-2.5">
      <span
        className={`grid size-6 shrink-0 place-items-center rounded-full border font-mono text-[9px] ${
          state === "done"
            ? "border-signal-400/40 bg-signal-400/10 text-signal-300"
            : state === "active"
              ? "border-signal-300 bg-signal-400 text-ink-950 shadow-[0_0_18px_rgba(84,230,181,0.25)]"
              : "border-white/10 bg-white/[0.025] text-white/28"
        }`}
      >
        {state === "done" ? <Icon name="check" size={12} strokeWidth={2.4} /> : index}
      </span>
      <span className={`truncate text-[11px] font-medium sm:text-xs ${state === "pending" ? "text-white/28" : "text-white/70"}`}>{label}</span>
    </div>
    {!last ? <span className={`mx-3 h-px flex-1 ${state === "done" ? "bg-signal-400/25" : "bg-white/[0.07]"}`} /> : null}
  </div>
);

const Metric: React.FC<{ icon: IconName; label: string; value: string }> = ({ icon, label, value }) => (
  <div className="flex items-center gap-3 border-t border-white/[0.065] px-4 py-3.5 first:border-t-0 sm:border-l sm:border-t-0 sm:first:border-l-0">
    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white/[0.035] text-white/35">
      <Icon name={icon} size={15} />
    </span>
    <span className="min-w-0">
      <span className="block text-[10px] uppercase tracking-[0.12em] text-white/28">{label}</span>
      <span className="mt-0.5 block truncate font-mono text-xs text-white/82">{value}</span>
    </span>
  </div>
);

const POLL_MS = 2_000;
const POLL_MAX = 90;

const DesignEditor: React.FC = () => {
  const { t } = useI18n();
  const { lastEvent } = useSocket();
  const [designName, setDesignName] = useState("half-wave-dipole");
  const [freqGhz, setFreqGhz] = useState("2.4");
  const [dipoleLength, setDipoleLength] = useState(0.0594);
  const [solver, setSolver] = useState<"nec2" | "openems">("nec2");
  const [running, setRunning] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [solverData, setSolverData] = useState<SParamData | null>(null);
  const [solverMode, setSolverMode] = useState<string | null>(null);
  const [tab, setTab] = useState<"sparams" | "pattern">("sparams");
  const pollRef = useRef<number | null>(null);

  const fc = (parseFloat(freqGhz) || 2.4) * 1e9;
  const preview = useMemo(() => dipoleS11Sweep(dipoleLength, fc * 0.75, fc * 1.25), [dipoleLength, fc]);
  const pattern = useMemo(() => dipolePattern(dipoleLength, fc), [dipoleLength, fc]);
  const previewData = useMemo<SParamData>(() => ({ frequency: preview.frequency, s11: preview.s11, z0: 50 }), [preview]);

  useEffect(() => () => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current);
  }, []);

  const invalidateSolverResult = () => {
    setSolverData(null);
    setSolverMode(null);
    if (!running) setStatusText(null);
  };

  const handleSimulate = async () => {
    setRunning(true);
    setStatusText(t("submitting"));
    if (pollRef.current !== null) window.clearInterval(pollRef.current);

    try {
      const response = await fetch("/api/v1/simulations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          design_id: "00000000-0000-0000-0000-000000000001",
          solver,
          frequency_min: fc * 0.75,
          frequency_max: fc * 1.25,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const job = (await response.json()) as { id: string };
      setStatusText(`${t("jobSubmitted")} · ${String(job.id).slice(0, 8)}`);

      let attempts = 0;
      pollRef.current = window.setInterval(async () => {
        attempts += 1;
        if (attempts > POLL_MAX) {
          if (pollRef.current !== null) window.clearInterval(pollRef.current);
          setRunning(false);
          setStatusText(`${t("simError")}: timeout`);
          return;
        }
        try {
          const resultResponse = await fetch(`/api/v1/simulations/${job.id}/result`);
          if (!resultResponse.ok) return;
          const result = (await resultResponse.json()) as SimResultPayload;
          if (pollRef.current !== null) window.clearInterval(pollRef.current);
          setRunning(false);
          setStatusText(t("simComplete"));
          setSolverMode(result.solver_mode ?? solver);
          if (result.s_params?.frequency && result.s_params.s_matrix) {
            setSolverData({ frequency: result.s_params.frequency, sMatrix: result.s_params.s_matrix, z0: 50 });
          }
        } catch {
          // A transient polling failure should not terminate an active solver job.
        }
      }, POLL_MS);
    } catch (error) {
      setRunning(false);
      setStatusText(`${t("simError")}: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const lambdaHalf = C0 / (2 * fc);
  const resonanceGhz = dipoleResonanceHz(dipoleLength) / 1e9;
  const lengthPct = ((dipoleLength - 0.01) / 0.19) * 100;
  const usingSolverData = solverData !== null;
  const statusTone = statusText?.startsWith(t("simError"))
    ? "text-red-300"
    : running
      ? "text-amber-200"
      : statusText === t("simComplete")
        ? "text-signal-300"
        : "text-white/65";

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-white/[0.065] bg-ink-850/70 px-4 py-3.5 shadow-panel sm:px-5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 flex-1 items-center">
            <Step index={1} label={t("geometry")} state="done" />
            <Step index={2} label={t("analyticalPreview")} state={usingSolverData ? "done" : "active"} />
            <Step index={3} label={t("fullWaveValidation")} state={usingSolverData ? "done" : running ? "active" : "pending"} last />
          </div>
          <span className="hidden rounded-full border border-white/[0.07] px-2.5 py-1 font-mono text-[9px] uppercase tracking-widest text-white/30 md:inline">{t("unsavedDraft")}</span>
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="panel-highlight relative overflow-hidden rounded-2xl border border-white/[0.07] bg-ink-850 shadow-panel">
          <div className="relative z-10 flex items-center justify-between border-b border-white/[0.06] px-4 py-3.5 sm:px-5">
            <div className="flex items-center gap-3">
              <span className="grid size-8 place-items-center rounded-lg border border-white/[0.07] bg-white/[0.03] text-signal-300">
                <Icon name="cube" size={16} />
              </span>
              <div>
                <h2 className="text-xs font-semibold text-white/85">{t("viewport")}</h2>
                <p className="mt-0.5 text-[10px] text-white/30">{t("viewportHint")}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-widest text-signal-300/70">
              <span className="size-1.5 rounded-full bg-signal-400 shadow-[0_0_8px_#54e6b5]" />
              {t("analyticalPreview")}
            </div>
          </div>

          <div className="grid-surface relative h-[430px] overflow-hidden sm:h-[500px]">
            <Canvas camera={{ position: [0.1, 0.06, 0.12], fov: 42 }}>
              <color attach="background" args={["#0b0e0f"]} />
              <fog attach="fog" args={["#0b0e0f", 0.22, 0.72]} />
              <ambientLight intensity={0.42} />
              <directionalLight position={[5, 8, 5]} intensity={1.05} />
              <Grid
                args={[20, 20]}
                position={[0, -0.055, 0]}
                cellSize={0.01}
                cellThickness={0.45}
                cellColor="#1c2523"
                sectionSize={0.05}
                sectionThickness={0.85}
                sectionColor="#2b3835"
                fadeDistance={0.85}
                infiniteGrid
              />
              <Suspense fallback={null}><Dipole length={dipoleLength} /></Suspense>
              <OrbitControls autoRotate autoRotateSpeed={0.45} enableDamping dampingFactor={0.1} />
            </Canvas>
            <div className="pointer-events-none absolute left-4 top-4 rounded-lg border border-white/[0.07] bg-black/30 px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-wider text-white/35 backdrop-blur-md">
              Y axis · center feed
            </div>
            <div className="pointer-events-none absolute bottom-4 right-4 flex items-center gap-2 rounded-lg border border-white/[0.07] bg-black/30 px-2.5 py-1.5 text-[10px] text-white/35 backdrop-blur-md">
              <Icon name="refresh" size={12} />
              AUTO ORBIT
            </div>
          </div>

          <div className="grid sm:grid-cols-3">
            <Metric icon="radio" label={t("halfWave")} value={`${(lambdaHalf * 1000).toFixed(1)} mm`} />
            <Metric icon="activity" label={t("resonance")} value={`${resonanceGhz.toFixed(2)} GHz`} />
            <Metric icon="signal" label={t("minS11")} value={`${preview.minS11Db.toFixed(1)} dB`} />
          </div>
        </section>

        <aside className="self-start overflow-hidden rounded-2xl border border-white/[0.07] bg-ink-850 shadow-panel">
          <div className="flex items-center gap-3 border-b border-white/[0.06] px-5 py-4">
            <span className="grid size-8 place-items-center rounded-lg bg-signal-400/10 text-signal-300"><Icon name="settings" size={16} /></span>
            <div>
              <h2 className="text-xs font-semibold text-white/85">{t("parameters")}</h2>
              <p className="mt-0.5 text-[10px] text-white/30">{t("parametersHint")}</p>
            </div>
          </div>

          <div className="space-y-5 p-5">
            <label className="block">
              <span className="mb-2 block text-[11px] font-medium text-white/48">{t("designName")}</span>
              <input
                type="text"
                value={designName}
                onChange={(event) => setDesignName(event.target.value)}
                className="w-full rounded-xl border border-white/[0.08] bg-black/20 px-3.5 py-2.5 text-xs text-white/85 placeholder:text-white/20 transition-colors hover:border-white/[0.14] focus:border-signal-400/50 focus:outline-none"
              />
            </label>

            <label className="block">
              <span className="mb-2 flex items-center justify-between text-[11px] font-medium text-white/48">
                {t("centerFreq")}<span className="font-mono text-[10px] text-white/25">GHz</span>
              </span>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="100"
                value={freqGhz}
                onChange={(event) => { setFreqGhz(event.target.value); invalidateSolverResult(); }}
                className="w-full rounded-xl border border-white/[0.08] bg-black/20 px-3.5 py-2.5 font-mono text-xs text-white/85 transition-colors hover:border-white/[0.14] focus:border-signal-400/50 focus:outline-none"
              />
            </label>

            <label className="block">
              <span className="mb-2 flex items-center justify-between text-[11px] font-medium text-white/48">
                {t("dipoleLength")}<span className="font-mono text-[10px] text-signal-300">{(dipoleLength * 1000).toFixed(1)} mm</span>
              </span>
              <input
                type="range"
                min="0.01"
                max="0.2"
                step="0.0005"
                value={dipoleLength}
                onChange={(event) => { setDipoleLength(parseFloat(event.target.value)); invalidateSolverResult(); }}
                style={{ "--range-pct": `${lengthPct}%` } as React.CSSProperties}
                className="range-control my-2"
              />
              <div className="flex justify-between font-mono text-[9px] text-white/20"><span>10 mm</span><span>200 mm</span></div>
            </label>

            <label className="block">
              <span className="mb-2 block text-[11px] font-medium text-white/48">{t("solver")}</span>
              <div className="relative">
                <select
                  value={solver}
                  onChange={(event) => { setSolver(event.target.value as "nec2" | "openems"); invalidateSolverResult(); }}
                  className="w-full appearance-none rounded-xl border border-white/[0.08] bg-black/20 px-3.5 py-2.5 pr-9 text-xs text-white/85 transition-colors hover:border-white/[0.14] focus:border-signal-400/50 focus:outline-none"
                >
                  <option value="nec2">NEC2 — {t("nec2Description")}</option>
                  <option value="openems">openEMS — {t("openemsDescription")}</option>
                </select>
                <Icon name="chevron-down" size={14} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-white/30" />
              </div>
            </label>

            <button
              onClick={() => void handleSimulate()}
              disabled={running}
              className="group flex w-full items-center justify-center gap-2 rounded-xl bg-signal-400 px-4 py-3 text-xs font-semibold text-ink-950 shadow-[0_10px_30px_rgba(84,230,181,0.12)] transition-all hover:bg-signal-300 hover:shadow-[0_12px_36px_rgba(84,230,181,0.2)] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-55"
            >
              <Icon name={running ? "activity" : "play"} size={15} className={running ? "animate-pulse" : "transition-transform group-hover:translate-x-0.5"} />
              {running ? t("running") : t("runSimulation")}
            </button>

            <div className="rounded-xl border border-white/[0.065] bg-black/15 p-3.5">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[10px] uppercase tracking-[0.13em] text-white/28">{t("statusTitle")}</span>
                <span className={`size-1.5 rounded-full ${running ? "animate-pulse bg-amber-300" : usingSolverData ? "bg-signal-400" : "bg-white/20"}`} />
              </div>
              <p className={`mt-2 text-xs font-medium ${statusTone}`}>{statusText ?? t("statusIdle")}</p>
              {lastEvent ? (
                <div className="mt-3 border-t border-white/[0.055] pt-3">
                  <span className="text-[9px] uppercase tracking-widest text-white/22">{t("latestEvent")}</span>
                  <p className="mt-1.5 line-clamp-2 font-mono text-[10px] leading-4 text-white/38">[{lastEvent.time}] {lastEvent.message}</p>
                </div>
              ) : null}
            </div>

            <p className="flex gap-2.5 text-[10px] leading-[1.6] text-white/28">
              <Icon name="activity" size={13} className="mt-0.5 shrink-0 text-amber-300/55" />
              {t("previewNote")}
            </p>
          </div>
        </aside>
      </div>

      <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-ink-850 shadow-panel">
        <div className="flex flex-col gap-4 border-b border-white/[0.06] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div className="flex items-center gap-3">
            <span className="grid size-8 place-items-center rounded-lg bg-white/[0.035] text-white/45"><Icon name="signal" size={16} /></span>
            <div>
              <h2 className="text-xs font-semibold text-white/85">{t("results")}</h2>
              <p className="mt-0.5 text-[10px] text-white/30">{t("resultsHint")}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-white/[0.07] bg-black/15 p-0.5">
              <button onClick={() => setTab("sparams")} className={`rounded-md px-3 py-1.5 text-[10px] font-medium transition-colors ${tab === "sparams" ? "bg-white/10 text-white/85" : "text-white/30 hover:text-white/60"}`}>{t("sParams")}</button>
              <button onClick={() => setTab("pattern")} className={`rounded-md px-3 py-1.5 text-[10px] font-medium transition-colors ${tab === "pattern" ? "bg-white/10 text-white/85" : "text-white/30 hover:text-white/60"}`}>{t("radPattern")}</button>
            </div>
            <span className={`rounded-full border px-2.5 py-1 font-mono text-[9px] uppercase tracking-wider ${usingSolverData && tab === "sparams" ? "border-signal-400/25 bg-signal-400/8 text-signal-300" : "border-amber-300/20 bg-amber-300/[0.06] text-amber-200/75"}`}>
              {usingSolverData && tab === "sparams" ? `${t("solverBadge")}: ${solverMode}` : t("previewBadge")}
            </span>
          </div>
        </div>
        <div className="p-3 sm:p-5">
          {tab === "sparams" ? (
            <SParamPlot data={usingSolverData ? solverData : previewData} height={360} />
          ) : (
            <RadiationPattern theta={pattern.theta} phi={pattern.phi} eTheta={pattern.eTheta} frequency={`${(fc / 1e9).toFixed(2)} GHz`} height={420} />
          )}
        </div>
      </section>
    </div>
  );
};

export default DesignEditor;
