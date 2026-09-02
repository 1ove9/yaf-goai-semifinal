# ============================================================
# REFERENCE
#   仿造来源：nec2c (Debian) 输出格式 + NEC-2 User's Guide Part III
#   对标输出段：FREQUENCY / ANTENNA INPUT PARAMETERS / POWER BUDGET /
#              RADIATION PATTERNS
#   关键设计点：
#     - nec2c 每个 FR 频点输出一个完整 block；逐 block 解析
#     - 阻抗在 ANTENNA INPUT PARAMETERS 表（REAL/IMAGINARY 第 7/8 列），
#       *不是* "INPUT IMPEDANCE" 关键字（那是原版 NEC-2 的措辞，
#       nec2c 不输出，旧解析器因此永远匹配不到）
#     - 方向图行的 SENSE 列可能为空（11 列）或 LINEAR/RIGHT/LEFT（12 列），
#       用"前 5 列 + 末 4 列"定位，避免列数漂移
#     - -999.99 dB 是 nec2c 的"零场"哨兵值
#     - 解析不到必需数据 → NEC2ParseError，绝不静默返回默认值
# ============================================================

"""
NEC2 output parser — parses real nec2c output into structured data.

Every quantity returned here was read from the solver output; there are
no defaults. If a required section is missing the parser raises
:class:`NEC2ParseError` so the caller can fail (or fall back) *explicitly*.
"""

from __future__ import annotations

import cmath
import math
import re
from dataclasses import dataclass, field

from yaf_solvers.base import YAFError

#: nec2c prints -999.99 dB for angles where the field is identically zero.
NULL_GAIN_DB = -999.99

_FREQ_RE = re.compile(r"FREQUENCY\s*[:=]\s*([0-9.Ee+-]+)\s*MHz", re.IGNORECASE)
_INPUT_POWER_RE = re.compile(r"INPUT POWER\s*=\s*([0-9.Ee+-]+)\s*Watts", re.IGNORECASE)
_RADIATED_POWER_RE = re.compile(r"RADIATED POWER\s*=\s*([0-9.Ee+-]+)\s*Watts", re.IGNORECASE)
_EFFICIENCY_RE = re.compile(r"EFFICIENCY\s*=\s*([0-9.Ee+-]+)\s*Percent", re.IGNORECASE)


class NEC2ParseError(YAFError):
    """Raised when nec2c output is missing a required section or value."""


@dataclass
class PatternPoint:
    """One row of the RADIATION PATTERNS table."""

    theta_deg: float
    phi_deg: float
    gain_vert_db: float
    gain_horiz_db: float
    gain_total_db: float
    e_theta: complex  # V/m, from MAGNITUDE/PHASE columns
    e_phi: complex


@dataclass
class FrequencyBlock:
    """Everything nec2c reports for one frequency point."""

    frequency_hz: float
    impedance: complex | None = None  # at the (first) excitation segment
    input_power_w: float | None = None
    radiated_power_w: float | None = None
    efficiency: float | None = None  # 0..1
    pattern: list[PatternPoint] = field(default_factory=list)

    def max_gain_dbi(self) -> float | None:
        """Peak total power gain over the requested pattern grid."""
        gains = [p.gain_total_db for p in self.pattern if p.gain_total_db > NULL_GAIN_DB]
        return max(gains) if gains else None


def _polar(magnitude: float, phase_deg: float) -> complex:
    return cmath.rect(magnitude, math.radians(phase_deg))


def _try_floats(tokens: list[str]) -> list[float] | None:
    try:
        return [float(t) for t in tokens]
    except ValueError:
        return None


def _parse_impedance_row(line: str) -> complex | None:
    """Parse a data row of the ANTENNA INPUT PARAMETERS table.

    Layout: TAG SEG V_re V_im I_re I_im Z_re Z_im Y_re Y_im POWER (11 cols).
    """
    tokens = line.split()
    if len(tokens) != 11:
        return None
    values = _try_floats(tokens)
    if values is None:
        return None
    return complex(values[6], values[7])


def _parse_pattern_row(line: str) -> PatternPoint | None:
    """Parse a data row of the RADIATION PATTERNS table.

    The SENSE column is blank for null fields (11 tokens) and a word such
    as LINEAR/RIGHT/LEFT otherwise (12 tokens), so index from both ends:
    the first 5 columns are angles+gains, the last 4 are the E fields.
    """
    tokens = line.split()
    if len(tokens) not in (11, 12):
        return None
    head = _try_floats(tokens[:7])
    tail = _try_floats(tokens[-4:])
    if head is None or tail is None:
        return None
    return PatternPoint(
        theta_deg=head[0],
        phi_deg=head[1],
        gain_vert_db=head[2],
        gain_horiz_db=head[3],
        gain_total_db=head[4],
        e_theta=_polar(tail[0], tail[1]),
        e_phi=_polar(tail[2], tail[3]),
    )


def parse_nec2_output(text: str) -> list[FrequencyBlock]:
    """Parse nec2c output text into one :class:`FrequencyBlock` per FR point.

    Raises:
        NEC2ParseError: no frequency block found, or a block has no
            parseable input impedance.
    """
    blocks: list[FrequencyBlock] = []
    current: FrequencyBlock | None = None
    section = ""  # "input_params" | "pattern" | ""

    for line in text.splitlines():
        m = _FREQ_RE.search(line)
        if m and "WAVELENGTH" not in line.upper():
            current = FrequencyBlock(frequency_hz=float(m.group(1)) * 1e6)
            blocks.append(current)
            section = ""
            continue
        if current is None:
            continue

        if "ANTENNA INPUT PARAMETERS" in line:
            section = "input_params"
            continue
        if "RADIATION PATTERNS" in line:
            section = "pattern"
            continue
        if "POWER BUDGET" in line or "CURRENTS AND LOCATION" in line:
            section = ""
            continue

        m = _INPUT_POWER_RE.search(line)
        if m:
            current.input_power_w = float(m.group(1))
            continue
        m = _RADIATED_POWER_RE.search(line)
        if m:
            current.radiated_power_w = float(m.group(1))
            continue
        m = _EFFICIENCY_RE.search(line)
        if m:
            current.efficiency = float(m.group(1)) / 100.0
            continue

        if section == "input_params" and current.impedance is None:
            imp = _parse_impedance_row(line)
            if imp is not None:
                current.impedance = imp
        elif section == "pattern":
            point = _parse_pattern_row(line)
            if point is not None:
                current.pattern.append(point)

    if not blocks:
        raise NEC2ParseError(
            "nec2c output contains no FREQUENCY block — output is empty, "
            "truncated, or the run aborted before the frequency loop"
        )
    for b in blocks:
        if b.impedance is None:
            raise NEC2ParseError(
                f"no ANTENNA INPUT PARAMETERS impedance found for "
                f"{b.frequency_hz / 1e6:.3f} MHz — check the EX card"
            )
    return blocks
