"""Requirement-driven antenna topology search and honest solver verification."""

from __future__ import annotations

import inspect
import math
import shutil
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np

from yaf_core.domain.discovery import (
    AntennaCandidate,
    AntennaTopology,
    CandidateMetrics,
    DiscoveryRequirements,
    EvaluationMode,
    RequirementCheck,
)
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationResult, SimulationSpec
from yaf_core.geometry.parametric import ParametricGenerator
from yaf_solvers.base import BaseSolverAdapter

C0 = 299_792_458.0

ProgressCallback = Callable[
    [str, float, list[AntennaCandidate]], Awaitable[None] | None
]

_GAIN_BASELINE = {
    AntennaTopology.DIPOLE: 2.15,
    AntennaTopology.PATCH: 6.5,
    AntennaTopology.BOWTIE: 4.2,
    AntennaTopology.SPIRAL: 4.0,
    AntennaTopology.MEANDER: 1.6,
    AntennaTopology.FRACTAL: 3.2,
    AntennaTopology.HORN: 10.5,
}

_EFFICIENCY_BASELINE = {
    AntennaTopology.DIPOLE: 0.94,
    AntennaTopology.PATCH: 0.79,
    AntennaTopology.BOWTIE: 0.88,
    AntennaTopology.SPIRAL: 0.82,
    AntennaTopology.MEANDER: 0.65,
    AntennaTopology.FRACTAL: 0.72,
    AntennaTopology.HORN: 0.92,
}

_FRACTIONAL_BANDWIDTH = {
    AntennaTopology.DIPOLE: 0.10,
    AntennaTopology.PATCH: 0.045,
    AntennaTopology.BOWTIE: 0.38,
    AntennaTopology.SPIRAL: 0.55,
    AntennaTopology.MEANDER: 0.055,
    AntennaTopology.FRACTAL: 0.18,
    AntennaTopology.HORN: 0.42,
}

_MATCHED_VSWR = {
    AntennaTopology.DIPOLE: 1.35,
    AntennaTopology.PATCH: 1.28,
    AntennaTopology.BOWTIE: 1.42,
    AntennaTopology.SPIRAL: 1.55,
    AntennaTopology.MEANDER: 1.70,
    AntennaTopology.FRACTAL: 1.62,
    AntennaTopology.HORN: 1.25,
}

_NOVELTY_PRIOR = {
    AntennaTopology.DIPOLE: 0.08,
    AntennaTopology.PATCH: 0.12,
    AntennaTopology.BOWTIE: 0.36,
    AntennaTopology.SPIRAL: 0.45,
    AntennaTopology.MEANDER: 0.58,
    AntennaTopology.FRACTAL: 0.72,
    AntennaTopology.HORN: 0.18,
}


async def _report(
    callback: ProgressCallback | None,
    stage: str,
    progress: float,
    candidates: list[AntennaCandidate],
) -> None:
    if callback is None:
        return
    returned = callback(stage, progress, candidates)
    if inspect.isawaitable(returned):
        await returned


def _geometry_dimensions(geometry: Geometry) -> tuple[float, float, float]:
    if not geometry.vertices:
        return (0.0, 0.0, 0.0)
    vertices = np.asarray(geometry.vertices, dtype=float)
    extent = np.max(vertices, axis=0) - np.min(vertices, axis=0)
    return tuple(float(value) for value in extent[:3])  # type: ignore[return-value]


def _bowtie(arm_length: float, flare_width: float, gap: float) -> Geometry:
    half_gap = gap / 2
    half_width = flare_width / 2
    vertices = [
        [-half_gap, 0.0, 0.0],
        [-half_gap - arm_length, -half_width, 0.0],
        [-half_gap - arm_length, half_width, 0.0],
        [half_gap, 0.0, 0.0],
        [half_gap + arm_length, -half_width, 0.0],
        [half_gap + arm_length, half_width, 0.0],
    ]
    return Geometry(
        name="bowtie",
        vertices=vertices,
        faces=[[0, 1, 2], [3, 5, 4]],
        metadata={"arm_length": arm_length, "flare_width": flare_width, "gap": gap},
    )


