#!/usr/bin/env python3
"""Interactive tissue area measurement from TIFF or common image files.

Workflow:
1. Open an image or iterate through a folder of images.
2. Calibrate scale once, either by clicking the scale bar or using a fixed pixel length.
3. Click one point inside the tissue to measure for each image.
4. Refine the mask with an OpenCV brush editor if needed.
5. Script fills interior holes inside the outer contour and reports pixel area
   plus real area. Folder mode also writes a summary CSV.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

import cv2
import matplotlib.pyplot as plt
import numpy as np
from skimage import exposure, filters, measure, morphology
from tifffile import imread


Point = Tuple[int, int]


@dataclass
class MeasurementResult:
    image_name: str
    pixel_area: int
    um_per_pixel: float
    area_um2: float
    area_mm2: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure tissue area from TIFF/images using interactive scale calibration."
    )
    parser.add_argument(
        "input_path",
        help="Path to an image file or a folder containing .tif/.tiff images",
    )
    parser.add_argument(
        "--scale-um",
        type=float,
        default=None,
        help="Real length of the selected scale bar in micrometers. If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--fixed-scale-pixels",
        type=float,
        default=None,
        help="Use a fixed scale bar pixel length and skip manual scale selection.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory for overlay/mask/result files (default: outputs)",
    )
    parser.add_argument(
        "--min-object-size",
        type=int,
        default=1500,
        help="Minimum connected component size to keep during cleanup.",
    )
    parser.add_argument(
        "--closing-radius",
        type=int,
        default=9,
        help="Morphology closing disk radius.",
    )
    parser.add_argument(
        "--opening-radius",
        type=int,
        default=3,
        help="Morphology opening disk radius.",
    )
    return parser.parse_args()


def read_image(path: Path) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix in {".tif", ".tiff"}:
        # Some microscope TIFFs include a second low-res thumbnail page.
        # Always read page 0 so downstream processing uses the full-resolution image.
        img = imread(str(path), key=0)
        if img.ndim == 2:
            img = np.stack([img] * 3, axis=-1)
        elif img.ndim == 3 and img.shape[-1] > 3:
            img = img[..., :3]
    else:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise FileNotFoundError(f"Unable to read image: {path}")
        img = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    if img.dtype != np.uint8:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return img


def collect_input_images(input_path: Path) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        images = sorted(
            [
                path
                for pattern in ("*.tif", "*.tiff", "*.TIF", "*.TIFF")
                for path in input_path.glob(pattern)
            ]
        )
        if not images:
            raise FileNotFoundError(f"No TIFF files found in folder: {input_path}")
        return images
    raise FileNotFoundError(f"Input path does not exist: {input_path}")


def request_points(
    image: np.ndarray, num_points: int, title: str, marker_color: str = "red"
) -> List[Point]:
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(image)
    ax.set_title(title)
    ax.axis("off")

    points: List[Point] = []

    def onclick(event) -> None:
        if event.xdata is None or event.ydata is None:
            return
        x, y = int(round(event.xdata)), int(round(event.ydata))
        points.append((x, y))
        ax.plot(x, y, marker="o", color=marker_color, markersize=8)
        ax.text(x + 8, y + 8, str(len(points)), color=marker_color, fontsize=12)
        fig.canvas.draw_idle()
        if len(points) >= num_points:
            plt.close(fig)

    fig.canvas.mpl_connect("button_press_event", onclick)
    plt.show()

    if len(points) != num_points:
        raise RuntimeError(f"Expected {num_points} points, got {len(points)}")
    return points


def compose_overlay(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    overlay = image.copy()
    overlay[mask] = (
        0.55 * overlay[mask] + 0.45 * np.array([255, 80, 80], dtype=np.float32)
    ).astype(np.uint8)
    contour_mask = (mask.astype(np.uint8) * 255).copy()
    contours, _ = cv2.findContours(
        contour_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(overlay, contours, -1, (0, 255, 0), 2)
    return overlay


def edit_mask_interactively(image: np.ndarray, initial_mask: np.ndarray) -> np.ndarray:
    """OpenCV brush editor for mask refinement."""
    mask = initial_mask.copy().astype(np.uint8)
    original_mask = mask.copy()
    brush_radius = 80
    drawing = False
    draw_value = True
    last_point: Point | None = None
    window_name = "Mask Editor"

    h, w = mask.shape
    max_display_dim = 1400
    scale = min(1.0, max_display_dim / max(h, w))

    def to_image_coords(x: int, y: int) -> Point:
        if scale == 1.0:
            return x, y
        return int(round(x / scale)), int(round(y / scale))

    def draw_brush_segment(start: Point, end: Point, value: bool) -> None:
        color = 1 if value else 0
        cv2.line(
            mask,
            start,
            end,
            color=color,
            thickness=brush_radius * 2,
            lineType=cv2.LINE_AA,
        )
        cv2.circle(mask, end, brush_radius, color=color, thickness=-1, lineType=cv2.LINE_AA)

    def render() -> None:
        overlay = compose_overlay(image, mask.astype(bool))
        display = cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR)
        text = (
            f"Left:erase  Right:add  +/-:brush  Enter:confirm  r:reset  "
            f"Brush:{brush_radius}px"
        )
        cv2.rectangle(display, (0, 0), (min(display.shape[1], 900), 36), (20, 20, 20), -1)
        cv2.putText(
            display,
            text,
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        if scale != 1.0:
            resized = cv2.resize(
                display,
                (int(round(display.shape[1] * scale)), int(round(display.shape[0] * scale))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            resized = display
        cv2.imshow(window_name, resized)

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        nonlocal drawing, draw_value, last_point
        image_point = to_image_coords(x, y)
        image_point = (
            int(np.clip(image_point[0], 0, w - 1)),
            int(np.clip(image_point[1], 0, h - 1)),
        )

        if event == cv2.EVENT_LBUTTONDOWN:
            drawing = True
            draw_value = False
            last_point = image_point
            draw_brush_segment(image_point, image_point, False)
            render()
        elif event == cv2.EVENT_RBUTTONDOWN:
            drawing = True
            draw_value = True
            last_point = image_point
            draw_brush_segment(image_point, image_point, True)
            render()
        elif event == cv2.EVENT_MOUSEMOVE and drawing and last_point is not None:
            draw_brush_segment(last_point, image_point, draw_value)
            last_point = image_point
            render()
        elif event in (cv2.EVENT_LBUTTONUP, cv2.EVENT_RBUTTONUP):
            if drawing and last_point is not None:
                draw_brush_segment(last_point, image_point, draw_value)
            drawing = False
            last_point = None
            render()

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window_name, on_mouse)
    render()

    while True:
        key = cv2.waitKey(16) & 0xFF
        if key in (13, 10):
            break
        if key in (ord("r"), ord("R")):
            mask = original_mask.copy()
            render()
        elif key in (ord("+"), ord("=")):
            brush_radius = min(brush_radius + 2, 200)
            render()
        elif key in (ord("-"), ord("_")):
            brush_radius = max(brush_radius - 2, 1)
            render()
        elif key == 27:
            break

        visible = cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE)
        if visible < 1:
            break

    try:
        cv2.destroyWindow(window_name)
    except cv2.error:
        pass
    return mask.astype(bool)


def prompt_scale_length(provided: float | None) -> float:
    if provided is not None and provided > 0:
        return provided
    raw = input("Enter the real scale bar length in micrometers (e.g. 100): ").strip()
    value = float(raw)
    if value <= 0:
        raise ValueError("Scale length must be positive.")
    return value


def scale_um_per_pixel(scale_points: Sequence[Point], scale_length_um: float) -> float:
    (x1, y1), (x2, y2) = scale_points
    pixel_length = float(np.hypot(x2 - x1, y2 - y1))
    if pixel_length <= 0:
        raise ValueError("Scale bar pixel length must be positive.")
    return scale_length_um / pixel_length


def scale_um_per_pixel_from_fixed_pixels(
    scale_length_um: float, fixed_scale_pixels: float
) -> float:
    if fixed_scale_pixels <= 0:
        raise ValueError("Fixed scale pixel length must be positive.")
    return scale_length_um / fixed_scale_pixels


def build_exclusion_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)

    # Exclude orange scale bar/text and very bright annotation pixels.
    orange = cv2.inRange(hsv, (5, 80, 80), (30, 255, 255)) > 0
    bright = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) > 245

    # Exclude a small bottom-right patch where scale bars usually live.
    h, w = image.shape[:2]
    corner = np.zeros((h, w), dtype=bool)
    corner[int(h * 0.88) :, int(w * 0.82) :] = True

    return orange | bright | corner


def segment_candidates(
    image: np.ndarray,
    min_object_size: int,
    closing_radius: int,
    opening_radius: int,
) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    gray = exposure.equalize_adapthist(gray, clip_limit=0.03)
    gray = (gray * 255).astype(np.uint8)

    exclusion = build_exclusion_mask(image)

    threshold = filters.threshold_otsu(gray[~exclusion])
    mask = gray > threshold
    mask[exclusion] = False

    mask = morphology.remove_small_objects(mask, min_size=min_object_size)
    mask = morphology.binary_closing(mask, morphology.disk(closing_radius))
    mask = morphology.binary_opening(mask, morphology.disk(opening_radius))
    mask = morphology.remove_small_holes(mask, area_threshold=min_object_size * 2)

    return mask


def pick_component_from_seed(mask: np.ndarray, seed: Point) -> np.ndarray:
    labels = measure.label(mask)
    x, y = seed
    h, w = labels.shape
    x = int(np.clip(x, 0, w - 1))
    y = int(np.clip(y, 0, h - 1))

    label_id = labels[y, x]
    if label_id == 0:
        regions = measure.regionprops(labels)
        if not regions:
            raise RuntimeError("No candidate tissue regions were found.")

        best_region = min(
            regions,
            key=lambda region: np.hypot(region.centroid[1] - x, region.centroid[0] - y),
        )
        label_id = best_region.label

    tissue_mask = labels == label_id
    tissue_mask = morphology.binary_closing(tissue_mask, morphology.disk(7))
    return fill_component_holes(tissue_mask)


def fill_component_holes(mask: np.ndarray) -> np.ndarray:
    """Fill all internal holes so area matches the full outer contour."""
    contour_mask = (mask.astype(np.uint8) * 255).copy()
    contours, _ = cv2.findContours(
        contour_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    filled = np.zeros_like(contour_mask)
    cv2.drawContours(filled, contours, -1, color=255, thickness=cv2.FILLED)
    return filled > 0


def calculate_area(mask: np.ndarray, um_per_pixel: float) -> MeasurementResult:
    pixel_area = int(mask.sum())
    area_um2 = pixel_area * (um_per_pixel**2)
    area_mm2 = area_um2 / 1e6
    return MeasurementResult(
        image_name="",
        pixel_area=pixel_area,
        um_per_pixel=um_per_pixel,
        area_um2=area_um2,
        area_mm2=area_mm2,
    )


def draw_overlay(image: np.ndarray, mask: np.ndarray, seed: Point) -> np.ndarray:
    overlay = compose_overlay(image, mask)
    cv2.circle(overlay, seed, 6, (255, 255, 0), -1)
    return overlay


def save_results(
    output_dir: Path,
    image_path: Path,
    image: np.ndarray,
    mask: np.ndarray,
    overlay: np.ndarray,
    result: MeasurementResult,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem

    mask_path = output_dir / f"{stem}_mask.png"
    overlay_path = output_dir / f"{stem}_overlay.png"

    cv2.imwrite(str(mask_path), (mask.astype(np.uint8) * 255))
    cv2.imwrite(str(overlay_path), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    axes[0].imshow(image)
    axes[0].set_title("Original")
    axes[1].imshow(mask, cmap="gray")
    axes[1].set_title("Mask")
    axes[2].imshow(overlay)
    axes[2].set_title("Overlay")
    for ax in axes:
        ax.axis("off")
    fig.tight_layout()
    preview_path = output_dir / f"{stem}_preview.png"
    fig.savefig(preview_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved mask: {mask_path}")
    print(f"Saved overlay: {overlay_path}")
    print(f"Saved preview: {preview_path}")


def save_summary_csv(output_dir: Path, results: Sequence[MeasurementResult]) -> None:
    summary_path = output_dir / "summary_measurements.csv"
    lines = ["image,pixel_area,um_per_pixel,area_um2,area_mm2"]
    for result in results:
        lines.append(
            f"{result.image_name},{result.pixel_area},{result.um_per_pixel:.8f},"
            f"{result.area_um2:.4f},{result.area_mm2:.8f}"
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved summary table: {summary_path}")


def measure_single_image(
    image_path: Path,
    output_dir: Path,
    um_per_pixel: float,
    image_index: int,
    total_images: int,
    args: argparse.Namespace,
) -> MeasurementResult:
    image = read_image(image_path)
    print()
    print(f"[{image_index}/{total_images}] Measuring {image_path.name}")
    print("Click one point inside the tissue you want to measure.")
    seed = request_points(
        image,
        num_points=1,
        title=f"{image_path.name}: click one point inside the target tissue",
        marker_color="yellow",
    )[0]

    candidates = segment_candidates(
        image=image,
        min_object_size=args.min_object_size,
        closing_radius=args.closing_radius,
        opening_radius=args.opening_radius,
    )
    tissue_mask = pick_component_from_seed(candidates, seed)
    print(
        "Brush edit: left-click to erase, right-click to add, +/- to resize brush, Enter to confirm."
    )
    tissue_mask = edit_mask_interactively(image, tissue_mask)
    result = calculate_area(tissue_mask, um_per_pixel)
    result.image_name = image_path.name
    overlay = draw_overlay(image, tissue_mask, seed)

    print(f"Scale calibration: {um_per_pixel:.6f} um/pixel")
    print(f"Tissue area: {result.pixel_area} pixels")
    print(f"Tissue area: {result.area_um2:.2f} um^2")
    print(f"Tissue area: {result.area_mm2:.6f} mm^2")

    save_results(output_dir, image_path, image, tissue_mask, overlay, result)
    return result


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    image_paths = collect_input_images(input_path)

    scale_length_um = prompt_scale_length(args.scale_um)
    if args.fixed_scale_pixels is not None:
        um_per_pixel = scale_um_per_pixel_from_fixed_pixels(
            scale_length_um, args.fixed_scale_pixels
        )
        print(
            f"Using fixed scale bar length: {args.fixed_scale_pixels:.2f} pixels "
            f"for {scale_length_um:.2f} um"
        )
    else:
        image = read_image(image_paths[0])
        print("Step 1/2: click the two ends of the scale bar on the first image.")
        scale_points = request_points(
            image,
            num_points=2,
            title="Click the two ends of the scale bar, then close automatically",
            marker_color="orange",
        )
        um_per_pixel = scale_um_per_pixel(scale_points, scale_length_um)

    results: List[MeasurementResult] = []
    for index, image_path in enumerate(image_paths, start=1):
        result = measure_single_image(
            image_path=image_path,
            output_dir=output_dir,
            um_per_pixel=um_per_pixel,
            image_index=index,
            total_images=len(image_paths),
            args=args,
        )
        results.append(result)

    if len(results) > 1:
        print()
        print(f"Processed {len(results)} images.")
    save_summary_csv(output_dir, results)


if __name__ == "__main__":
    main()
