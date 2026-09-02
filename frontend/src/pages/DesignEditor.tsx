import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Grid, Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { Icon } from "../components/Icons";
import RadiationPattern from "../components/RadiationPattern";
import SParamPlot, { SParamData } from "../components/SParamPlot";
import { useI18n } from "../i18n";
import { C0, dipolePattern, dipoleResonanceHz, dipoleS11Sweep } from "../lib/dipole";
import { useDesignContext } from "../lib/designContext";
import { useSocket } from "../lib/socket";

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return reduced;
}

const Dipole: React.FC<{ length: number }> = ({ length }) => {
  const arm = length / 2;
  return (
    <group>
      <mesh position={[0, arm / 2 + length * 0.01, 0]}>
        <cylinderGeometry args={[0.0011, 0.0011, arm, 28]} />
        <meshStandardMaterial color="#c8cbd2" metalness={0.95} roughness={0.22} />
      </mesh>
      <mesh position={[0, -arm / 2 - length * 0.01, 0]}>
        <cylinderGeometry args={[0.0011, 0.0011, arm, 28]} />
        <meshStandardMaterial color="#c8cbd2" metalness={0.95} roughness={0.22} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.0017, 24, 24]} />
        <meshStandardMaterial color="#d6e2f2" emissive="#a9c4e8" emissiveIntensity={2} />
      </mesh>
      <pointLight position={[0, 0, 0]} intensity={0.8} color="#a9c4e8" distance={0.12} />
    </group>
  );
};

