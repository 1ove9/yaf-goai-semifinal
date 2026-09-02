"""Deterministic pixel-topology definitions and geometry reconstruction."""

from __future__ import annotations

import hashlib
import math
from collections import deque
from collections.abc import Mapping
from types import MappingProxyType

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_core.domain.geometry import Geometry

C0 = 299_792_458.0


def encode_mask_rle(mask: np.ndarray) -> str:
    """Encode a two-dimensional boolean mask in exact row-major RLE form."""

    if mask.ndim != 2 or mask.size == 0:
        raise ValueError("pixel mask must be a non-empty two-dimensional array")
    flat = mask.astype(bool, copy=False).reshape(-1)
    runs: list[str] = []
    value = bool(flat[0])
    count = 1
    for item in flat[1:]:
        current = bool(item)
        if current == value:
            count += 1
        else:
            runs.append(f"{int(value)}:{count}")
            value = current
            count = 1
    runs.append(f"{int(value)}:{count}")
    return ",".join(runs)


def decode_mask_rle(rle: str, rows: int, columns: int) -> np.ndarray:
    """Decode and validate an exact row-major boolean RLE payload."""

    if rows <= 0 or columns <= 0:
        raise ValueError("pixel mask dimensions must be positive")
    values: list[bool] = []
    try:
        for run in rle.split(","):
            raw_value, raw_count = run.split(":", maxsplit=1)
            if raw_value not in {"0", "1"}:
                raise ValueError
            count = int(raw_count)
            if count <= 0:
                raise ValueError
            values.extend([raw_value == "1"] * count)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid pixel-mask RLE payload") from error
    if len(values) != rows * columns:
        raise ValueError(
            f"pixel-mask RLE has {len(values)} cells; expected {rows * columns}"
        )
    return np.asarray(values, dtype=bool).reshape((rows, columns))


def mask_sha256(mask: np.ndarray) -> str:
    """Hash mask dimensions and bits so the topology is byte-addressable."""

    if mask.ndim != 2:
        raise ValueError("pixel mask must be two-dimensional")
    prefix = f"{mask.shape[0]}x{mask.shape[1]}:".encode("ascii")
    payload = mask.astype(np.uint8, copy=False).tobytes(order="C")
    return hashlib.sha256(prefix + payload).hexdigest()


def is_four_connected(mask: np.ndarray, feed_cell: tuple[int, int]) -> bool:
    """Return whether every metal cell belongs to the feed's 4-neighbor component."""

    if mask.ndim != 2:
        return False
    row, column = feed_cell
    if not (0 <= row < mask.shape[0] and 0 <= column < mask.shape[1]):
        return False
    if not bool(mask[row, column]):
        return False
    metal_count = int(mask.sum())
    seen = {(row, column)}
    pending: deque[tuple[int, int]] = deque([(row, column)])
    while pending:
        current_row, current_column = pending.popleft()
        for next_row, next_column in (
            (current_row - 1, current_column),
            (current_row + 1, current_column),
            (current_row, current_column - 1),
            (current_row, current_column + 1),
        ):
            cell = (next_row, next_column)
            if (
                0 <= next_row < mask.shape[0]
                and 0 <= next_column < mask.shape[1]
                and bool(mask[next_row, next_column])
                and cell not in seen
            ):
                seen.add(cell)
                pending.append(cell)
    return len(seen) == metal_count


def is_left_right_symmetric(mask: np.ndarray) -> bool:
    """Return whether columns mirror exactly across the vertical centerline."""

    return mask.ndim == 2 and bool(np.array_equal(mask, np.fliplr(mask)))


def mask_iou(first: np.ndarray, second: np.ndarray) -> float:
    """Compute intersection-over-union for two same-sized boolean masks."""

    if first.shape != second.shape:
        raise ValueError("IoU masks must have identical dimensions")
    union = int(np.logical_or(first, second).sum())
    if union == 0:
        return 1.0
    intersection = int(np.logical_and(first, second).sum())
    return intersection / union


