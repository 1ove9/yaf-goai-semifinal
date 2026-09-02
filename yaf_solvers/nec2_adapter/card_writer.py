"""
NEC2 card writer — generates NEC-2 input card deck (.nec files).

Reference: NEC-2 User's Guide, Lawrence Livermore National Laboratory.
"""

from __future__ import annotations

import math


class NEC2CardWriter:
    """Generates NEC-2 input card deck for wire/structure antennas.

    Supports standard NEC cards:
      CM  — Comment
      CE  — End of comment
      GW  — Geometry wire
      GE  — End of geometry
      GN  — Ground parameters
      EX  — Excitation
      FR  — Frequency
      RP  — Radiation pattern
      EN  — End of run

    Uses standard NEC-2 formatting (FORTRAN-style fixed columns).
    """

    def __init__(self, title: str = "YAF NEC2 Simulation") -> None:
        self.title = title
        self.cards: list[str] = []

    def comment(self, text: str) -> None:
        """Add comment cards."""
        self.cards.append(f"CM {text}")

    def end_comment(self) -> None:
        """End comment section."""
        self.cards.append("CE")

    def gw_card(
        self,
        tag: int,
        segments: int,
        x1: float, y1: float, z1: float,
        x2: float, y2: float, z2: float,
        radius: float,
    ) -> str:
        """Generate a GW (geometry wire) card.

        Args:
            tag: Wire tag number.
            segments: Number of segments.
            x1..z2: Wire endpoints [m].
            radius: Wire radius [m].
        """
        # Scientific notation: fixed-point %.4f truncates sub-0.1mm radii
        # (any wire above ~3 GHz) to 0.0000, which NEC rejects.
        return (
            f"GW {tag:>3d} {segments:>5d} "
            f"{x1:.5E} {y1:.5E} {z1:.5E} "
            f"{x2:.5E} {y2:.5E} {z2:.5E} "
            f"{radius:.5E}"
        )

    def add_dipole(
        self,
        length: float,
        radius: float = 0.001,
        segments: int = 21,
        tag: int = 1,
    ) -> None:
        """Add a z-oriented half-wave dipole.

        Args:
            length: Total dipole length [m].
            radius: Wire radius [m].
            segments: Number of segments.
            tag: Wire tag.
        """
        half = length / 2
        self.cards.append(
            self.gw_card(tag, segments, 0, 0, -half, 0, 0, half, radius)
        )

    def add_loop(
        self,
        radius: float,
        wire_radius: float = 0.001,
        segments: int = 36,
        tag: int = 1,
        center_z: float = 0.0,
    ) -> None:
        """Add a circular loop in the xy-plane.

        Args:
            radius: Loop radius [m].
            wire_radius: Wire radius [m].
            segments: Number of segments.
            tag: Wire tag.
            center_z: Z-position of the loop.
        """
        for i in range(segments):
            t1 = 2 * math.pi * i / segments
            t2 = 2 * math.pi * (i + 1) / segments
            x1 = radius * math.cos(t1)
            y1 = radius * math.sin(t1)
            x2 = radius * math.cos(t2)
            y2 = radius * math.sin(t2)
            self.cards.append(
                self.gw_card(
                    tag, 1,
                    x1, y1, center_z,
                    x2, y2, center_z,
                    wire_radius,
                )
            )

    def add_yagi(
        self,
        n_elements: int = 3,
        freq: float = 1e9,
        spacing: float | None = None,
        tag_start: int = 1,
    ) -> None:
        """Add a Yagi-Uda array.

        Args:
            n_elements: Number of elements.
            freq: Design frequency [Hz].
            spacing: Element spacing [m]. Default: 0.2λ.
            tag_start: Starting wire tag.
        """
        c0 = 3e8
        wavelength = c0 / freq

        if spacing is None:
            spacing = 0.2 * wavelength

        for i in range(n_elements):
            y_pos = (i - (n_elements - 1) / 2) * spacing
            half_len = wavelength / 4 if i == (n_elements // 2) else wavelength / 4 * 0.95
            self.cards.append(
                self.gw_card(
                    tag_start + i, 11,
                    0, y_pos, -half_len,
                    0, y_pos, half_len,
                    wavelength / 200,
                )
            )

    def ge_card(self, ground_flag: int = 0) -> str:
        """GE (end of geometry) card.

        Args:
            ground_flag: 0 = free space (no ground plane),
                         1 = ground plane, current expansion modified,
                         -1 = ground plane, current expansion unmodified.
                         (NEC-2 User's Guide; a GN card is required when
                         ground_flag != 0.)
        """
        return f"GE {ground_flag}"

    def gn_card(
        self,
        ground_type: int = 0,
        n_radials: int = 0,
        eps_r: float = 13.0,
        sigma: float = 0.005,
    ) -> str:
        """GN (ground parameters) card.

        Args:
            ground_type: -1 = nullify ground (free space), 0 = finite
                         (reflection coefficient), 1 = perfectly conducting,
                         2 = finite (Sommerfeld/Norton).
            n_radials: For finite ground.
            eps_r: Relative permittivity.
            sigma: Conductivity [S/m].
        """
        return f"GN {ground_type} {n_radials} 0 0 {eps_r:.3f} {sigma:.4f}"

    def ex_card(
        self,
        excitation_type: int = 0,
        tag: int = 1,
        segment: int = 0,
        admittance: tuple[float, float] | None = None,
    ) -> str:
        """EX (excitation) card.

        Args:
            excitation_type: 0 = voltage source, 1 = incident plane wave.
            tag: Wire tag of source.
            segment: Segment number (0 = center).
            admittance: Optional (real, imag) admittance.
        """
        if admittance:
            r, x = admittance
            return f"EX {excitation_type} {tag} {segment} 0 {r:.6f} {x:.6f} 0 0 0 0"
        return f"EX {excitation_type} {tag} {segment} 0 1.0 0.0 0 0 0 0"

    def fr_card(
        self,
        frequency_range: tuple[float, float, int] | float,
    ) -> str:
        """FR (frequency) card.

        Args:
            frequency_range: If tuple: (f_min, f_max, n_steps) in MHz.
                             If float: single frequency in MHz.
        """
        if isinstance(frequency_range, tuple):
            f_min, f_max, n_steps = frequency_range
            if n_steps <= 1:
                return f"FR 0 1 0 0 {f_min:.3f} 0.0"
            step = (f_max - f_min) / (n_steps - 1) if n_steps > 1 else 0
            return f"FR 0 {n_steps} 0 0 {f_min:.3f} {step:.3f}"
        return f"FR 0 1 0 0 {frequency_range:.3f} 0.0"

    def rp_card(
        self,
        theta0: float = 0.0,
        phi0: float = 0.0,
        dtheta: float = 5.0,
        dphi: float = 90.0,
        n_theta: int = 37,
        n_phi: int = 5,
        mode: int = 0,
        xnda: int = 1000,
    ) -> str:
        """RP (radiation pattern) card.

        Card layout is ``RP I1 I2 I3 I4 F1 F2 F3 F4`` (NEC-2 User's Guide):
        I1=mode, I2=n_theta, I3=n_phi, I4=XNDA, then THETS PHIS DTH DPH.
        An extra field before THETS shifts every angle parameter by one slot
        and silently turns the request into a near-field computation.

        Args:
            theta0, phi0: Start angles [degrees].
            dtheta, dphi: Angle increments [degrees].
            n_theta, n_phi: Number of points.
            mode: 0 = normal space-wave far field.
            xnda: Packed output-control digits; 1000 = vertical/horizontal/
                  total power gain, no normalization, no averaging.
        """
        return (
            f"RP {mode} {n_theta} {n_phi} {xnda:04d} "
            f"{theta0:.2f} {phi0:.2f} {dtheta:.2f} {dphi:.2f}"
        )

    def xq_card(self) -> str:
        """Request execution when no radiation-pattern card is present."""

        return "XQ"

    def en_card(self) -> str:
        """EN (end of run) card."""
        return "EN"

    def generate(self) -> str:
        """Generate complete NEC-2 input deck as a string."""
        lines: list[str] = []
        lines.append(f"CM {self.title}")
        lines.append("CE")
        lines.extend(self.cards)
        lines.append(self.en_card())
        return "\n".join(lines)

    def to_bytes(self) -> bytes:
        """Return input deck as UTF-8 bytes."""
        return self.generate().encode("utf-8")

    def write_file(self, filepath: str) -> None:
        """Write input deck to a .nec file."""
        with open(filepath, "w") as f:
            f.write(self.generate())
