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
  onModeChange?: (mode: "db" | "smith") => void;
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

const PAPER = "rgba(0,0,0,0)";
const PLOT_BG = "rgba(0,0,0,0)";
const GRID = "rgba(255,255,255,0.09)";
const TEXT = "#8a8c94";
const ACCENT = "#c4d8f0";
const FONT = "'Geist Mono', 'IBM Plex Mono', Consolas, monospace";

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

const SParamPlot: React.FC<SParamPlotProps> = ({ data, mode, onModeChange, height = 360, trace = "S11" }) => {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const [currentMode, setCurrentMode] = useState<"db" | "smith">(mode ?? "db");
  const controlled = mode !== undefined && onModeChange !== undefined;
  const activeMode = controlled ? mode : currentMode;

  useEffect(() => {
    if (!controlled && mode !== undefined) setCurrentMode(mode);
  }, [controlled, mode]);

  const selectMode = (nextMode: "db" | "smith") => {
    if (!controlled) setCurrentMode(nextMode);
    onModeChange?.(nextMode);
  };

  useEffect(() => {
    const element = containerRef.current;
    if (!element || !data) return;
    const frequencyGhz = data.frequency.map((frequency) => frequency / 1e9);
    const values = extractS11(data);
    if (frequencyGhz.length === 0 || values.length === 0) return;

    if (activeMode === "db") {
      const dbValues = values.map(toDb);
      let minimumIndex = 0;
      for (let index = 1; index < dbValues.length; index += 1) {
        if (dbValues[index] < dbValues[minimumIndex]) minimumIndex = index;
      }
      const minimumDb = dbValues[minimumIndex];
      const glow: Plotly.Data = {
        x: frequencyGhz, y: dbValues, type: "scatter", mode: "lines",
        line: { color: "rgba(169,196,232,0.22)", width: 8, shape: "spline" },
        hoverinfo: "skip", showlegend: false,
      };
      const curve: Plotly.Data = {
        x: frequencyGhz, y: dbValues, type: "scatter", mode: "lines",
        line: { color: ACCENT, width: 2, shape: "spline" }, name: `|${trace}|`,
        hovertemplate: "%{x:.3f} GHz<br>%{y:.2f} dB<extra></extra>",
      };
      const marker: Plotly.Data = {
        x: [frequencyGhz[minimumIndex]], y: [minimumDb], type: "scatter", mode: "text+markers",
        marker: { color: "#c4d8f0", size: 8, symbol: "circle", line: { color: "#151518", width: 2 } }, text: [`${minimumDb.toFixed(1)} dB`],
        textposition: "bottom center", textfont: { color: "#ededf0", family: FONT, size: 10 },
        showlegend: false, hoverinfo: "skip",
      };
      const layout: Partial<Plotly.Layout> = {
        paper_bgcolor: PAPER, plot_bgcolor: PLOT_BG, font: { color: TEXT, family: FONT, size: 10 },
        xaxis: { title: { text: "Frequency (GHz)", font: { size: 10 } }, gridcolor: GRID, zerolinecolor: GRID, color: TEXT, fixedrange: false, showspikes: true, spikemode: "across", spikecolor: "rgba(255,255,255,0.28)", spikethickness: 1, spikedash: "solid" },
        yaxis: { title: { text: `|${trace}| (dB)`, font: { size: 10 } }, gridcolor: GRID, zerolinecolor: GRID, color: TEXT, range: [Math.min(-40, Math.floor(minimumDb / 10) * 10 - 5), 2], fixedrange: false },
        margin: { t: 18, r: 18, b: 48, l: 56 }, showlegend: false, hovermode: "x unified",
        hoverlabel: { bgcolor: "rgba(22,22,26,0.92)", bordercolor: "rgba(255,255,255,0.22)", font: { color: "#ededf0", family: FONT, size: 10 } },
        shapes: [{ type: "line", x0: frequencyGhz[0], x1: frequencyGhz[frequencyGhz.length - 1], y0: -10, y1: -10, line: { color: "rgba(255,255,255,0.3)", width: 1 } }],
        annotations: [{ x: frequencyGhz[frequencyGhz.length - 1], y: -10, xanchor: "right", yanchor: "bottom", text: "−10 dB 工程参考（非研究判据）", showarrow: false, font: { color: TEXT, size: 9, family: FONT } }],
      };
      void Plotly.react(element, [glow, curve, marker], layout, PLOT_CONFIG);
    } else {
      const z0 = data.z0 ?? 50;
      const impedance = values.map((value) => toImpedance(value, z0));
      const locus: Plotly.Data = {
        x: impedance.map((point) => point.resistance), y: impedance.map((point) => point.reactance),
        type: "scatter", mode: "lines+markers",
        marker: { size: 4.5, color: frequencyGhz, colorscale: [[0, "#3a4256"], [0.5, "#a9c4e8"], [1, "#ead9b8"]], colorbar: { title: { text: "GHz", font: { size: 9 } }, tickfont: { size: 9, color: TEXT }, thickness: 10, outlinewidth: 0 } },
        line: { color: "rgba(169,196,232,0.42)", width: 1.4 }, name: `${trace} impedance locus`,
        hovertemplate: "R = %{x:.1f} Ω<br>X = %{y:.1f} Ω<extra></extra>",
      };
      const reference: Plotly.Data = {
        x: [z0], y: [0], type: "scatter", mode: "text+markers", marker: { color: "#ededf0", size: 9, symbol: "cross" },
        text: [`Z₀ = ${z0} Ω`], textposition: "top center", textfont: { color: "#ededf0", family: FONT, size: 9 },
        showlegend: false, hoverinfo: "skip",
      };
      const layout: Partial<Plotly.Layout> = {
        paper_bgcolor: PAPER, plot_bgcolor: PLOT_BG, font: { color: TEXT, family: FONT, size: 10 },
        xaxis: { title: { text: "Resistance (Ω)", font: { size: 10 } }, gridcolor: GRID, zerolinecolor: "rgba(255,255,255,0.3)", color: TEXT },
        yaxis: { title: { text: "Reactance (Ω)", font: { size: 10 } }, gridcolor: GRID, zerolinecolor: "rgba(255,255,255,0.3)", color: TEXT },
        margin: { t: 18, r: 18, b: 48, l: 56 }, showlegend: false,
        hoverlabel: { bgcolor: "rgba(22,22,26,0.92)", bordercolor: "rgba(255,255,255,0.22)", font: { color: "#ededf0", family: FONT, size: 10 } },
      };
      void Plotly.react(element, [locus, reference], layout, PLOT_CONFIG);
    }
    return () => { Plotly.purge(element); };
  }, [activeMode, data, trace]);

  if (!data) {
    return <div style={{ height }} className="well grid place-items-center text-xs text-white/40">{t("noSParamData")}</div>;
  }
  return (
    <div>
      {!controlled ? (
        <div className="toggle mb-3" role="group" aria-label={t("sParams")}>
          <button type="button" aria-pressed={activeMode === "db"} onClick={() => selectMode("db")} className={activeMode === "db" ? "active" : ""}>{t("dbMagnitude")}</button>
          <button type="button" aria-pressed={activeMode === "smith"} onClick={() => selectMode("smith")} className={activeMode === "smith" ? "active" : ""}>{t("zPlane")}</button>
        </div>
      ) : null}
      <div className="well overflow-hidden" role="img" aria-label={`${trace} ${activeMode === "db" ? t("dbMagnitude") : t("zPlane")}`}>
        <div ref={containerRef} style={{ width: "100%", height }} />
      </div>
    </div>
  );
};

export default SParamPlot;
