import React, { useEffect, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { useI18n } from "../i18n";

export interface SParamData {
  frequency: number[];
  sMatrix?: number[][][] | { re: number; im: number }[][][];
  s11?: number[] | { re: number; im: number }[];
  z0?: number;
  ports?: string[];
}

export interface SParamPlotProps {
  data?: SParamData | null;
  mode?: "db" | "smith";
  height?: number;
  trace?: "S11" | "S21" | "S12" | "S22";
}

const PLOT_CONFIG: Partial<Plotly.Config> = {
  displayModeBar: "hover",
  displaylogo: false,
  scrollZoom: true,
  responsive: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
};

const PAPER = "#0a0d0e";
const PLOT_BG = "#0c1011";
const GRID = "#202627";
const TEXT = "#77817e";
const ACCENT = "#54e6b5";
const FONT = "'IBM Plex Mono', Consolas, monospace";

function toDb(value: number | { re: number; im: number }): number {
  const magnitude = typeof value === "number" ? Math.abs(value) : Math.hypot(value.re, value.im);
  return 20 * Math.log10(Math.max(magnitude, 1e-30));
}

function toImpedance(value: number | { re: number; im: number }, z0 = 50) {
  const re = typeof value === "number" ? value : value.re;
  const im = typeof value === "number" ? 0 : value.im;
  const denominator = (1 - re) ** 2 + im ** 2;
  if (denominator < 1e-30) return { resistance: 1e4, reactance: 1e4 };
  return {
    resistance: ((1 - re ** 2 - im ** 2) / denominator) * z0,
    reactance: ((2 * im) / denominator) * z0,
  };
}

function extractS11(data: SParamData): (number | { re: number; im: number })[] {
  if (data.s11) return [...data.s11];
  return data.sMatrix?.map((perFrequency) => perFrequency[0]?.[0] ?? 0) ?? [];
}

const SParamPlot: React.FC<SParamPlotProps> = ({ data, mode = "db", height = 360, trace = "S11" }) => {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const [currentMode, setCurrentMode] = useState<"db" | "smith">(mode);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || !data) return;
    const frequencyGhz = data.frequency.map((frequency) => frequency / 1e9);
    const values = extractS11(data);
    if (frequencyGhz.length === 0 || values.length === 0) return;

    if (currentMode === "db") {
      const dbValues = values.map(toDb);
      let minimumIndex = 0;
      for (let index = 1; index < dbValues.length; index += 1) {
        if (dbValues[index] < dbValues[minimumIndex]) minimumIndex = index;
      }
      const minimumDb = dbValues[minimumIndex];
      const curve: Plotly.Data = {
        x: frequencyGhz, y: dbValues, type: "scatter", mode: "lines",
        line: { color: ACCENT, width: 2.4, shape: "spline" },
        fill: "tozeroy", fillcolor: "rgba(84, 230, 181, 0.045)", name: `|${trace}|`,
        hovertemplate: "%{x:.3f} GHz<br>%{y:.2f} dB<extra></extra>",
      };
      const marker: Plotly.Data = {
        x: [frequencyGhz[minimumIndex]], y: [minimumDb], type: "scatter", mode: "text+markers",
        marker: { color: "#f4d06f", size: 8, symbol: "diamond" }, text: [`${minimumDb.toFixed(1)} dB`],
        textposition: "bottom center", textfont: { color: "#f4d06f", family: FONT, size: 10 },
        showlegend: false, hoverinfo: "skip",
      };
      const layout: Partial<Plotly.Layout> = {
        paper_bgcolor: PAPER, plot_bgcolor: PLOT_BG, font: { color: TEXT, family: FONT, size: 10 },
        xaxis: { title: { text: "Frequency (GHz)", font: { size: 10 } }, gridcolor: GRID, zerolinecolor: GRID, color: TEXT, fixedrange: false },
        yaxis: { title: { text: `|${trace}| (dB)`, font: { size: 10 } }, gridcolor: GRID, zerolinecolor: GRID, color: TEXT, range: [Math.min(-40, Math.floor(minimumDb / 10) * 10 - 5), 2], fixedrange: false },
        margin: { t: 18, r: 18, b: 48, l: 56 }, showlegend: false,
        hoverlabel: { bgcolor: "#171b1c", bordercolor: "#303637", font: { color: "#f5f6f2", family: FONT, size: 10 } },
        shapes: [{ type: "line", x0: frequencyGhz[0], x1: frequencyGhz[frequencyGhz.length - 1], y0: -10, y1: -10, line: { color: "#ef8b78", width: 1, dash: "dot" } }],
        annotations: [{ x: frequencyGhz[frequencyGhz.length - 1], y: -10, xanchor: "right", yanchor: "bottom", text: "−10 dB · VSWR ≤ 2", showarrow: false, font: { color: "#b66d60", size: 9, family: FONT } }],
      };
      void Plotly.react(element, [curve, marker], layout, PLOT_CONFIG);
    } else {
      const z0 = data.z0 ?? 50;
      const impedance = values.map((value) => toImpedance(value, z0));
      const locus: Plotly.Data = {
        x: impedance.map((point) => point.resistance), y: impedance.map((point) => point.reactance),
        type: "scatter", mode: "lines+markers",
        marker: { size: 4.5, color: frequencyGhz, colorscale: [[0, "#153a32"], [0.5, "#54e6b5"], [1, "#f4d06f"]], colorbar: { title: { text: "GHz", font: { size: 9 } }, tickfont: { size: 9, color: TEXT }, thickness: 10, outlinewidth: 0 } },
        line: { color: "rgba(84, 230, 181, 0.42)", width: 1.4 }, name: `${trace} impedance locus`,
        hovertemplate: "R = %{x:.1f} Ω<br>X = %{y:.1f} Ω<extra></extra>",
      };
      const reference: Plotly.Data = {
        x: [z0], y: [0], type: "scatter", mode: "text+markers", marker: { color: "#f4d06f", size: 9, symbol: "cross" },
        text: [`Z₀ = ${z0} Ω`], textposition: "top center", textfont: { color: "#f4d06f", family: FONT, size: 9 },
        showlegend: false, hoverinfo: "skip",
      };
      const layout: Partial<Plotly.Layout> = {
        paper_bgcolor: PAPER, plot_bgcolor: PLOT_BG, font: { color: TEXT, family: FONT, size: 10 },
        xaxis: { title: { text: "Resistance (Ω)", font: { size: 10 } }, gridcolor: GRID, zerolinecolor: "#303637", color: TEXT },
        yaxis: { title: { text: "Reactance (Ω)", font: { size: 10 } }, gridcolor: GRID, zerolinecolor: "#303637", color: TEXT },
        margin: { t: 18, r: 18, b: 48, l: 56 }, showlegend: false,
        hoverlabel: { bgcolor: "#171b1c", bordercolor: "#303637", font: { color: "#f5f6f2", family: FONT, size: 10 } },
      };
      void Plotly.react(element, [locus, reference], layout, PLOT_CONFIG);
    }
    return () => { Plotly.purge(element); };
  }, [currentMode, data, trace]);

  if (!data) {
    return <div style={{ height }} className="grid place-items-center rounded-xl border border-dashed border-white/[0.07] text-xs text-white/25">{t("noSParamData")}</div>;
  }
  return (
    <div>
      <div className="mb-3 inline-flex rounded-lg border border-white/[0.07] bg-black/15 p-0.5">
        <button onClick={() => setCurrentMode("db")} className={`rounded-md px-3 py-1.5 text-[10px] font-medium transition-colors ${currentMode === "db" ? "bg-white/10 text-white/80" : "text-white/30 hover:text-white/60"}`}>{t("dbMagnitude")}</button>
        <button onClick={() => setCurrentMode("smith")} className={`rounded-md px-3 py-1.5 text-[10px] font-medium transition-colors ${currentMode === "smith" ? "bg-white/10 text-white/80" : "text-white/30 hover:text-white/60"}`}>{t("zPlane")}</button>
      </div>
      <div className="plot-frame"><div ref={containerRef} style={{ width: "100%", height }} /></div>
    </div>
  );
};

export default SParamPlot;
