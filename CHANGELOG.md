# Changelog

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
