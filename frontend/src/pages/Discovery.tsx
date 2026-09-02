import React, { useEffect, useMemo, useState } from "react";
import { Icon } from "../components/Icons";
import TopologyGlyph from "../components/TopologyGlyph";
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
    idleBody: "系统会探索多种天线拓扑，生成跨代候选并按目标函数排序。只有真实求解器运行过的结果才会标记为已评估。",
    flowOne: "拓扑探索",
    flowOneHint: "在七类结构中产生多样候选",
    flowTwo: "物理筛选",
    flowTwoHint: "依据谐振、带宽、增益和尺寸评分",
    flowThree: "真实求解评估",
    flowThreeHint: "使用已安装的 NEC2/openEMS 评估优选方案",
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
    verified: "真实求解器已运行",
    evidenceWarning: "该候选尚未由真实全波求解器评估，不能直接用于工程决策。",
    noSolver: "当前主机没有完成真实求解器评估，以下指标仅用于筛选。",
    generation: "代",
    explored: "已探索",
    failed: "发现任务失败",
    retry: "重新配置",
    passed: "通过",
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
    idleBody: "The system explores multiple topology families, produces generations of candidates, and ranks them against the objective. Only candidates evaluated by a real solver are labelled as such.",
    flowOne: "Topology exploration",
    flowOneHint: "Generate diverse candidates across seven structure families",
    flowTwo: "Physics screening",
    flowTwoHint: "Score resonance, bandwidth, gain, efficiency, and size",
    flowThree: "Real-solver evaluation",
    flowThreeHint: "Evaluate finalists with installed NEC2/openEMS solvers",
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
    verified: "Real-solver evaluated",
    evidenceWarning: "This candidate has not been evaluated by a real full-wave solver and is not ready for engineering decisions.",
    noSolver: "No candidate was evaluated by a real solver on this host. Metrics are screening estimates.",
    generation: "Gen",
    explored: "Explored",
    failed: "Discovery run failed",
    retry: "Reconfigure",
    passed: "passed",
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
        <aside className="glass">
          <div className="phead">
            <span className="grid size-8 place-items-center rounded-xl border border-white/10 bg-white/[0.06] text-[#a9c4e8]"><Icon name="settings" size={16} /></span>
            <div>
              <h2 className="eyebrow">01 · {copy.contract}</h2>
              <p className="mt-1 text-[11px] text-white/45">{copy.contractHint}</p>
            </div>
          </div>

          <div className="space-y-5 p-5">
            <label className="block">
              <span className="mb-2 block text-[11px] font-medium text-white/48">{copy.name}</span>
              <input value={form.name} onChange={(event) => updateForm("name", event.target.value)} disabled={active} className="input w-full disabled:opacity-45" />
            </label>

            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.center}<span className="font-mono text-[9px] text-white/25">GHz</span></span>
                <input type="number" min="0.01" step="0.1" value={form.centerFrequency} onChange={(event) => updateForm("centerFrequency", event.target.value)} disabled={active} className="input w-full font-mono disabled:opacity-45" />
              </label>
              <label className="block">
                <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.bandwidth}<span className="font-mono text-[9px] text-white/25">MHz</span></span>
                <input type="number" min="1" step="10" value={form.bandwidth} onChange={(event) => updateForm("bandwidth", event.target.value)} disabled={active} className="input w-full font-mono disabled:opacity-45" />
              </label>
              <label className="block">
                <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.gain}<span className="font-mono text-[9px] text-white/25">dBi</span></span>
                <input type="number" step="0.5" value={form.gain} onChange={(event) => updateForm("gain", event.target.value)} disabled={active} className="input w-full font-mono disabled:opacity-45" />
              </label>
              <label className="block">
                <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.vswr}<span className="font-mono text-[9px] text-white/25">ratio</span></span>
                <input type="number" min="1.01" step="0.1" value={form.vswr} onChange={(event) => updateForm("vswr", event.target.value)} disabled={active} className="input w-full font-mono disabled:opacity-45" />
              </label>
            </div>

            <label className="block">
              <span className="mb-2 flex justify-between text-[11px] font-medium text-white/48">{copy.efficiency}<span className="font-mono text-[10px] text-[#d6e2f2]">{form.efficiency}%</span></span>
              <input type="range" min="20" max="98" step="1" value={form.efficiency} onChange={(event) => updateForm("efficiency", event.target.value)} disabled={active} style={{ "--range-pct": `${((numeric(form.efficiency, 70) - 20) / 78) * 100}%` } as React.CSSProperties} className="range-control my-2 disabled:opacity-45" />
            </label>

            <fieldset disabled={active}>
              <legend className="mb-2 text-[11px] font-medium text-white/48">{copy.envelope}</legend>
              <div className="grid grid-cols-3 gap-2">
                {(["maxWidth", "maxHeight", "maxDepth"] as const).map((key, index) => (
                  <label key={key} className="relative block">
                    <span className="absolute left-2.5 top-1/2 -translate-y-1/2 font-mono text-[9px] uppercase text-white/20">{["W", "H", "D"][index]}</span>
                    <input type="number" min="0.1" value={form[key]} onChange={(event) => updateForm(key, event.target.value)} className="input w-full py-0 pl-7 pr-6 font-mono text-[10px]" />
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
                  return <button key={topology} type="button" onClick={() => toggleTopology(topology)} aria-pressed={selected} aria-label={`${topologyLabels[topology]}: ${selected ? "selected" : "not selected"}`} className={`tag ${selected ? "on" : ""}`}>{selected ? <Icon name="check" size={11} /> : null}{topologyLabels[topology]}</button>;
                })}
              </div>
            </fieldset>

            <label className="block">
              <span className="mb-2 block text-[11px] font-medium text-white/48">{copy.depth}</span>
              <select value={form.searchDepth} onChange={(event) => updateForm("searchDepth", event.target.value as FormState["searchDepth"])} disabled={active} className="input w-full appearance-none disabled:opacity-45">
                <option value="quick">{copy.quick}</option>
                <option value="balanced">{copy.balanced}</option>
                <option value="deep">{copy.deep}</option>
              </select>
            </label>

            {requestError ? <p role="alert" className="break-words whitespace-pre-wrap rounded-[14px] border border-[#e39a9a]/40 bg-[#e39a9a]/10 p-3 text-[10px] leading-5 text-[#e39a9a]">{requestError}</p> : null}

            {active ? (
              <button type="button" onClick={() => void cancelRun()} className="btn-secondary w-full border-[#e39a9a]/50 text-[#e39a9a]"><Icon name="circle-stop" size={15} />{copy.cancel}</button>
            ) : (
              <button type="button" onClick={() => void startDiscovery()} disabled={submitting} className="btn-primary w-full disabled:opacity-50"><Icon name="sparkles" size={15} />{submitting ? copy.running : copy.start}</button>
            )}
          </div>
        </aside>

        <section className="glass min-h-[720px]">
          {run && active ? (
            <div className="flex h-full min-h-[720px] flex-col">
              <div className="phead h-auto min-h-14 py-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3"><span className="grid size-8 place-items-center rounded-xl border border-[#a9c4e8]/30 bg-[#a9c4e8]/10 text-[#d6e2f2]"><Icon name="activity" size={16} className="breathe" /></span><div><h2 className="eyebrow">{copy.running}</h2><p className="mt-1 break-words text-[11px] text-white/45">{run.stage}</p></div></div>
                  <span className="font-mono text-xs text-[#d6e2f2]">{Math.round(run.progress * 100)}%</span>
                </div>
                <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/[0.08]"><div className="h-full rounded-full bg-gradient-to-r from-[#8faed4] to-[#d6e2f2] transition-[width] duration-500" style={{ width: `${run.progress * 100}%` }} /></div>
              </div>
              <div className="grid flex-1 place-items-center p-8 text-center">
                <div className="max-w-md">
                  <div className="relative mx-auto size-24">
                    <span className="absolute inset-0 rounded-full border border-[#a9c4e8]/20 [animation:breathe_3.2s_ease-in-out_infinite]" />
                    <span className="absolute inset-3 rounded-full border border-[#a9c4e8]/35 [animation:breathe_3.2s_ease-in-out_.4s_infinite]" />
                    <span className="absolute inset-0 grid place-items-center text-[#a9c4e8]"><Icon name="radio" size={30} /></span>
                  </div>
                  <p className="mt-7 text-sm font-semibold text-white/75">{run.stage}</p>
                  <p className="mt-2 font-mono text-[10px] uppercase tracking-widest text-white/28">{copy.explored} {run.explored_count}</p>
                  {run.candidates.length > 0 ? (
                    <div className="mt-8 flex flex-wrap justify-center gap-2">
                      {Array.from(new Set(run.candidates.map((candidate) => candidate.topology))).map((topology) => <span key={topology} className="chip">{topologyLabels[topology]}</span>)}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ) : selectedCandidate ? (
            <div>
              <div className="phead h-auto min-h-14 py-4">
                <div className="flex items-center gap-3"><span className="grid size-8 place-items-center rounded-xl border border-[#a9c4e8]/30 bg-[#a9c4e8]/10 text-[#d6e2f2]"><Icon name="check" size={16} /></span><div><p className="eyebrow">02 · {copy.best}</p><h2 className="mt-1 text-sm font-semibold text-white/90">{topologyLabels[selectedCandidate.topology]} · {selectedCandidate.name}</h2></div></div>
                <span className={`chip ${selectedCandidate.evaluation_mode === "real_solver" ? "ice" : "gold"}`}>{selectedCandidate.evaluation_mode === "real_solver" ? [selectedCandidate.solver_name ?? "solver", selectedCandidate.solver_mode].filter(Boolean).join(" · ") : copy.analytical}</span>
              </div>

              <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_300px]">
                <div className="well relative min-h-[440px] overflow-hidden">
                  <React.Suspense fallback={<div className="grid min-h-[440px] place-items-center"><span className="size-5 animate-spin rounded-full border-2 border-white/10 border-t-[#a9c4e8]" /></div>}>
                    <ThreeViewer meshData={selectedCandidate.geometry} fill />
                  </React.Suspense>
                  <span className="chip absolute left-4 top-4">3D · {topologyLabels[selectedCandidate.topology]}</span>
                  <span className="chip absolute bottom-4 right-4">{copy.generation} {selectedCandidate.generation + 1}</span>
                </div>
                <div className="divide-y divide-white/[0.055]">
                  <div className="grid grid-cols-2">
                    <div className="p-4"><p className="text-[9px] uppercase tracking-wider text-white/35">{copy.score}</p><p className="mt-2 font-mono text-[30px] text-[#d6e2f2]">{Math.round(selectedCandidate.score * 100)}<span className="text-xs text-white/35">/100</span></p></div>
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
                      {selectedCandidate.checks.map((check) => <div key={check.key} className="check"><span className={`ic ${check.passed ? "ok" : "no"}`} aria-label={check.passed ? "passed" : "not passed"}><Icon name={check.passed ? "check" : "activity"} size={9} /></span><span className="min-w-0 flex-1 break-words text-[9px] text-white/50">{check.label}</span><span className="font-mono text-[9px] text-white/70">{formatCheckValue(check.actual, check.unit)}</span></div>)}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex items-start gap-2.5 border-t border-white/10 px-5 py-3 text-[10px] leading-5 text-white/55"><span className={`chip mt-0.5 flex-none ${selectedCandidate.evaluation_mode === "real_solver" ? "ice" : "gold"}`}>{selectedCandidate.evaluation_mode === "real_solver" ? copy.verified : copy.analytical}</span><span>{selectedCandidate.evaluation_mode === "real_solver" ? (selectedCandidate.warning ?? copy.verified) : copy.evidenceWarning}</span></div>
            </div>
          ) : run?.state === "failed" ? (
            <div className="grid min-h-[720px] place-items-center p-8 text-center"><div className="max-w-xl"><span className="mx-auto grid size-12 place-items-center rounded-[18px] border border-[#e39a9a]/35 bg-[#e39a9a]/10 text-[#e39a9a]"><Icon name="activity" size={20} /></span><h2 className="mt-4 text-sm font-semibold text-white/80">{copy.failed}</h2><p className="mt-2 break-words whitespace-pre-wrap text-xs leading-5 text-[#e39a9a]">{run.error}</p><button type="button" onClick={() => setRun(null)} className="btn-ghost mt-5">{copy.retry}</button></div></div>
          ) : (
            <div className="grid min-h-[720px] place-items-center p-8">
              <div className="max-w-xl text-center">
                <span className="mx-auto grid size-14 place-items-center rounded-[18px] border border-white/12 bg-white/[0.06] text-[#a9c4e8]"><Icon name="layers" size={24} /></span>
                <h2 className="mt-5 text-lg font-semibold tracking-[-0.025em] text-white/82">{copy.idleTitle}</h2>
                <p className="mt-2 text-xs leading-5 text-white/32">{copy.idleBody}</p>
                <div className="mt-9 grid gap-3 text-left sm:grid-cols-3">
                  {[["layers", copy.flowOne, copy.flowOneHint], ["signal", copy.flowTwo, copy.flowTwoHint], ["check", copy.flowThree, copy.flowThreeHint]].map(([icon, title, hint], index) => <div key={title} className="card"><div className="flex items-center justify-between"><span className="grid size-7 place-items-center rounded-xl border border-white/10 bg-white/[0.06] text-[#a9c4e8]"><Icon name={icon as "layers" | "signal" | "check"} size={14} /></span><span className="font-mono text-[9px] text-white/35">0{index + 1}</span></div><p className="mt-4 text-[10px] font-semibold text-white/70">{title}</p><p className="mt-1.5 text-[9px] leading-4 text-white/40">{hint}</p></div>)}
                </div>
              </div>
            </div>
          )}
        </section>
      </div>

      {run && !active && run.candidates.length > 0 ? (
        <section className="glass">
          <div className="phead h-auto min-h-14 py-4"><div><span className="eyebrow">{copy.candidates}</span><p className="mt-1 text-[11px] text-white/45">{copy.candidatesHint}</p></div><div className="flex flex-wrap items-center justify-end gap-3 text-[9px] text-white/50"><span className="flex items-center gap-1.5"><i className="size-1.5 rounded-full bg-[#a9c4e8] shadow-[0_0_8px_rgba(169,196,232,.9)]" />{copy.verified}</span><span className="flex items-center gap-1.5"><i className="size-1.5 rounded-full bg-[#d8c39a]" />{copy.analytical}</span><span className="font-mono uppercase tracking-widest">{copy.explored} {run.explored_count}</span></div></div>
          {run.warnings.length > 0 ? <div className="border-b border-[#d8c39a]/20 bg-[#d8c39a]/[0.06] px-5 py-2.5 text-[9px] text-[#ead9b8]">{copy.noSolver}</div> : null}
          <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
            {run.candidates.slice(0, 12).map((candidate, index) => {
              const activeCandidate = candidate.id === selectedCandidate?.id;
              const passed = candidate.checks.filter((check) => check.passed).length;
              return <button key={candidate.id} type="button" onClick={() => setSelectedId(candidate.id)} aria-pressed={activeCandidate} aria-label={`${topologyLabels[candidate.topology]} ${candidate.name}, ${Math.round(candidate.score * 100)} ${copy.score}`} className={`card group text-left ${activeCandidate ? "sel" : ""}`}><div className="flex items-start justify-between"><TopologyGlyph topology={candidate.topology} className="size-11 text-white/60 transition-colors group-hover:text-[#d6e2f2]" /><span className={`mt-1 size-1.5 rounded-full ${candidate.evaluation_mode === "real_solver" ? "bg-[#a9c4e8] shadow-[0_0_8px_rgba(169,196,232,.9)]" : "bg-[#d8c39a]"}`}><span className="sr-only">{candidate.evaluation_mode === "real_solver" ? copy.verified : copy.analytical}</span></span></div><h3 className="mt-2 text-xs font-semibold text-white/80">{topologyLabels[candidate.topology]}</h3><p className="mt-1 font-mono text-[9px] uppercase tracking-wider text-white/40">#{String(index + 1).padStart(2, "0")} · {copy.generation} {candidate.generation + 1}</p><div className="mt-4 flex items-end justify-between"><span className="font-mono text-2xl text-white/90">{Math.round(candidate.score * 100)}</span><span className="text-[9px] text-white/45">{passed}/{candidate.checks.length} {copy.passed}</span></div></button>;
            })}
          </div>
        </section>
      ) : null}
    </div>
  );
};

export default Discovery;
