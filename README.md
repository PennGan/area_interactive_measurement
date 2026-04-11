# Tissue Area Interactive

Interactive Python script for measuring tissue area from TIFF images with a fixed microscope scale bar.

The workflow is designed for semi-automatic measurement:

1. Load one TIFF image or a folder of TIFF images.
2. Use a fixed scale bar length in pixels or calibrate once from the first image.
3. Click one point inside the target tissue for each image.
4. Refine the segmentation with an OpenCV brush editor.
5. Export per-image mask and overlay previews, plus a single summary CSV.

## Features

- Supports `.tif` and `.tiff` input
- Supports single-image and batch folder processing
- Fixed scale bar pixel mode to skip manual scale calibration
- Measures full outer contour area, including internal holes
- OpenCV brush editing for manual erase/add correction
- Writes one summary CSV for all processed images

## Requirements

- Python 3.9+
- `numpy`
- `opencv-python`
- `matplotlib`
- `scikit-image`
- `tifffile`

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Usage

Process a single image:

```bash
python tissue_area_interactive.py path/to/image.tif --scale-um 100 --fixed-scale-pixels 194
```

Process a folder of TIFF images:

```bash
python tissue_area_interactive.py path/to/folder --scale-um 100 --fixed-scale-pixels 194
```

If `--fixed-scale-pixels` is omitted, the script asks you to click the two ends of the scale bar on the first image.

## Interactive Controls

After automatic segmentation, an OpenCV editor window opens:

- Left mouse drag: erase mask area
- Right mouse drag: add mask area
- `+` / `-`: change brush size
- `r`: reset to the automatic segmentation
- `Enter`: confirm the current mask and continue
- `Esc`: close the editor and continue with the current mask

The brush starts at `80 px` by default.

## Output

The script writes results to `outputs/` by default:

- `*_mask.png`: binary mask
- `*_overlay.png`: overlay with contour
- `*_preview.png`: three-panel preview
- `summary_measurements.csv`: combined results for all processed images

The summary CSV contains:

- `image`
- `pixel_area`
- `um_per_pixel`
- `area_um2`
- `area_mm2`

## Export Only The First TIFF Page

Some TIFF files contain multiple pages:

- page 0: the full-resolution image
- page 1: a low-resolution thumbnail used by Preview

To batch-export only the first page into single-page TIFF files:

```bash
python extract_first_tiff_page.py path/to/folder --output-dir extracted_tiffs
```

If the TIFFs are inside nested subfolders and you want to keep the same folder structure
in the output directory:

```bash
python extract_first_tiff_page.py path/to/folder --output-dir extracted_tiffs --recursive
```

To process a single file:

```bash
python extract_first_tiff_page.py path/to/image.tif --output-dir extracted_tiffs
```

If you want to overwrite existing outputs:

```bash
python extract_first_tiff_page.py path/to/folder --output-dir extracted_tiffs --overwrite
```

## Notes

- Area is measured using the full outer contour of the tissue.
- Internal dark holes are filled and counted as part of the tissue area.
- The fixed scale bar mode is useful when every image uses the same scale bar size.
