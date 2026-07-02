# Changelog

## 1.5.2

- Reverted the unsafe 1.5.1 runtime wheel-loading approach.
- Kept the Windows x64 extension packaging model with the official bundled PDF renderer wheel.
- Removed PDF worker subprocess code that referenced the `sys` module.
- Hardened `.refbmd` imports with format validation and size limits for manifests, node counts, and embedded images.

## 1.5.0

- Added PDF import support for Add Image, drag and drop, and clipboard file paths.
- PDF pages are rendered into separate image nodes and packed into the `.blend` file.
- PDF pages are arranged top-to-bottom as a separate column when mixed with regular image imports.
- Added an in-editor import progress overlay for longer image and PDF imports.
- Added a bundled Windows x64 PDF rendering wheel for Blender Extensions packaging.
- PDF rendering uses multiple worker processes when possible, with fallback renderers for reliability.

## 1.4.1

- Fixed automatic framing after adding, dropping, pasting, or importing images.
- `.refbmd` imports now select imported board images before framing them.

## 1.4.0

- Added portable `.refbmd` export and import for RefBoard boards.
- Added drag/drop and clipboard import support for `.refbmd` files.
- Added node Image Transform controls for clockwise/counter-clockwise rotation and X/Y mirroring.
- Image transforms are saved in `.refbmd` files as optional secondary settings.
- Alignment, selection outlines, hit testing, and size matching now account for rotated image bounds.

## 1.3.0

- Added Ctrl+V image paste support in RefBoard.
- Supports pasted image files and direct bitmap image data from the clipboard.
- Packs direct clipboard bitmap images into the `.blend` file instead of keeping them linked to temporary files.
- Added Blender-like numeric input and X/Y axis constraints to RefBoard image scaling; axis-constrained scaling moves nodes without resizing images.
- Added active-node alignment buttons for image top/middle/node bottom and image left/center/right.
- Made Shift-click selection follow Blender behavior: selected inactive images become active before they can be deselected.
- Moved Match Size controls to the top of the Arrange panel section.

## 1.2.1

- Fixed add-on registration lifecycle for Blender Extensions review.

## 1.2.0

Initial public release preparation.

- Added drag and drop image creation.
- Added multi-image add from the file picker.
- Added row, column, and grid arrangement.
- Added width and height matching against the active image.
- Added image click selection with Shift/Ctrl selection support.
- Added outlines that follow Blender's node selection colors.
- Added RefBoard scaling with `S`.
- Prepared the Blender Extensions package.
