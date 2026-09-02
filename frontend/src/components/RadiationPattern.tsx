import React, { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { useI18n } from "../i18n";

export interface RadiationPatternProps {
  theta?: number[];
  phi?: number[];
  eTheta?: number[][] | { re: number; im: number }[][];
  ePhi?: number[][] | { re: number; im: number }[][];
  frequency?: string;
  height?: number;
}

const PAPER = "rgba(0,0,0,0)";
const TEXT = "#8a8c94";
const FONT = "'Geist Mono', 'IBM Plex Mono', Consolas, monospace";

function magnitude(value: number | { re: number; im: number } | undefined): number {
  if (value === undefined) return 0;
  return typeof value === "number" ? Math.abs(value) : Math.hypot(value.re, value.im);
}

const RadiationPattern: React.FC<RadiationPatternProps> = ({ theta, phi, eTheta, frequency = "", height = 400 }) => {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const hasData = Boolean(theta && phi && eTheta);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || !theta || !phi || !eTheta) return;
    const gain: number[][] = [];
    let peak = 0;
    for (let thetaIndex = 0; thetaIndex < theta.length; thetaIndex += 1) {
      const row: number[] = [];
      for (let phiIndex = 0; phiIndex < phi.length; phiIndex += 1) {
        const fieldMagnitude = magnitude(eTheta[thetaIndex]?.[phiIndex]);
        row.push(fieldMagnitude);
        peak = Math.max(peak, fieldMagnitude);
      }
      gain.push(row);
    }

    const scale = peak > 0 ? 1 / peak : 1;
    const x: number[][] = [];
    const y: number[][] = [];
    const z: number[][] = [];
    const color: number[][] = [];
    for (let thetaIndex = 0; thetaIndex < theta.length; thetaIndex += 1) {
      const xRow: number[] = [];
      const yRow: number[] = [];
      const zRow: number[] = [];
      const colorRow: number[] = [];
      const thetaRadians = (theta[thetaIndex] * Math.PI) / 180;
      for (let phiIndex = 0; phiIndex < phi.length; phiIndex += 1) {
        const phiRadians = (phi[phiIndex] * Math.PI) / 180;
        const radius = gain[thetaIndex][phiIndex] * scale;
        xRow.push(radius * Math.sin(thetaRadians) * Math.cos(phiRadians));
        yRow.push(radius * Math.sin(thetaRadians) * Math.sin(phiRadians));
        zRow.push(radius * Math.cos(thetaRadians));
        colorRow.push(radius);
      }
      x.push(xRow);
      y.push(yRow);
      z.push(zRow);
      color.push(colorRow);
    }

    const surface = {
      type: "surface", x, y, z, surfacecolor: color, cmin: 0, cmax: 1, showscale: true,
      colorscale: [[0, "#1a1c22"], [0.5, "#5c6f8c"], [1, "#d6e2f2"]],
      colorbar: { title: { text: "|E| / |E|max", font: { size: 9, color: TEXT } }, tickfont: { size: 9, color: TEXT }, thickness: 10, outlinewidth: 0 },
      lighting: { ambient: 0.5, diffuse: 0.72, specular: 0.3, roughness: 0.55 },
      hovertemplate: "Normalized gain %{surfacecolor:.2f}<extra></extra>",
    } as unknown as Plotly.Data;
    const axis = { visible: false, showgrid: false, zeroline: false, range: [-1.05, 1.05] };
    const layout: Partial<Plotly.Layout> = {
      paper_bgcolor: PAPER,
      font: { color: TEXT, family: FONT, size: 10 },
      scene: { xaxis: axis, yaxis: axis, zaxis: axis, bgcolor: PAPER, aspectmode: "cube", camera: { eye: { x: 1.45, y: 1.25, z: 0.65 } } },
      margin: { t: frequency ? 34 : 8, r: 8, b: 8, l: 8 },
      title: frequency ? { text: `Far field · ${frequency}`, font: { color: TEXT, size: 10 } } : undefined,
    };
    void Plotly.react(element, [surface], layout, { displayModeBar: "hover", displaylogo: false, scrollZoom: true, responsive: true });
    return () => { Plotly.purge(element); };
  }, [eTheta, frequency, phi, theta]);

  if (!hasData) {
    return <div style={{ height }} className="well grid place-items-center text-xs text-white/40">{t("noPatternData")}</div>;
  }
  return (
    <div className="well overflow-hidden" role="img" aria-label={`${t("radPattern")}${frequency ? ` · ${frequency}` : ""}`}>
      <div ref={containerRef} style={{ width: "100%", height }} />
    </div>
  );
};

export default RadiationPattern;