const RadiationRings: React.FC<{ length: number }> = ({ length }) => {
  const groupRef = useRef<THREE.Group>(null);
  const reducedMotion = usePrefersReducedMotion();
  const rings = useMemo(
    () => [0.35, 0.65, 1].map((factor) => {
      const radius = length * factor;
      return new THREE.EllipseCurve(0, 0, radius, radius * 0.36, 0, Math.PI * 2, false, 0)
        .getPoints(72)
        .map((point) => new THREE.Vector3(point.x, 0, point.y));
    }),
    [length],
  );

  useFrame(({ clock }) => {
    if (!groupRef.current) return;
    const scale = reducedMotion ? 1 : 1 + Math.sin((clock.elapsedTime / 4.8) * Math.PI * 2) * 0.045;
    groupRef.current.scale.setScalar(scale);
  });

  return (
    <group ref={groupRef}>
      {rings.map((points, index) => (
        <Line
          key={index}
          points={points}
          color="#bfb4e6"
          lineWidth={1}
          transparent
          opacity={[0.4, 0.25, 0.12][index]}
          depthWrite={false}
        />
      ))}
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
}

const Step: React.FC<StepProps> = ({ index, label, state }) => (
  <div className={`step ${state} [&::before]:hidden`}>
    <span className={`grid size-6 place-items-center rounded-full border font-mono text-[10px] ${state === "active" ? "border-transparent bg-gradient-to-br from-steel-300 to-heather-400 text-obsidian-950 shadow-[0_0_18px_rgba(169,196,232,.55)]" : state === "done" ? "border-steel-500/50 bg-steel-500/15 text-steel-300" : "border-white/15 bg-black/25 text-white/35"}`}>{state === "done" ? <Icon name="check" size={12} strokeWidth={2.4} /> : index}</span>
    <span>{label}</span>
  </div>
);

const Metric: React.FC<{ label: string; value: string; unit: string }> = ({ label, value, unit }) => (
  <div className="metric border-t border-white/10 first:border-t-0 sm:border-l sm:border-t-0 sm:first:border-l-0">
    <span className="l">{label}</span>
    <span className="v">{value}<small>{unit}</small></span>
    <span className="chip gold self-start">Analytical</span>
  </div>
);

const POLL_MS = 2_000;
const POLL_MAX = 90;

const DesignEditor: React.FC = () => {
  const { t } = useI18n();
  const { lastEvent } = useSocket();
  const { setDesignContext } = useDesignContext();
  const reducedMotion = usePrefersReducedMotion();
  const [designName, setDesignName] = useState("half-wave-dipole");
  const [freqGhz, setFreqGhz] = useState("2.4");
  const [dipoleLength, setDipoleLength] = useState(0.0594);
  const [solver, setSolver] = useState<"nec2" | "openems">("nec2");
  const [running, setRunning] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [solverData, setSolverData] = useState<SParamData | null>(null);
  const [solverMode, setSolverMode] = useState<string | null>(null);
  const [tab, setTab] = useState<"sparams" | "pattern">("sparams");
  const [sParamMode, setSParamMode] = useState<"db" | "smith">("db");
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
    setSolverData(null);
    setSolverMode(null);
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
  const chartData = usingSolverData ? solverData : previewData;
  const sweepStart = chartData.frequency[0] / 1e9;
  const sweepEnd = chartData.frequency[chartData.frequency.length - 1] / 1e9;
  const statusTone = statusText?.startsWith(t("simError"))
    ? "text-coral-400"
    : running
      ? "text-sand-400"
      : statusText === t("simComplete")
        ? "text-steel-300"
        : "text-white/70";

  useEffect(() => {
    setDesignContext({
      designName,
      freqGhz: fc / 1e9,
      dipoleLengthM: dipoleLength,
      solver,
      resonanceGhz,
      minS11Db: preview.minS11Db,
      solverMode: null,
      solverAnchorMode: usingSolverData ? (solverMode ?? solver) : null,
    });
  }, [designName, dipoleLength, fc, preview.minS11Db, resonanceGhz, setDesignContext, solver, solverMode, usingSolverData]);

  return (
    <div className="space-y-5">
      <section className="glass flex min-h-14 items-center gap-4 rounded-full px-5 py-3 sm:px-6" aria-label="Design workflow">
        <Step index={1} label={t("geometry")} state="done" />
        <span className="rule done" />
        <Step index={2} label={t("analyticalPreview")} state={usingSolverData ? "done" : "active"} />
        <span className={`rule ${usingSolverData ? "done" : ""}`} />
        <Step index={3} label={t("canonicalSolverAnchor")} state={usingSolverData ? "done" : running ? "active" : "pending"} />
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-start">
        <section className="glass overflow-hidden">
          <div className="phead">
            <div>
              <span className="eyebrow">01 · {t("viewport")}</span>
              <p className="psub phead-subtitle">{t("viewportHint")}</p>
            </div>
            <span className="chip gold">Analytical</span>
          </div>

          <div className="well relative h-[540px] overflow-hidden" role="img" aria-label={`${t("viewport")}. ${t("analyticalFieldCue")}`}>
            <Canvas camera={{ position: [0.1, 0.06, 0.12], fov: 42 }}>
              <color attach="background" args={["#0c0c0e"]} />
              <fog attach="fog" args={["#0c0c0e", 0.22, 0.72]} />
              <ambientLight intensity={0.42} />
              <directionalLight position={[5, 8, 5]} intensity={1.05} />
              <Grid
                args={[20, 20]}
                position={[0, -0.055, 0]}
                cellSize={0.01}
                cellThickness={0.45}
                cellColor="#26272c"
                sectionSize={0.05}
                sectionThickness={0.85}
                sectionColor="#34363c"
                fadeDistance={0.85}
                infiniteGrid
              />
              <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.054, 0]}>
                <circleGeometry args={[0.065, 64]} />
                <meshBasicMaterial color="#000000" transparent opacity={0.28} depthWrite={false} />
              </mesh>
              <Suspense fallback={null}>
                <Dipole length={dipoleLength} />
                <RadiationRings length={dipoleLength} />
              </Suspense>
              <OrbitControls autoRotate={!reducedMotion} autoRotateSpeed={0.45} enableDamping dampingFactor={0.1} />
            </Canvas>
            <span className="chip absolute left-4 top-4 [&::before]:hidden">Y axis · center feed</span>
            <span className="chip absolute right-4 top-4 [&::before]:hidden">{t("targetFrequency")} · {(fc / 1e9).toFixed(2)} GHz</span>
            <span className="chip gold absolute bottom-4 right-4 max-w-[55%] whitespace-normal text-right [&::before]:hidden">{t("analyticalFieldCue")}</span>
            <span className="absolute bottom-5 left-4 flex items-center gap-2 font-mono text-[10px] tracking-widest text-tick">
              <i className="h-px w-12 bg-tick" />10 mm
            </span>
          </div>

          <div className="grid sm:grid-cols-3">
            <Metric label={t("halfWave")} value={(lambdaHalf * 1000).toFixed(1)} unit="mm" />
            <Metric label={t("resonance")} value={resonanceGhz.toFixed(2)} unit="GHz" />
            <Metric label={t("minS11")} value={preview.minS11Db.toFixed(1)} unit="dB" />
          </div>
        </section>

        <aside className="glass self-start overflow-hidden">
          <div className="phead">
            <div>
              <span className="eyebrow">02 · {t("parameters")}</span>
              <p className="psub phead-subtitle">{t("parametersHint")}</p>
            </div>
          </div>

          <div className="space-y-[18px] p-[22px]">
            <label className="block space-y-2">
              <span className="field-label">{t("designName")}</span>
              <input
                type="text"
                value={designName}
                disabled={running}
                onChange={(event) => setDesignName(event.target.value)}
                className="input w-full"
              />
            </label>

            <label className="block space-y-2">
              <span className="field-label">{t("centerFreq")}</span>
              <span className={`input flex items-center ${running ? "opacity-60" : ""}`}>
                <input
                  type="number"
                  step="0.1"
                  min="0.1"
                  max="100"
                  value={freqGhz}
                  disabled={running}
                  onChange={(event) => { setFreqGhz(event.target.value); invalidateSolverResult(); }}
                  className="min-w-0 flex-1 bg-transparent font-mono text-inherit outline-none"
                  aria-label={t("centerFreq")}
                />
                <span className="ml-auto font-mono text-[10px] text-white/45">GHz</span>
              </span>
            </label>

            <label className="block space-y-2.5">
              <span className="flex items-baseline justify-between gap-4">
                <span className="field-label">{t("dipoleLength")}</span>
                <span className="font-mono text-xs font-medium text-steel-300">{(dipoleLength * 1000).toFixed(1)} mm</span>
              </span>
              <input
                type="range"
                min="0.01"
                max="0.2"
                step="0.0005"
                value={dipoleLength}
                disabled={running}
                onChange={(event) => { setDipoleLength(parseFloat(event.target.value)); invalidateSolverResult(); }}
                style={{ "--range-pct": `${lengthPct}%` } as React.CSSProperties}
                className="range-control"
                aria-label={t("dipoleLength")}
              />
              <span className="flex justify-between font-mono text-[10px] text-white/30"><span>10 mm</span><span>200 mm</span></span>
            </label>

            <fieldset className="space-y-2">
              <legend className="field-label">{t("solver")}</legend>
              <div className="seg" role="group" aria-label={t("solver")}>
                <button type="button" disabled={running} aria-pressed={solver === "nec2"} onClick={() => { setSolver("nec2"); invalidateSolverResult(); }} className={`flex-1 ${solver === "nec2" ? "active" : ""}`}>NEC2 · {t("nec2Description")}</button>
                <button type="button" disabled={running} aria-pressed={solver === "openems"} onClick={() => { setSolver("openems"); invalidateSolverResult(); }} className={`flex-1 ${solver === "openems" ? "active" : ""}`}>openEMS · {t("openemsDescription")}</button>
              </div>
            </fieldset>

            <button
              type="button"
              onClick={() => void handleSimulate()}
              disabled={running}
              className="btn-primary w-full"
            >
              <Icon name={running ? "activity" : "play"} size={15} className={running ? "spin" : ""} />
              {running ? t("running") : t("runCanonicalAnchor")}
            </button>

            <div className="status">
              <div className="flex items-center justify-between gap-3">
                <span className="eyebrow">{t("statusTitle")}</span>
                <span className={`size-1.5 rounded-full ${running ? "breathe bg-sand-500" : usingSolverData ? "bg-steel-500 shadow-[0_0_8px_rgba(169,196,232,.9)]" : "bg-white/30"}`} />
              </div>
              <p className={`text-[13px] font-medium ${statusTone}`}>{statusText ?? t("statusIdle")}</p>
              {lastEvent ? (
                <div className="border-t border-white/10 pt-2.5">
                  <span className="eyebrow">{t("latestEvent")}</span>
                  <p className="mt-1.5 line-clamp-2 font-mono text-[11px] leading-5 text-white/50">[{lastEvent.time}] {lastEvent.message}</p>
                </div>
              ) : null}
            </div>

            <p className="text-[11px] leading-[1.65] text-white/45">{t("previewAnchorNote")}</p>
          </div>
        </aside>
      </div>

      <section className="glass overflow-hidden">
        <div className="phead h-auto min-h-14 flex-wrap py-3">
          <div>
            <span className="eyebrow">03 · {t("results")}</span>
            <p className="psub phead-subtitle">{t("resultsAnchorHint")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="toggle" role="group" aria-label={t("results")}>
              <button type="button" aria-pressed={tab === "sparams"} onClick={() => setTab("sparams")} className={tab === "sparams" ? "active" : ""}>{t("sParams")}</button>
              <button type="button" aria-pressed={tab === "pattern"} onClick={() => setTab("pattern")} className={tab === "pattern" ? "active" : ""}>{t("radPattern")}</button>
            </div>
            <div className="toggle" role="group" aria-label={t("sParams")}>
              <button type="button" aria-pressed={sParamMode === "db"} onClick={() => setSParamMode("db")} className={sParamMode === "db" ? "active" : ""}>{t("dbMagnitude")}</button>
              <button type="button" aria-pressed={sParamMode === "smith"} onClick={() => setSParamMode("smith")} className={sParamMode === "smith" ? "active" : ""}>{t("zPlane")}</button>
            </div>
            <span className={`chip ${usingSolverData && tab === "sparams" ? "ice" : "gold"}`}>
              {usingSolverData && tab === "sparams" ? `${solverMode ?? solver} · ${t("solverAnchorBadge")}` : "Analytical"}
            </span>
          </div>
        </div>

        <div className="p-3 sm:p-[18px] sm:px-[22px]">
          {tab === "sparams" ? (
            <SParamPlot data={chartData} mode={sParamMode} onModeChange={setSParamMode} height={380} />
          ) : (
            <RadiationPattern theta={pattern.theta} phi={pattern.phi} eTheta={pattern.eTheta} frequency={`${(fc / 1e9).toFixed(2)} GHz`} height={440} />
          )}
        </div>
        <div className="flex flex-col gap-1 border-t border-white/10 px-[22px] py-3 text-[11px] text-white/45 sm:flex-row sm:items-center sm:justify-between">
          <span>{chartData.frequency.length} · {sweepStart.toFixed(2)}–{sweepEnd.toFixed(2)} GHz · Z₀ = 50 Ω</span>
          <span>{usingSolverData ? t("solverAnchorScope") : t("previewAnchorNote")}</span>
        </div>
      </section>
    </div>
  );
};

export default DesignEditor;