class PixelTopology(BaseModel):
    """Lossless audit description for one pixel proposal."""

    model_config = ConfigDict(frozen=True)

    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    rle: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metal_pixels: int = Field(gt=0)
    connected_to_feed: bool
    left_right_symmetric: bool
    iou_vs_classic_rectangle: float = Field(ge=0.0, le=1.0)
    novelty_vs_classic_rectangle: float = Field(ge=0.0, le=1.0)


class PixelProposalSpace(BaseModel):
    """Frozen single source of truth for the 16x16 topology search space."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(min_length=1)
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    symmetry: bool = True
    pixel_size_m: float = Field(gt=0.0)
    origin_x_m: float
    origin_y_m: float
    feed_cell: tuple[int, int]
    feed_position_m: tuple[float, float]
    substrate_thickness_m: float = Field(gt=0.0)
    substrate_size_m: tuple[float, float]
    classic_rectangle_rle: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_definition(self) -> PixelProposalSpace:
        row, column = self.feed_cell
        if not (0 <= row < self.rows and 0 <= column < self.columns):
            raise ValueError("pixel-space feed cell is outside the grid")
        if any(size <= 0.0 for size in self.substrate_size_m):
            raise ValueError("pixel-space substrate dimensions must be positive")
        classic = decode_mask_rle(
            self.classic_rectangle_rle,
            self.rows,
            self.columns,
        )
        self.validate_mask(classic)
        return self

    @property
    def minimum_feature_m(self) -> float:
        """Return the physical one-pixel minimum feature size."""

        return self.pixel_size_m

    def classic_mask(self) -> np.ndarray:
        """Rebuild the frozen classic rectangular-patch reference mask."""

        return decode_mask_rle(
            self.classic_rectangle_rle,
            self.rows,
            self.columns,
        )

    def validate_parameters(self, values: Mapping[str, float]) -> None:
        """Validate finite numeric audit parameters for a topology proposal."""

        for name, value in values.items():
            if not name or not math.isfinite(value):
                raise ValueError("pixel proposal parameters must be finite and named")

    def validate_mask(self, mask: np.ndarray) -> None:
        """Reject wrong-sized, asymmetric, feedless, or disconnected metal masks."""

        if mask.shape != (self.rows, self.columns):
            raise ValueError(
                f"pixel mask shape {mask.shape} does not match "
                f"{(self.rows, self.columns)}"
            )
        if self.symmetry and not is_left_right_symmetric(mask):
            raise ValueError("pixel mask violates frozen left/right symmetry")
        if not is_four_connected(mask, self.feed_cell):
            raise ValueError("pixel mask is not 4-connected to the fixed feed")

    def describe_mask(self, mask: np.ndarray) -> PixelTopology:
        """Validate and encode a proposal with its reference-mask novelty."""

        self.validate_mask(mask)
        classic = self.classic_mask()
        iou = mask_iou(mask, classic)
        return PixelTopology(
            rows=self.rows,
            columns=self.columns,
            rle=encode_mask_rle(mask),
            sha256=mask_sha256(mask),
            metal_pixels=int(mask.sum()),
            connected_to_feed=True,
            left_right_symmetric=is_left_right_symmetric(mask),
            iou_vs_classic_rectangle=iou,
            novelty_vs_classic_rectangle=1.0 - iou,
        )

    def decode_topology(self, topology: PixelTopology) -> np.ndarray:
        """Rebuild and authenticate one logged topology descriptor."""

        if (topology.rows, topology.columns) != (self.rows, self.columns):
            raise ValueError("logged topology dimensions do not match pixel space")
        mask = decode_mask_rle(topology.rle, topology.rows, topology.columns)
        if mask_sha256(mask) != topology.sha256:
            raise ValueError("logged topology hash does not match its RLE")
        self.validate_mask(mask)
        expected = self.describe_mask(mask)
        if expected != topology:
            raise ValueError("logged topology metadata is internally inconsistent")
        return mask


def _wifi24_space() -> PixelProposalSpace:
    center_frequency = 2.45e9
    eps_r = 4.4
    substrate_thickness = 1.6e-3
    width = C0 / (2.0 * center_frequency) * math.sqrt(2.0 / (eps_r + 1.0))
    eps_eff = (eps_r + 1.0) / 2.0 + (eps_r - 1.0) / (
        2.0 * math.sqrt(1.0 + 12.0 * substrate_thickness / width)
    )
    delta_length = (
        0.412
        * substrate_thickness
        * (eps_eff + 0.3)
        * (width / substrate_thickness + 0.264)
        / ((eps_eff - 0.258) * (width / substrate_thickness + 0.8))
    )
    length = C0 / (2.0 * center_frequency * math.sqrt(eps_eff)) - 2.0 * delta_length
    rows = 16
    columns = 16
    region_side = 1.25 * max(width, length)
    pixel_size = region_side / rows
    origin = -region_side / 2.0
    feed_x_target = -length * 3.0 / 16.0
    feed_row = min(max(int((feed_x_target - origin) / pixel_size), 0), rows - 1)
    feed_column = columns // 2 - 1
    feed_x = origin + (feed_row + 0.5) * pixel_size

    x_centers = origin + (np.arange(rows) + 0.5) * pixel_size
    y_centers = origin + (np.arange(columns) + 0.5) * pixel_size
    classic = (
        (np.abs(x_centers)[:, None] <= length / 2.0)
        & (np.abs(y_centers)[None, :] <= width / 2.0)
    )
    classic[feed_row, feed_column] = True
    classic[feed_row, columns - 1 - feed_column] = True
    return PixelProposalSpace(
        version="pixel-wifi24-v1-16x16",
        rows=rows,
        columns=columns,
        symmetry=True,
        pixel_size_m=pixel_size,
        origin_x_m=origin,
        origin_y_m=origin,
        feed_cell=(feed_row, feed_column),
        feed_position_m=(feed_x, 0.0),
        substrate_thickness_m=substrate_thickness,
        substrate_size_m=(1.5 * region_side, 1.5 * region_side),
        classic_rectangle_rle=encode_mask_rle(classic),
    )


WIFI24_PIXEL_PROPOSAL_SPACE = _wifi24_space()
PIXEL_PROPOSAL_SPACES: Mapping[str, PixelProposalSpace] = MappingProxyType(
    {WIFI24_PIXEL_PROPOSAL_SPACE.version: WIFI24_PIXEL_PROPOSAL_SPACE}
)


def pixel_geometry(
    space: PixelProposalSpace,
    mask: np.ndarray,
    proposer: str,
) -> tuple[Geometry, PixelTopology]:
    """Build a planar triangle mesh whose unused anchors freeze the grid extent."""

    topology = space.describe_mask(mask)
    z = space.substrate_thickness_m
    x0 = space.origin_x_m
    y0 = space.origin_y_m
    x1 = x0 + space.rows * space.pixel_size_m
    y1 = y0 + space.columns * space.pixel_size_m
    vertices: list[list[float]] = [
        [x0, y0, z],
        [x1, y0, z],
        [x1, y1, z],
        [x0, y1, z],
    ]
    faces: list[list[int]] = []
    for row, column in np.argwhere(mask):
        cell_x0 = x0 + int(row) * space.pixel_size_m
        cell_y0 = y0 + int(column) * space.pixel_size_m
        base = len(vertices)
        vertices.extend(
            [
                [cell_x0, cell_y0, z],
                [cell_x0 + space.pixel_size_m, cell_y0, z],
                [cell_x0 + space.pixel_size_m, cell_y0 + space.pixel_size_m, z],
                [cell_x0, cell_y0 + space.pixel_size_m, z],
            ]
        )
        faces.extend([[base, base + 1, base + 2], [base, base + 2, base + 3]])
    geometry = Geometry(
        name=f"{proposer}_pixel_patch",
        vertices=vertices,
        faces=faces,
        metadata={
            "antenna_class": "pixel_patch",
            "pixel_size": space.pixel_size_m,
            "pixel_space_version": space.version,
            "pixel_mask_rle": topology.rle,
            "pixel_mask_sha256": topology.sha256,
            "substrate_thickness": space.substrate_thickness_m,
            "substrate_length": space.substrate_size_m[0],
            "substrate_width": space.substrate_size_m[1],
            "eps_r": 4.4,
            "loss_tangent": 0.02,
            "feed_x": space.feed_position_m[0],
            "feed_y": space.feed_position_m[1],
        },
    )
    return geometry, topology
