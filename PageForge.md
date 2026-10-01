# PageForge

**PageForge** is a lightweight desktop GUI for combining images from a folder into a single PDF.

It is designed especially for scanned documents, records, books, maps, and other page-image collections where **every source image must remain completely intact**.

## Features

- Select an input folder containing page images.
- Select the destination PDF file.
- Combines all supported images into one PDF in **natural filename order**.
- Creates a separate PDF page for every source image.
- Automatically sizes each PDF page to the **aspect ratio of the corresponding image**.
- Preserves the complete original image — **no cropping, stretching, or distortion**.
- Displays image dimensions and aspect ratios before conversion.
- Shows page count and image-format statistics.
- Displays conversion progress.
- Runs PDF generation in a background thread so the GUI remains responsive.
- Confirms before overwriting an existing PDF.
- Supports transparent images by flattening transparency onto a white background.
- Modern, simple PySide6 interface.

## Supported Image Formats

PageForge recognizes:

- PNG
- JPG / JPEG
- WEBP
- BMP
- TIFF / TIF

Files with other extensions are ignored.

## Requirements

- Python 3.10 or newer is recommended.
- [PySide6](https://pypi.org/project/PySide6/)
- [Pillow](https://pypi.org/project/Pillow/)

Install the dependencies with:

```bash
pip install PySide6 Pillow
```

On systems where `pip` maps to a different Python installation, use:

```bash
python -m pip install PySide6 Pillow
```

## Running PageForge

Place `pageforge.py` in a convenient directory and run:

```bash
python pageforge.py
```

The PageForge window will open.

## How to Use

### 1. Select the source folder

Click **Browse** next to **Source Folder** and select the folder containing the page images.

PageForge scans the folder and lists all supported images.

### 2. Check the page order

The image list shows:

- Page number
- Filename
- Image dimensions
- Aspect ratio

Files are sorted using **natural filename sorting**.

For example:

```text
1.png
2.png
3.png
...
9.png
10.png
11.png
```

rather than:

```text
1.png
10.png
11.png
2.png
3.png
```

For best results, name scanned pages sequentially.

### 3. Select the output PDF

Choose the location and filename for the resulting PDF.

Example:

```text
jamabandi_1_to_65.pdf
```

### 4. Create the PDF

Click **Create PDF**.

PageForge creates one PDF page for each source image.

The PDF page dimensions are calculated from the image dimensions so that the original page fits completely without distortion.

## Page Sizing

PageForge does **not** force every image into A4, Letter, or another fixed paper size.

Instead, each PDF page follows the source image's aspect ratio.

For example:

```text
Source image              PDF page
-------------             --------
1600 × 2200               1600 × 2200 ratio
2000 × 1500               2000 × 1500 ratio
2480 × 3508               2480 × 3508 ratio
```

This approach is useful when a collection contains pages with different dimensions or orientations.

### Why this matters

Traditional image-to-PDF conversion can accidentally:

- crop the edges of a page,
- stretch the image,
- squeeze a page into a different aspect ratio,
- or add unwanted borders.

PageForge avoids these problems by using the original image dimensions to determine the PDF page size.

## Recommended Folder Structure

A simple project can look like this:

```text
PageForge/
├── pageforge.py
├── README.md
└── pages/
    ├── 1.png
    ├── 2.png
    ├── 3.png
    ├── ...
    └── 65.png
```

The output PDF can be stored outside the source folder or in another directory.

## Example: Scanned Document

Suppose a folder contains:

```text
1.png
2.png
3.png
...
65.png
```

Select that folder as the source and choose:

```text
jamabandi_1_to_65.pdf
```

PageForge will produce a single 65-page PDF:

```text
1.png  → PDF page 1
2.png  → PDF page 2
3.png  → PDF page 3
...
65.png → PDF page 65
```

Each page retains its original proportions.

## Important Notes

### File order

PageForge sorts filenames naturally, but it cannot determine the logical order of pages if filenames themselves are ambiguous.

For example, these are recommended:

```text
1.png
2.png
3.png
...
10.png
```

or:

```text
001.png
002.png
003.png
...
010.png
```

### Existing output files

If the selected PDF already exists, PageForge asks for confirmation before replacing it.

### Image quality

PageForge uses the source images as the basis for the PDF pages. It does not intentionally resize them to a fixed page format.

Very large source images can therefore produce a relatively large PDF.

### Transparency

Images with transparency are converted to RGB with a white background before being written to the PDF.

## Project Purpose

PageForge is intended to be a small, focused utility rather than a document-management system.

Its main job is:

> **Take a folder of page images and turn them into one correctly ordered PDF without changing the pages.**

This makes it useful for:

- scanned land/revenue records
- historical documents
- books and manuscripts
- maps
- receipts and forms
- archival page images
- OCR preparation
- document sharing
- multi-page image collections

## Technology

PageForge is built with:

- **Python**
- **PySide6** — graphical user interface
- **Pillow** — image handling and PDF generation

No database or external service is required.

## License

Add the project's preferred license here if the project is to be distributed publicly.

For example:

```text
MIT License
```

## Version

**PageForge 1.0**

A small standalone image-to-PDF utility focused on preserving original page geometry.
