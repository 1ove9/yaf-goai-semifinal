/**
 * Client-side analytical dipole models for instant design preview.
 *
 * These are deliberately simple closed-form approximations so the UI can
 * react to parameter changes in real time. They are NOT full-wave EM and
 * every consumer must label them as `analytical preview` — solver results
 * from the backend replace them once a simulation completes.
 *
 * Models:
 *  - Impedance: thin-wire dipole near first resonance as a series-RLC
 *    resonator (R ≈ 73 Ω at resonance, empirical Q for a thin wire).
 *  - Far field: exact thin-wire dipole pattern
 *    F(θ) = [cos(kL/2·cosθ) − cos(kL/2)] / sinθ.
 */

export const C0 = 299_792_458;

/** First-resonance shortening factor for a thin wire (L ≈ 0.475 λ). */
const RESONANT_LENGTH_FACTOR = 0.475;

/** Radiation resistance of a half-wave dipole at resonance [Ω]. */
const R_RESONANT = 73.1;

/** Empirical quality factor of a thin-wire dipole near resonance. */
const THIN_WIRE_Q = 8;

export interface Complex {
  re: number;
  im: number;
}

export interface S11Preview {
  /** Sweep frequencies [Hz]. */
  frequency: number[];
  /** Complex S11 per frequency point (Z0 = 50 Ω). */
  s11: Complex[];
  /** Estimated first resonance [Hz]. */
  resonanceHz: number;
  /** Minimum |S11| over the sweep [dB]. */
  minS11Db: number;
  /** Frequency of the minimum [Hz]. */
  minS11FreqHz: number;
}

/** Estimated first resonance of a thin-wire dipole of physical length L. */
export function dipoleResonanceHz(lengthM: number): number {
  return (RESONANT_LENGTH_FACTOR * C0) / lengthM;
}

/**
 * Sweep S11 of a thin-wire dipole against a 50 Ω reference.
 */
export function dipoleS11Sweep(
  lengthM: number,
  fMinHz: number,
  fMaxHz: number,
  nPoints = 201
): S11Preview {
  const fRes = dipoleResonanceHz(lengthM);
  const frequency: number[] = [];
  const s11: Complex[] = [];
  let minS11Db = Infinity;
  let minS11FreqHz = fMinHz;

  for (let i = 0; i < nPoints; i++) {
    const f = fMinHz + ((fMaxHz - fMinHz) * i) / (nPoints - 1);
    const u = f / fRes;
    // Series-RLC resonator: R grows with electrical length, X crosses zero at fRes.
    const r = R_RESONANT * u * u;
    const x = R_RESONANT * THIN_WIRE_Q * (u - 1 / u);
    // Γ = (Z − Z0) / (Z + Z0), Z0 = 50 Ω
    const dRe = r - 50;
    const sRe = r + 50;
    const denom = sRe * sRe + x * x;
    const gRe = (dRe * sRe + x * x) / denom;
    const gIm = (x * sRe - dRe * x) / denom;
    const mag = Math.sqrt(gRe * gRe + gIm * gIm);
    const db = 20 * Math.log10(Math.max(mag, 1e-12));

    frequency.push(f);
    s11.push({ re: gRe, im: gIm });
    if (db < minS11Db) {
      minS11Db = db;
      minS11FreqHz = f;
    }
  }

  return { frequency, s11, resonanceHz: fRes, minS11Db, minS11FreqHz };
}

export interface PatternPreview {
  /** Polar angles [deg]. */
  theta: number[];
  /** Azimuth angles [deg]. */
  phi: number[];
  /** Normalized |E_theta| field magnitude [theta][phi]. */
  eTheta: number[][];
}

/**
 * Exact thin-wire dipole far-field pattern for a dipole of length L at
 * frequency f (axis along z, azimuthally symmetric).
 */
export function dipolePattern(
  lengthM: number,
  freqHz: number,
  nTheta = 61,
  nPhi = 73
): PatternPreview {
  const k = (2 * Math.PI * freqHz) / C0;
  const kl2 = (k * lengthM) / 2;
  const cosKl2 = Math.cos(kl2);

  const theta: number[] = [];
  const phi: number[] = [];
  for (let i = 0; i < nTheta; i++) theta.push((180 * i) / (nTheta - 1));
  for (let j = 0; j < nPhi; j++) phi.push((360 * j) / (nPhi - 1));

  const eTheta: number[][] = [];
  let peak = 0;
  const cut: number[] = [];
  for (let i = 0; i < nTheta; i++) {
    const th = (theta[i] * Math.PI) / 180;
    const sinTh = Math.sin(th);
    const f = sinTh < 1e-6 ? 0 : Math.abs((Math.cos(kl2 * Math.cos(th)) - cosKl2) / sinTh);
    cut.push(f);
    if (f > peak) peak = f;
  }
  const scale = peak > 0 ? 1 / peak : 1;
  for (let i = 0; i < nTheta; i++) {
    eTheta.push(new Array<number>(nPhi).fill(cut[i] * scale));
  }

  return { theta, phi, eTheta };
}
