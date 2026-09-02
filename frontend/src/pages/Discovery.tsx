import React, { useEffect, useMemo, useState } from "react";
import { Icon } from "../components/Icons";
import { useI18n } from "../i18n";

const ThreeViewer = React.lazy(() => import("../components/ThreeViewer"));

type DiscoveryState =
  | "pending"
  | "exploring"
  | "screening"
  | "verifying"
  | "completed"
  | "failed"
  | "cancelled";

type Topology = "dipole" | "patch" | "bowtie" | "spiral" | "meander" | "fractal" | "horn";

interface GeometryData {
  vertices: number[][];
  faces: number[][];
}

interface CandidateMetrics {
  resonance_hz: number;
  bandwidth_hz: number;
  gain_dbi: number;
  efficiency: number;
  vswr: number;
  dimensions_m: [number, number, number];
}

interface RequirementCheck {
  key: string;
  label: string;
  target: number;
  actual: number;
  unit: string;
  comparator: string;
  passed: boolean;
  evidence: "analytical_screening" | "real_solver";
}

interface Candidate {
  id: string;
  topology: Topology;
  name: string;
  generation: number;
  geometry: GeometryData;
  parameters: Record<string, number>;
  metrics: CandidateMetrics;
  checks: RequirementCheck[];
  score: number;
  novelty_score: number;
  evaluation_mode: "analytical_screening" | "real_solver";
  solver_name?: string | null;
  solver_mode?: string | null;
  warning?: string | null;
}

interface DiscoveryRun {
  id: string;
  state: DiscoveryState;
  stage: string;
  progress: number;
  explored_count: number;
  candidates: Candidate[];
  best_candidate?: Candidate | null;
  warnings: string[];
  error?: string | null;
}

interface FormState {
  name: string;
  centerFrequency: string;
  bandwidth: string;
  gain: string;
  vswr: string;
  efficiency: string;
  maxWidth: string;
  maxHeight: string;
  maxDepth: string;
  searchDepth: "quick" | "balanced" | "deep";
}

const INITIAL_FORM: FormState = {
  name: "wifi-compact-discovery",
  centerFrequency: "2.4",
  bandwidth: "100",
  gain: "4.0",
  vswr: "2.0",
  efficiency: "70",
  maxWidth: "100",
  maxHeight: "100",
  maxDepth: "20",
  searchDepth: "balanced",
};

const ALL_TOPOLOGIES: Topology[] = ["dipole", "patch", "bowtie", "spiral", "meander", "fractal", "horn"];