def _meander(width: float, height: float, trace_width: float, turns: int) -> Geometry:
    """Create a printable serpentine conductor as disconnected ribbon quads."""
    points: list[tuple[float, float]] = []
    y_values = np.linspace(-height / 2, height / 2, turns + 1)
    for index, y_value in enumerate(y_values):
        x_value = width / 2 if index % 2 else -width / 2
        points.append((x_value, float(y_value)))

    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for start, end in zip(points, points[1:], strict=False):
        x0, y0 = start
        x1, y1 = end
        dx, dy = x1 - x0, y1 - y0
        length = max(math.hypot(dx, dy), 1e-12)
        nx, ny = -dy / length * trace_width / 2, dx / length * trace_width / 2
        base = len(vertices)
        vertices.extend([
            [x0 + nx, y0 + ny, 0.0],
            [x0 - nx, y0 - ny, 0.0],
            [x1 - nx, y1 - ny, 0.0],
            [x1 + nx, y1 + ny, 0.0],
        ])
        faces.extend([[base, base + 1, base + 2], [base, base + 2, base + 3]])
    return Geometry(
        name="meander",
        vertices=vertices,
        faces=faces,
        metadata={"width": width, "height": height, "trace_width": trace_width, "turns": turns},
    )


class AntennaDiscoveryEngine:
    """Explore topology families, refine dimensions, rank, then verify."""

    def __init__(self, requirements: DiscoveryRequirements) -> None:
        self.requirements = requirements
        self.rng = np.random.default_rng(requirements.seed)
        self.center_hz = sum(requirements.frequency_range_hz) / 2
        self.wavelength = C0 / self.center_hz

    async def run(
        self, progress_callback: ProgressCallback | None = None
    ) -> tuple[list[AntennaCandidate], list[str]]:
        budget = self.requirements.candidate_budget
        generations = self.requirements.generations
        topologies = self._ordered_topologies()
        candidates: list[AntennaCandidate] = []

        initial_count = (
            budget
            if generations == 1
            else min(budget, max(len(topologies), math.ceil(budget * 0.55)))
        )
        await _report(progress_callback, "Exploring topology families", 0.05, candidates)
        for index in range(initial_count):
            topology = topologies[index % len(topologies)]
            # Establish a resonant baseline for each family before spending
            # the remaining budget on stochastic exploration.
            tune = 1.0 if index < len(topologies) else float(self.rng.uniform(0.86, 1.14))
            candidates.append(self._create_candidate(topology, tune, generation=0))
            await _report(
                progress_callback,
                "Exploring topology families",
                0.05 + 0.35 * (index + 1) / initial_count,
                candidates,
            )

        remaining = budget - len(candidates)
        for generation in range(1, generations):
            if remaining <= 0:
                break
            ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
            parents = ranked[: min(4, len(ranked))]
            generations_left = generations - generation
            generation_count = min(remaining, math.ceil(remaining / generations_left))
            sigma = 0.055 / generation
            for index in range(generation_count):
                parent = parents[index % len(parents)]
                parent_tune = parent.parameters.get("tune", 1.0)
                tune = float(np.clip(parent_tune * (1 + self.rng.normal(0, sigma)), 0.78, 1.22))
                candidates.append(
                    self._create_candidate(
                        parent.topology,
                        tune,
                        generation=generation,
                        parent_id=parent.id,
                    )
                )
                await _report(
                    progress_callback,
                    f"Refining generation {generation}",
                    0.40 + 0.35 * len(candidates) / budget,
                    candidates,
                )
            remaining = budget - len(candidates)

        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        await _report(progress_callback, "Ranking candidate designs", 0.78, candidates)
        warnings = await self._verify_candidates(candidates, progress_callback)
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        await _report(progress_callback, "Discovery complete", 1.0, candidates)
        return candidates, warnings

    def _ordered_topologies(self) -> list[AntennaTopology]:
        allowed = list(dict.fromkeys(self.requirements.allowed_topologies))
        requested_fraction = (
            self.requirements.frequency_range_hz[1]
            - self.requirements.frequency_range_hz[0]
        ) / self.center_hz
        max_dimension = max(self.requirements.max_dimensions_m)
        compact = max_dimension < 0.35 * self.wavelength
        high_gain = (self.requirements.target_gain_dbi or 0.0) >= 6.0

        def priority(topology: AntennaTopology) -> float:
            value = 0.0
            if requested_fraction > 0.15 and topology in {
                AntennaTopology.BOWTIE,
                AntennaTopology.SPIRAL,
                AntennaTopology.HORN,
            }:
                value += 3.0
            if compact and topology in {
                AntennaTopology.MEANDER,
                AntennaTopology.FRACTAL,
                AntennaTopology.PATCH,
            }:
                value += 3.0
            if high_gain and topology in {AntennaTopology.PATCH, AntennaTopology.HORN}:
                value += 4.0
            value += _NOVELTY_PRIOR[topology] * 0.2
            return value

        return sorted(allowed, key=priority, reverse=True)

    def _create_candidate(
        self,
        topology: AntennaTopology,
        tune: float,
        generation: int,
        parent_id: Any = None,
    ) -> AntennaCandidate:
        geometry, parameters, compact_ratio = self._build_geometry(topology, tune)
        dimensions = _geometry_dimensions(geometry)
        resonance_hz = self.center_hz / tune
        detuning = abs(resonance_hz - self.center_hz) / self.center_hz
        gain = _GAIN_BASELINE[topology] * (0.82 + 0.18 * math.sqrt(compact_ratio))
        gain *= math.exp(-2.2 * detuning**2)
        efficiency = _EFFICIENCY_BASELINE[topology] * math.sqrt(compact_ratio)
        efficiency = float(np.clip(efficiency, 0.15, 0.98))
        bandwidth_hz = _FRACTIONAL_BANDWIDTH[topology] * resonance_hz
        normalized_detuning = detuning / max(_FRACTIONAL_BANDWIDTH[topology] / 2, 0.02)
        vswr = _MATCHED_VSWR[topology] + 1.8 * normalized_detuning**2
        metrics = CandidateMetrics(
            resonance_hz=resonance_hz,
            bandwidth_hz=bandwidth_hz,
            gain_dbi=gain,
            efficiency=efficiency,
            vswr=vswr,
            dimensions_m=dimensions,
        )
        novelty = float(
            np.clip(_NOVELTY_PRIOR[topology] + 0.04 * generation + self.rng.uniform(-0.02, 0.02), 0, 1)
        )
        checks = self._checks(metrics, EvaluationMode.ANALYTICAL_SCREENING)
        score = self._score(metrics, novelty)
        parameters.update({"tune": tune, "compact_ratio": compact_ratio})
        geometry.name = f"{topology.value}_g{generation}"
        geometry.metadata.update({"topology": topology.value, **parameters})
        candidate = AntennaCandidate(
            topology=topology,
            name=f"{topology.value.title()} · G{generation + 1}",
            generation=generation,
            geometry=geometry,
            parameters=parameters,
            metrics=metrics,
            checks=checks,
            score=score,
            novelty_score=novelty,
            parent_id=parent_id,
            warning="Analytical screening only; solver verification has not run.",
        )
        candidate.name = f"{topology.value.title()} · generation {generation + 1}"
        return candidate

    def _build_geometry(
        self, topology: AntennaTopology, tune: float
    ) -> tuple[Geometry, dict[str, float], float]:
        max_width, max_height, max_depth = self.requirements.max_dimensions_m
        generator = ParametricGenerator()
        compact_ratio = 1.0

        if topology is AntennaTopology.DIPOLE:
            desired = 0.48 * self.wavelength * tune
            length = min(desired, max_height * 0.96)
            compact_ratio = min(1.0, length / desired)
            radius = max(min(self.wavelength / 800, max_width / 20), 0.00015)
            geometry = generator.dipole(length, radius=radius)
            geometry.vertices = [
                [vertex[0], vertex[2], vertex[1]] for vertex in geometry.vertices
            ]
            return geometry, {"length_m": length, "radius_m": radius}, compact_ratio

        if topology is AntennaTopology.PATCH:
            eps_r = float(self.rng.choice([2.2, 3.38, 4.4]))
            eps_eff = (eps_r + 1) / 2
            desired_length = 0.48 * self.wavelength / math.sqrt(eps_eff) * tune
            desired_width = 0.58 * self.wavelength / math.sqrt((eps_r + 1) / 2)
            length = min(desired_length, max_width * 0.92)
            width = min(desired_width, max_height * 0.92)
            compact_ratio = min(1.0, length / desired_length, width / desired_width)
            thickness = min(0.0016, max_depth * 0.45)
            geometry = generator.rectangular_patch(width=width, length=length, substrate_thickness=thickness)
            return geometry, {"length_m": length, "width_m": width, "substrate_m": thickness, "eps_r": eps_r}, compact_ratio

        if topology is AntennaTopology.BOWTIE:
            desired_arm = 0.235 * self.wavelength * tune
            arm = min(desired_arm, max_width * 0.46)
            flare = min(0.22 * self.wavelength, max_height * 0.90)
            compact_ratio = min(1.0, arm / desired_arm)
            gap = max(min(0.008 * self.wavelength, max_width * 0.03), 0.0003)
            return _bowtie(arm, flare, gap), {"arm_length_m": arm, "flare_width_m": flare, "gap_m": gap}, compact_ratio

        if topology is AntennaTopology.SPIRAL:
            desired_outer = 0.17 * self.wavelength * tune
            outer = min(desired_outer, min(max_width, max_height) * 0.46)
            compact_ratio = min(1.0, outer / desired_outer)
            inner = max(outer * 0.06, 0.0003)
            turns = float(self.rng.uniform(1.4, 2.8))
            geometry = generator.archimedean_spiral(inner, outer, turns, max(outer * 0.025, 0.0002), segments=96)
            return geometry, {"inner_radius_m": inner, "outer_radius_m": outer, "turns": turns}, compact_ratio

        if topology is AntennaTopology.MEANDER:
            desired_height = 0.19 * self.wavelength * tune
            height = min(desired_height, max_height * 0.90)
            width = min(0.16 * self.wavelength, max_width * 0.90)
            compact_ratio = min(1.0, height / desired_height)
            turns = int(self.rng.integers(5, 10))
            trace = max(min(width / 45, 0.0012), 0.0002)
            return _meander(width, height, trace, turns), {"width_m": width, "height_m": height, "trace_m": trace, "turns": float(turns)}, compact_ratio

        if topology is AntennaTopology.FRACTAL:
            desired_side = 0.29 * self.wavelength * tune
            side = min(desired_side, min(max_width, max_height) * 0.92)
            compact_ratio = min(1.0, side / desired_side)
            order = int(self.rng.integers(1, 4))
            return generator.sierpinski_gasket(order, side), {"side_length_m": side, "order": float(order)}, compact_ratio

        desired_aperture = 0.72 * self.wavelength
        aperture_width = min(desired_aperture, max_width * 0.92)
        aperture_height = min(0.52 * self.wavelength, max_height * 0.92)
        flare_length = min(0.65 * self.wavelength * tune, max_depth * 0.72)
        compact_ratio = min(1.0, aperture_width / desired_aperture, flare_length / (0.65 * self.wavelength * tune))
        waveguide_width = aperture_width * 0.46
        waveguide_height = aperture_height * 0.46
        waveguide_length = min(flare_length * 0.35, max_depth * 0.25)
        geometry = generator.horn_antenna(aperture_width, aperture_height, flare_length, waveguide_width, waveguide_height, waveguide_length)
        return geometry, {"aperture_width_m": aperture_width, "aperture_height_m": aperture_height, "flare_length_m": flare_length}, compact_ratio

    def _checks(
        self, metrics: CandidateMetrics, evidence: EvaluationMode
    ) -> list[RequirementCheck]:
        f_min, f_max = self.requirements.frequency_range_hz
        requested_bandwidth = f_max - f_min
        center_tolerance = max(requested_bandwidth / 2, self.center_hz * 0.02)
        checks = [
            RequirementCheck(key="resonance", label="Resonance in target band", target=center_tolerance, actual=abs(metrics.resonance_hz - self.center_hz), unit="Hz error", comparator="<=", passed=abs(metrics.resonance_hz - self.center_hz) <= center_tolerance, evidence=evidence),
            RequirementCheck(key="bandwidth", label="Bandwidth coverage", target=requested_bandwidth, actual=metrics.bandwidth_hz, unit="Hz", comparator=">=", passed=metrics.bandwidth_hz >= requested_bandwidth, evidence=evidence),
            RequirementCheck(key="vswr", label="VSWR", target=self.requirements.target_vswr, actual=metrics.vswr, unit="ratio", comparator="<=", passed=metrics.vswr <= self.requirements.target_vswr, evidence=evidence),
        ]
        if self.requirements.target_gain_dbi is not None:
            checks.append(RequirementCheck(key="gain", label="Realized gain", target=self.requirements.target_gain_dbi, actual=metrics.gain_dbi, unit="dBi", comparator=">=", passed=metrics.gain_dbi >= self.requirements.target_gain_dbi, evidence=evidence))
        if self.requirements.minimum_efficiency is not None:
            checks.append(RequirementCheck(key="efficiency", label="Radiation efficiency", target=self.requirements.minimum_efficiency, actual=metrics.efficiency, unit="ratio", comparator=">=", passed=metrics.efficiency >= self.requirements.minimum_efficiency, evidence=evidence))
        for key, label, actual, target in zip(
            ("width", "height", "depth"),
            ("Maximum width", "Maximum height", "Maximum depth"),
            metrics.dimensions_m,
            self.requirements.max_dimensions_m,
            strict=True,
        ):
            checks.append(RequirementCheck(key=key, label=label, target=target, actual=actual, unit="m", comparator="<=", passed=actual <= target + 1e-12, evidence=evidence))
        return checks

    def _score(self, metrics: CandidateMetrics, novelty: float) -> float:
        f_min, f_max = self.requirements.frequency_range_hz
        requested_bandwidth = f_max - f_min
        frequency_scale = max(requested_bandwidth / 2, self.center_hz * 0.025)
        frequency_score = math.exp(-((metrics.resonance_hz - self.center_hz) / frequency_scale) ** 2)
        bandwidth_score = min(1.0, metrics.bandwidth_hz / requested_bandwidth)
        gain_target = self.requirements.target_gain_dbi
        gain_score = 1.0 if gain_target is None or metrics.gain_dbi >= gain_target else math.exp(-(gain_target - metrics.gain_dbi) / 2.5)
        vswr_score = 1.0 if metrics.vswr <= self.requirements.target_vswr else math.exp(-(metrics.vswr - self.requirements.target_vswr))
        efficiency_target = self.requirements.minimum_efficiency
        efficiency_score = 1.0 if efficiency_target is None or metrics.efficiency >= efficiency_target else metrics.efficiency / efficiency_target
        size_pass = all(actual <= target + 1e-12 for actual, target in zip(metrics.dimensions_m, self.requirements.max_dimensions_m, strict=True))
        performance = 0.30 * frequency_score + 0.20 * bandwidth_score + 0.20 * gain_score + 0.12 * vswr_score + 0.13 * efficiency_score + 0.05 * float(size_pass)
        score = 0.95 * performance + 0.05 * novelty
        if not size_pass:
            score *= 0.65
        return float(np.clip(score, 0.0, 1.0))

    async def _verify_candidates(
        self,
        candidates: list[AntennaCandidate],
        progress_callback: ProgressCallback | None,
    ) -> list[str]:
        count = self.requirements.verify_top_k
        if count <= 0:
            return ["Real-solver verification was disabled for this discovery run."]

        nec2_available = shutil.which("nec2c") is not None
        try:
            from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

            openems_available = OpenEMSAdapter()._openems_available
        except Exception:
            openems_available = False

        if not nec2_available and not openems_available:
            return [
                "No real EM solver is installed. Candidates are analytically screened, not solver verified."
            ]

        verified = 0
        errors: list[str] = []
        for candidate in candidates:
            if verified >= count:
                break
            try:
                result = await self._solve_candidate(candidate, nec2_available, openems_available)
            except Exception as error:  # noqa: BLE001
                errors.append(f"{candidate.name}: {type(error).__name__}: {error}")
                continue
            if result is None:
                continue
            mode = result.solver_metadata.get("solver_mode", "unknown")
            if mode not in {"native", "subprocess"}:
                errors.append(f"{candidate.name}: solver returned non-physical mode '{mode}'")
                continue
            self._apply_solver_result(candidate, result)
            verified += 1
            await _report(
                progress_callback,
                f"Solver verified {verified}/{count}",
                0.80 + 0.18 * verified / count,
                candidates,
            )

        if verified == 0:
            errors.insert(0, "Installed solvers could not verify a compatible candidate.")
        return errors

    async def _solve_candidate(
        self,
        candidate: AntennaCandidate,
        nec2_available: bool,
        openems_available: bool,
    ) -> SimulationResult | None:
        simulation_spec = SimulationSpec(
            name=f"discovery_{candidate.topology.value}",
            frequency_range=self.requirements.frequency_range_hz,
            frequency_points=51,
            far_field_request={},
        )
        adapter: BaseSolverAdapter
        if candidate.topology is AntennaTopology.DIPOLE and nec2_available:
            from yaf_solvers.nec2_adapter.adapter import NEC2Adapter

            length = candidate.parameters["length_m"]
            geometry = Geometry(
                name=candidate.name,
                vertices=[[0.0, 0.0, -length / 2], [0.0, 0.0, length / 2]],
                faces=[[0, 1]],
            )
            adapter = NEC2Adapter()
        elif openems_available and candidate.topology in {
            AntennaTopology.PATCH,
            AntennaTopology.BOWTIE,
            AntennaTopology.SPIRAL,
            AntennaTopology.MEANDER,
            AntennaTopology.FRACTAL,
        }:
            from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

            geometry = candidate.geometry
            adapter = OpenEMSAdapter()
        else:
            return None
        mesh = await adapter.mesh(geometry, simulation_spec)
        return await adapter.solve(mesh, simulation_spec)

    def _apply_solver_result(
        self, candidate: AntennaCandidate, result: SimulationResult
    ) -> None:
        resonance_hz = candidate.metrics.resonance_hz
        if result.s_params is not None and result.s_params.frequency:
            magnitudes = [abs(value[0][0]) for value in result.s_params.s_matrix]
            resonance_hz = result.s_params.frequency[int(np.argmin(magnitudes))]
        metrics = candidate.metrics.model_copy(
            update={
                "resonance_hz": resonance_hz,
                "gain_dbi": result.gain_dbi if result.gain_dbi is not None else candidate.metrics.gain_dbi,
                "efficiency": result.efficiency if result.efficiency is not None else candidate.metrics.efficiency,
                "vswr": result.vswr if result.vswr is not None else candidate.metrics.vswr,
                "bandwidth_hz": result.bandwidth_hz if result.bandwidth_hz is not None else candidate.metrics.bandwidth_hz,
            }
        )
        candidate.metrics = metrics
        candidate.checks = self._checks(metrics, EvaluationMode.REAL_SOLVER)
        candidate.score = self._score(metrics, candidate.novelty_score)
        candidate.evaluation_mode = EvaluationMode.REAL_SOLVER
        candidate.solver_name = result.solver_name
        candidate.solver_mode = result.solver_metadata.get("solver_mode")
        candidate.warning = None
