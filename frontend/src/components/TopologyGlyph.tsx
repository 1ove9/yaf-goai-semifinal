import React from "react";

export type TopologyGlyphTopology =
  | "dipole"
  | "patch"
  | "bowtie"
  | "spiral"
  | "meander"
  | "fractal"
  | "horn";

interface TopologyGlyphProps extends React.SVGProps<SVGSVGElement> {
  topology: TopologyGlyphTopology;
}

const glyphs: Record<TopologyGlyphTopology, React.ReactNode> = {
  meander: <path d="M22 36V30H12V24H32V18H12V12H22V8" />,
  patch: (
    <>
      <rect x="8" y="12" width="28" height="20" rx="1" />
      <path d="M22 32v6M18 38h8" />
    </>
  ),
  dipole: (
    <>
      <path d="M22 6v14M22 24v14" />
      <circle cx="22" cy="22" r="1.5" fill="currentColor" stroke="none" />
    </>
  ),
  bowtie: <path d="M20 22 6 12v20l14-10ZM24 22l14-10v20L24 22Z" />,
  spiral: <path d="M22 22c0-2 2-3 3.5-2 2 1.5 1.5 5-1 6.5-3.5 2-8 0-9.5-4-2-5.5 2-11 7.5-12.5 7-2 14 3 15.5 10 1.5 8.5-4 16-12.5 17.5" />,
  fractal: (
    <>
      <path d="M8 30h8l4-8 4 8h4l-2-5 2-5h8" />
      <path d="M20 30v6M24 30v6" />
    </>
  ),
  horn: (
    <>
      <path d="M16 16h6l14-8v28l-14-8h-6z" />
      <path d="M8 18h8v8H8z" />
    </>
  ),
};

const TopologyGlyph: React.FC<TopologyGlyphProps> = ({ topology, className, ...props }) => (
  <svg
    viewBox="0 0 44 44"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden="true"
    {...props}
  >
    {glyphs[topology]}
  </svg>
);

export default TopologyGlyph;
