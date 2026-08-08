"""Create opaque optical-flow in-betweens for a Phoebe Cleaner sprite atlas."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--input-frames", type=int, default=15)
    parser.add_argument("--columns", type=int, default=5)
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=384)
    return parser.parse_args()


def composite_gray(frame: np.ndarray) -> np.ndarray:
    alpha = frame[:, :, 3:4].astype(np.float32) / 255.0
    bgr = frame[:, :, :3].astype(np.float32)
    composite = bgr * alpha + 255.0 * (1.0 - alpha)
    return cv2.cvtColor(composite.astype(np.uint8), cv2.COLOR_BGR2GRAY)


def warp(image: np.ndarray, flow: np.ndarray, amount: float) -> np.ndarray:
    height, width = image.shape[:2]
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )
    map_x = grid_x - flow[:, :, 0] * amount
    map_y = grid_y - flow[:, :, 1] * amount
    return cv2.remap(
        image,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def premultiplied(frame: np.ndarray) -> np.ndarray:
    alpha = frame[:, :, 3:4].astype(np.float32) / 255.0
    result = np.empty(frame.shape, dtype=np.float32)
    result[:, :, :3] = frame[:, :, :3].astype(np.float32) * alpha
    result[:, :, 3:4] = alpha
    return result


def unpremultiply(frame: np.ndarray) -> np.ndarray:
    alpha = np.clip(frame[:, :, 3:4], 0.0, 1.0)
    color = np.divide(
        frame[:, :, :3],
        np.maximum(alpha, 1.0 / 255.0),
        out=np.zeros_like(frame[:, :, :3]),
        where=alpha > 0.0,
    )
    result = np.empty(frame.shape, dtype=np.uint8)
    result[:, :, :3] = np.clip(color, 0.0, 255.0).astype(np.uint8)
    result[:, :, 3] = np.clip(alpha[:, :, 0] * 255.0, 0.0, 255.0).astype(np.uint8)
    return result


def interpolate(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    first_gray = composite_gray(first)
    second_gray = composite_gray(second)
    settings = dict(
        pyr_scale=0.5,
        levels=4,
        winsize=31,
        iterations=5,
        poly_n=7,
        poly_sigma=1.5,
        flags=cv2.OPTFLOW_FARNEBACK_GAUSSIAN,
    )
    forward = cv2.calcOpticalFlowFarneback(first_gray, second_gray, None, **settings)
    backward = cv2.calcOpticalFlowFarneback(second_gray, first_gray, None, **settings)
    first_warped = warp(premultiplied(first), forward, 0.5)
    second_warped = warp(premultiplied(second), backward, 0.5)
    return unpremultiply((first_warped + second_warped) * 0.5)


def main() -> None:
    args = parse_args()
    atlas = cv2.imread(str(args.input), cv2.IMREAD_UNCHANGED)
    if atlas is None or atlas.ndim != 3 or atlas.shape[2] != 4:
        raise SystemExit(f"Expected a readable BGRA atlas: {args.input}")

    source_frames: list[np.ndarray] = []
    for index in range(args.input_frames):
        column = index % args.columns
        row = index // args.columns
        x = column * args.cell_width
        y = row * args.cell_height
        source_frames.append(atlas[y : y + args.cell_height, x : x + args.cell_width].copy())

    output_frames: list[np.ndarray] = []
    for index, frame in enumerate(source_frames[:-1]):
        output_frames.append(frame)
        output_frames.append(interpolate(frame, source_frames[index + 1]))
    output_frames.append(source_frames[-1])

    output_rows = math.ceil(len(output_frames) / args.columns)
    output = np.zeros(
        (output_rows * args.cell_height, args.columns * args.cell_width, 4),
        dtype=np.uint8,
    )
    for index, frame in enumerate(output_frames):
        column = index % args.columns
        row = index // args.columns
        x = column * args.cell_width
        y = row * args.cell_height
        output[y : y + args.cell_height, x : x + args.cell_width] = frame

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), output, [cv2.IMWRITE_PNG_COMPRESSION, 7]):
        raise SystemExit(f"Failed to write {args.output}")
    print(f"Wrote {args.output}: {len(source_frames)} -> {len(output_frames)} frames")


if __name__ == "__main__":
    main()