const COPY = {
  zh: {
    contract: "定义设计合同",
    contractHint: "所有候选、评分和验证都从这些约束推导",
    name: "设计任务名称",
    center: "中心频率",
    bandwidth: "目标带宽",
    gain: "最低增益",
    vswr: "最高 VSWR",
    efficiency: "最低效率",
    envelope: "最大物理包络",
    topologies: "允许探索的拓扑",
    depth: "搜索深度",
    quick: "快速 · 8 个候选",
    balanced: "均衡 · 16 个候选",
    deep: "深入 · 32 个候选",
    start: "开始发现新天线",
    running: "正在探索设计空间",
    cancel: "取消任务",
    idleTitle: "从需求出发，而不是从固定结构出发",
    idleBody: "系统会探索多种天线拓扑，生成跨代候选并按目标函数排序。只有真实求解器运行过的结果才会标记为已验证。",
    flowOne: "拓扑探索",
    flowOneHint: "在七类结构中产生多样候选",
    flowTwo: "物理筛选",
    flowTwoHint: "依据谐振、带宽、增益和尺寸评分",
    flowThree: "真实验证",
    flowThreeHint: "使用已安装的 NEC2/openEMS 验证优选方案",
    best: "当前最佳方案",
    candidates: "候选设计族",
    candidatesHint: "选择候选以检查几何、指标和约束证据",
    score: "目标得分",
    diversity: "搜索多样性",
    resonance: "预估谐振",
    candidateBandwidth: "预估带宽",
    candidateGain: "预估增益",
    candidateEfficiency: "预估效率",
    constraints: "需求符合性",
    analytical: "解析筛选",
    verified: "真实求解验证",
    evidenceWarning: "该候选尚未经过真实全波求解器验证，不能直接用于工程决策。",
    noSolver: "当前主机没有完成真实求解验证，以下指标仅用于筛选。",
    generation: "代",
    explored: "已探索",
    failed: "发现任务失败",
    retry: "重新配置",
  },
  en: {
    contract: "Define the design contract",
    contractHint: "Every candidate, score, and verification step derives from these constraints",
    name: "Run name",
    center: "Center frequency",
    bandwidth: "Target bandwidth",
    gain: "Minimum gain",
    vswr: "Maximum VSWR",
    efficiency: "Minimum efficiency",
    envelope: "Maximum physical envelope",
    topologies: "Allowed topology families",
    depth: "Search depth",
    quick: "Quick · 8 candidates",
    balanced: "Balanced · 16 candidates",
    deep: "Deep · 32 candidates",
    start: "Discover new antennas",
    running: "Exploring the design space",
    cancel: "Cancel run",
    idleTitle: "Start from requirements, not a fixed geometry",
    idleBody: "The system explores multiple topology families, produces generations of candidates, and ranks them against the objective. Only real solver runs are marked verified.",
    flowOne: "Topology exploration",
    flowOneHint: "Generate diverse candidates across seven structure families",
    flowTwo: "Physics screening",
    flowTwoHint: "Score resonance, bandwidth, gain, efficiency, and size",
    flowThree: "Real verification",
    flowThreeHint: "Validate finalists with installed NEC2/openEMS solvers",
    best: "Current best design",
    candidates: "Candidate design family",
    candidatesHint: "Select a candidate to inspect its geometry, metrics, and requirement evidence",
    score: "Objective score",
    diversity: "Search diversity",
    resonance: "Resonance",
    candidateBandwidth: "Bandwidth",
    candidateGain: "Gain",
    candidateEfficiency: "Efficiency",
    constraints: "Requirement compliance",
    analytical: "Analytical screening",
    verified: "Real solver verified",
    evidenceWarning: "This candidate has not been evaluated by a real full-wave solver and is not ready for engineering decisions.",
    noSolver: "No candidate was verified by a real solver on this host. Metrics are screening estimates.",
    generation: "Gen",
    explored: "Explored",
    failed: "Discovery run failed",
    retry: "Reconfigure",
  },
} as const;

const TOPOLOGY_LABELS: Record<"zh" | "en", Record<Topology, string>> = {
  zh: { dipole: "偶极子", patch: "微带贴片", bowtie: "蝴蝶结", spiral: "阿基米德螺旋", meander: "蛇形线", fractal: "分形", horn: "喇叭" },
  en: { dipole: "Dipole", patch: "Microstrip patch", bowtie: "Bow-tie", spiral: "Archimedean spiral", meander: "Meander line", fractal: "Fractal", horn: "Horn" },
};

function numeric(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatCheckValue(value: number, unit: string): string {
  if (unit === "Hz" || unit === "Hz error") return `${(value / 1e6).toFixed(1)} MHz`;
  if (unit === "m") return `${(value * 1000).toFixed(1)} mm`;
  if (unit === "dBi") return `${value.toFixed(2)} dBi`;
  if (unit === "ratio") return value.toFixed(2);
  return value.toFixed(2);
}

const Discovery: React.FC = () => {
  const { lang } = useI18n();
  const copy = COPY[lang];
  const topologyLabels = TOPOLOGY_LABELS[lang];
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [selectedTopologies, setSelectedTopologies] = useState<Topology[]>(ALL_TOPOLOGIES);
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);

  const runId = run?.id;
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    let timer: number | null = null;
    const controller = new AbortController();

    const poll = async () => {
      try {
        const response = await fetch(`/api/v1/discoveries/${runId}`, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const nextRun = (await response.json()) as DiscoveryRun;
        if (cancelled) return;
        setRun(nextRun);
        if (!["completed", "failed", "cancelled"].includes(nextRun.state)) {
          timer = window.setTimeout(poll, 750);
        }
      } catch (error) {
        if (!cancelled && !(error instanceof DOMException && error.name === "AbortError")) {
          setRequestError(error instanceof Error ? error.message : String(error));
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [runId]);

  const selectedCandidate = useMemo(() => {
    if (!run) return null;
    return run.candidates.find((candidate) => candidate.id === selectedId) ?? run.best_candidate ?? run.candidates[0] ?? null;
  }, [run, selectedId]);

  const active = run ? !["completed", "failed", "cancelled"].includes(run.state) : false;

  const updateForm = <Key extends keyof FormState>(key: Key, value: FormState[Key]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const toggleTopology = (topology: Topology) => {
    setSelectedTopologies((current) => {
      if (current.includes(topology)) {
        return current.length === 1 ? current : current.filter((item) => item !== topology);
      }
      return [...current, topology];
    });
  };

  const startDiscovery = async () => {
    const depth = form.searchDepth === "quick"
      ? { candidate_budget: 8, generations: 1 }
      : form.searchDepth === "deep"
        ? { candidate_budget: 32, generations: 3 }
        : { candidate_budget: 16, generations: 2 };
    setSubmitting(true);
    setRequestError(null);
    setSelectedId(null);
    try {
      const response = await fetch("/api/v1/discoveries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          center_frequency_ghz: numeric(form.centerFrequency, 2.4),
          bandwidth_mhz: numeric(form.bandwidth, 100),
          target_gain_dbi: numeric(form.gain, 4),
          target_vswr: numeric(form.vswr, 2),
          minimum_efficiency: numeric(form.efficiency, 70) / 100,
          max_width_mm: numeric(form.maxWidth, 100),
          max_height_mm: numeric(form.maxHeight, 100),
          max_depth_mm: numeric(form.maxDepth, 20),
          allowed_topologies: selectedTopologies,
          verify_top_k: 1,
          seed: Date.now() % 2_147_483_647,
          ...depth,
        }),
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`${response.status}: ${detail}`);
      }
      setRun((await response.json()) as DiscoveryRun);
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  const cancelRun = async () => {
    if (!runId) return;
    const response = await fetch(`/api/v1/discoveries/${runId}`, { method: "DELETE" });
    if (response.ok) setRun((await response.json()) as DiscoveryRun);
  };

  return (
    <div className="space-y-5">
      <div className="grid items-start gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
        <aside className="overflow-hidden rounded-2xl border border-white/[0.07] bg-ink-850 shadow-panel">
          <div className="flex items-center gap-3 border-b border-white/[0.06] px-5 py-4">
            <span className="grid size-8 place-items-center rounded-lg bg-signal-400/10 text-signal-300"><Icon name="settings" size={16} /></span>
            <div>
              <h2 className="text-xs font-semibold text-white/85">{copy.contract}</h2>
              <p className="mt-0.5 text-[10px] text-white/30">{copy.contractHint}</p>
            </div>
          </div>

          <div className="space-y-5 p-5">
            <label className="block">
              <span className="mb-2 block text-[11px] font-medium text-white/48">{copy.name}</span>
              <input value={form.name} onChange={(event) => updateForm("name", event.target.value)} disabled={active} className="w-full rounded-xl border border-white/[0.08] bg-black/20 px-3.5 py-2.5 text-xs text-white/85 outline-none transition-colors focus:border-signal-400/50 disabled:opacity-45" />
            </label>

            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.center}<span className="font-mono text-[9px] text-white/25">GHz</span></span>
                <input type="number" min="0.01" step="0.1" value={form.centerFrequency} onChange={(event) => updateForm("centerFrequency", event.target.value)} disabled={active} className="w-full rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2.5 font-mono text-xs text-white/85 outline-none focus:border-signal-400/50 disabled:opacity-45" />
              </label>
              <label className="block">
                <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.bandwidth}<span className="font-mono text-[9px] text-white/25">MHz</span></span>
                <input type="number" min="1" step="10" value={form.bandwidth} onChange={(event) => updateForm("bandwidth", event.target.value)} disabled={active} className="w-full rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2.5 font-mono text-xs text-white/85 outline-none focus:border-signal-400/50 disabled:opacity-45" />
              </label>
              <label className="block">
                <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.gain}<span className="font-mono text-[9px] text-white/25">dBi</span></span>
                <input type="number" step="0.5" value={form.gain} onChange={(event) => updateForm("gain", event.target.value)} disabled={active} className="w-full rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2.5 font-mono text-xs text-white/85 outline-none focus:border-signal-400/50 disabled:opacity-45" />
              </label>
              <label className="block">
                <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.vswr}<span className="font-mono text-[9px] text-white/25">ratio</span></span>
                <input type="number" min="1.01" step="0.1" value={form.vswr} onChange={(event) => updateForm("vswr", event.target.value)} disabled={active} className="w-full rounded-xl border border-white/[0.08] bg-black/20 px-3 py-2.5 font-mono text-xs text-white/85 outline-none focus:border-signal-400/50 disabled:opacity-45" />
              </label>
            </div>

            <label className="block">
              <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.efficiency}<span className="font-mono text-[10px] text-signal-300">{form.efficiency}%</span></span>
              <input type="range" min="20" max="98" step="1" value={form.efficiency} onChange={(event) => updateForm("efficiency", event.target.value)} disabled={active} style={{ "--range-pct": `${((numeric(form.efficiency, 70) - 20) / 78) * 100}%` } as React.CSSProperties} className="range-control my-2 disabled:opacity-45" />
            </label>

            <fieldset disabled={active}>
              <legend className="mb-2 text-[11px] font-medium text-white/48">{copy.envelope}</legend>
              <div className="grid grid-cols-3 gap-2">
                {(["maxWidth", "maxHeight", "maxDepth"] as const).map((key, index) => (
                  <label key={key} className="relative block">
                    <span className="absolute left-2.5 top-1/2 -translate-y-1/2 font-mono text-[9px] uppercase text-white/20">{["W", "H", "D"][index]}</span>
                    <input type="number" min="0.1" value={form[key]} onChange={(event) => updateForm(key, event.target.value)} className="w-full rounded-xl border border-white/[0.08] bg-black/20 py-2.5 pl-7 pr-6 font-mono text-[10px] text-white/78 outline-none focus:border-signal-400/50" />
                    <span className="absolute right-2 top-1/2 -translate-y-1/2 font-mono text-[8px] text-white/18">mm</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset disabled={active}>
              <legend className="mb-2 text-[11px] font-medium text-white/48">{copy.topologies}</legend>
              <div className="flex flex-wrap gap-1.5">
                {ALL_TOPOLOGIES.map((topology) => {
                  const selected = selectedTopologies.includes(topology);
                  return <button key={topology} type="button" onClick={() => toggleTopology(topology)} className={`rounded-lg border px-2.5 py-1.5 text-[9px] font-medium transition-colors ${selected ? "border-signal-400/25 bg-signal-400/[0.08] text-signal-300" : "border-white/[0.06] bg-white/[0.015] text-white/28 hover:text-white/55"}`}>{topologyLabels[topology]}</button>;
                })}
              </div>
            </fieldset>

            <label className="block">
              <span className="mb-2 block text-[11px] font-medium text-white/48">{copy.depth}</span>
              <select value={form.searchDepth} onChange={(event) => updateForm("searchDepth", event.target.value as FormState["searchDepth"])} disabled={active} className="w-full appearance-none rounded-xl border border-white/[0.08] bg-black/20 px-3.5 py-2.5 text-xs text-white/78 outline-none focus:border-signal-400/50 disabled:opacity-45">
                <option value="quick">{copy.quick}</option>
                <option value="balanced">{copy.balanced}</option>
                <option value="deep">{copy.deep}</option>
              </select>
            </label>

            {requestError ? <p className="rounded-xl border border-red-400/15 bg-red-400/[0.05] p-3 text-[10px] leading-5 text-red-200/75">{requestError}</p> : null}

            {active ? (
              <button onClick={() => void cancelRun()} className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.035] px-4 py-3 text-xs font-semibold text-white/55 transition-colors hover:bg-white/[0.07] hover:text-white"><Icon name="circle-stop" size={15} />{copy.cancel}</button>
            ) : (
              <button onClick={() => void startDiscovery()} disabled={submitting} className="group flex w-full items-center justify-center gap-2 rounded-xl bg-signal-400 px-4 py-3 text-xs font-semibold text-ink-950 shadow-[0_10px_30px_rgba(84,230,181,0.12)] transition-all hover:bg-signal-300 disabled:opacity-50"><Icon name="sparkles" size={15} />{submitting ? copy.running : copy.start}</button>
            )}
          </div>
        </aside>

        <section className="min-h-[720px] overflow-hidden rounded-2xl border border-white/[0.07] bg-ink-850 shadow-panel">
          {run && active ? (
            <div className="flex h-full min-h-[720px] flex-col">
              <div className="border-b border-white/[0.06] px-5 py-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3"><span className="grid size-8 place-items-center rounded-lg bg-signal-400/10 text-signal-300"><Icon name="activity" size={16} className="animate-pulse" /></span><div><h2 className="text-xs font-semibold text-white/85">{copy.running}</h2><p className="mt-0.5 text-[10px] text-white/30">{run.stage}</p></div></div>
                  <span className="font-mono text-xs text-signal-300">{Math.round(run.progress * 100)}%</span>
                </div>
                <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full bg-signal-400 transition-[width] duration-500" style={{ width: `${run.progress * 100}%` }} /></div>
              </div>
              <div className="grid flex-1 place-items-center p-8 text-center">
                <div className="max-w-md">
                  <div className="relative mx-auto size-24">
                    <span className="absolute inset-0 animate-ping rounded-full border border-signal-400/15" />
                    <span className="absolute inset-3 animate-pulse rounded-full border border-signal-400/25" />
                    <span className="absolute inset-0 grid place-items-center text-signal-300"><Icon name="radio" size={30} /></span>
                  </div>
                  <p className="mt-7 text-sm font-semibold text-white/75">{run.stage}</p>
                  <p className="mt-2 font-mono text-[10px] uppercase tracking-widest text-white/28">{copy.explored} {run.explored_count}</p>
                  {run.candidates.length > 0 ? (
                    <div className="mt-8 flex flex-wrap justify-center gap-2">
                      {Array.from(new Set(run.candidates.map((candidate) => candidate.topology))).map((topology) => <span key={topology} className="rounded-full border border-white/[0.07] px-2.5 py-1 text-[9px] text-white/35">{topologyLabels[topology]}</span>)}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ) : selectedCandidate ? (
            <div>
              <div className="flex flex-col gap-4 border-b border-white/[0.06] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3"><span className="grid size-8 place-items-center rounded-lg bg-signal-400/10 text-signal-300"><Icon name="check" size={16} /></span><div><p className="text-[9px] uppercase tracking-[0.15em] text-white/25">{copy.best}</p><h2 className="mt-0.5 text-sm font-semibold text-white/85">{topologyLabels[selectedCandidate.topology]} · {selectedCandidate.name}</h2></div></div>
                <div className={`self-start rounded-full border px-3 py-1.5 font-mono text-[9px] uppercase tracking-wider ${selectedCandidate.evaluation_mode === "real_solver" ? "border-signal-400/25 bg-signal-400/[0.07] text-signal-300" : "border-amber-300/20 bg-amber-300/[0.05] text-amber-200/75"}`}>{selectedCandidate.evaluation_mode === "real_solver" ? copy.verified : copy.analytical}</div>
              </div>

              <div className="grid lg:grid-cols-[minmax(0,1fr)_280px]">
                <div className="grid-surface min-h-[430px] border-b border-white/[0.06] lg:border-b-0 lg:border-r">
                  <React.Suspense fallback={<div className="grid h-[430px] place-items-center"><span className="size-5 animate-spin rounded-full border-2 border-white/10 border-t-signal-400" /></div>}>
                    <ThreeViewer meshData={selectedCandidate.geometry} height="430px" />
                  </React.Suspense>
                </div>
                <div className="divide-y divide-white/[0.055]">
                  <div className="grid grid-cols-2">
                    <div className="p-4"><p className="text-[9px] uppercase tracking-wider text-white/25">{copy.score}</p><p className="mt-2 font-mono text-xl text-signal-300">{Math.round(selectedCandidate.score * 100)}<span className="text-xs text-white/25">/100</span></p></div>
                    <div className="border-l border-white/[0.055] p-4"><p className="text-[9px] uppercase tracking-wider text-white/25">{copy.diversity}</p><p className="mt-2 font-mono text-xl text-white/70">{Math.round(selectedCandidate.novelty_score * 100)}<span className="text-xs text-white/25">%</span></p></div>
                  </div>
                  <div className="grid grid-cols-2 gap-px p-4">
                    {[
                      [copy.resonance, `${(selectedCandidate.metrics.resonance_hz / 1e9).toFixed(3)} GHz`],
                      [copy.candidateBandwidth, `${(selectedCandidate.metrics.bandwidth_hz / 1e6).toFixed(1)} MHz`],
                      [copy.candidateGain, `${selectedCandidate.metrics.gain_dbi.toFixed(2)} dBi`],
                      [copy.candidateEfficiency, `${(selectedCandidate.metrics.efficiency * 100).toFixed(1)}%`],
                    ].map(([label, value]) => <div key={label} className="py-2"><p className="text-[9px] text-white/25">{label}</p><p className="mt-1 font-mono text-[11px] text-white/68">{value}</p></div>)}
                  </div>
                  <div className="p-4">
                    <h3 className="text-[9px] font-semibold uppercase tracking-[0.14em] text-white/28">{copy.constraints}</h3>
                    <div className="mt-3 space-y-2.5">
                      {selectedCandidate.checks.map((check) => <div key={check.key} className="flex items-center gap-2"><span className={`grid size-4 shrink-0 place-items-center rounded-full ${check.passed ? "bg-signal-400/10 text-signal-300" : "bg-red-400/10 text-red-300"}`}><Icon name={check.passed ? "check" : "activity"} size={9} /></span><span className="min-w-0 flex-1 truncate text-[9px] text-white/35">{check.label}</span><span className="font-mono text-[9px] text-white/55">{formatCheckValue(check.actual, check.unit)}</span></div>)}
                    </div>
                  </div>
                </div>
              </div>

              {selectedCandidate.evaluation_mode !== "real_solver" ? <div className="flex gap-2.5 border-t border-amber-300/10 bg-amber-300/[0.025] px-5 py-3 text-[10px] leading-5 text-amber-100/45"><Icon name="activity" size={13} className="mt-0.5 shrink-0 text-amber-300/55" />{copy.evidenceWarning}</div> : null}
            </div>
          ) : run?.state === "failed" ? (
            <div className="grid min-h-[720px] place-items-center p-8 text-center"><div><span className="mx-auto grid size-12 place-items-center rounded-xl bg-red-400/10 text-red-300"><Icon name="activity" size={20} /></span><h2 className="mt-4 text-sm font-semibold text-white/75">{copy.failed}</h2><p className="mt-2 max-w-md text-xs text-red-200/50">{run.error}</p><button onClick={() => setRun(null)} className="mt-5 rounded-lg border border-white/[0.08] px-4 py-2 text-xs text-white/55 hover:bg-white/[0.04]">{copy.retry}</button></div></div>
          ) : (
            <div className="grid min-h-[720px] place-items-center p-8">
              <div className="max-w-xl text-center">
                <span className="mx-auto grid size-14 place-items-center rounded-2xl border border-white/[0.07] bg-white/[0.025] text-signal-300"><Icon name="layers" size={24} /></span>
                <h2 className="mt-5 text-lg font-semibold tracking-[-0.025em] text-white/82">{copy.idleTitle}</h2>
                <p className="mt-2 text-xs leading-5 text-white/32">{copy.idleBody}</p>
                <div className="mt-9 grid gap-3 text-left sm:grid-cols-3">
                  {[["layers", copy.flowOne, copy.flowOneHint], ["signal", copy.flowTwo, copy.flowTwoHint], ["check", copy.flowThree, copy.flowThreeHint]].map(([icon, title, hint], index) => <div key={title} className="rounded-xl border border-white/[0.06] bg-white/[0.015] p-3.5"><div className="flex items-center justify-between"><span className="grid size-7 place-items-center rounded-lg bg-white/[0.035] text-white/40"><Icon name={icon as "layers" | "signal" | "check"} size={14} /></span><span className="font-mono text-[9px] text-white/18">0{index + 1}</span></div><p className="mt-4 text-[10px] font-semibold text-white/58">{title}</p><p className="mt-1.5 text-[9px] leading-4 text-white/25">{hint}</p></div>)}
                </div>
              </div>
            </div>
          )}
        </section>
      </div>

      {run && !active && run.candidates.length > 0 ? (
        <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-ink-850 shadow-panel">
          <div className="flex items-center justify-between gap-4 border-b border-white/[0.06] px-5 py-4"><div><h2 className="text-xs font-semibold text-white/85">{copy.candidates}</h2><p className="mt-0.5 text-[10px] text-white/30">{copy.candidatesHint}</p></div><span className="font-mono text-[9px] uppercase tracking-widest text-white/25">{copy.explored} {run.explored_count}</span></div>
          {run.warnings.length > 0 ? <div className="border-b border-amber-300/10 bg-amber-300/[0.02] px-5 py-2.5 text-[9px] text-amber-100/40">{copy.noSolver}</div> : null}
          <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
            {run.candidates.slice(0, 12).map((candidate, index) => {
              const activeCandidate = candidate.id === selectedCandidate?.id;
              const passed = candidate.checks.filter((check) => check.passed).length;
              return <button key={candidate.id} onClick={() => setSelectedId(candidate.id)} className={`group rounded-xl border p-4 text-left transition-all ${activeCandidate ? "border-signal-400/25 bg-signal-400/[0.045]" : "border-white/[0.06] bg-white/[0.012] hover:border-white/[0.12] hover:bg-white/[0.025]"}`}><div className="flex items-center justify-between"><span className="font-mono text-[9px] text-white/20">#{String(index + 1).padStart(2, "0")}</span><span className={`size-1.5 rounded-full ${candidate.evaluation_mode === "real_solver" ? "bg-signal-400" : "bg-amber-300/60"}`} /></div><h3 className="mt-4 text-xs font-semibold text-white/72">{topologyLabels[candidate.topology]}</h3><p className="mt-1 font-mono text-[9px] text-white/25">{copy.generation} {candidate.generation + 1}</p><div className="mt-4 flex items-end justify-between"><span className="font-mono text-lg text-white/78">{Math.round(candidate.score * 100)}</span><span className="text-[9px] text-white/28">{passed}/{candidate.checks.length} ✓</span></div></button>;
            })}
          </div>
        </section>
      ) : null}
    </div>
  );
};

export default Discovery;
