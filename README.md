# RefBoard

RefBoard is a small Blender add-on for keeping image references inside Blender, in a dedicated node editor.

It is not trying to replace PureRef or Blender's built-in reference images. The idea is simpler: when you are already working in Blender and want a quick board of images next to your materials, geometry nodes, or scene work, RefBoard gives you a clean place to drop them.

## What it does

- Adds a dedicated `RefBoard` node tree.
- Lets you drag and drop images into the node editor.
- Lets you add one or several images from the sidebar.
- Draws images behind their nodes, so the nodes stay readable and selectable.
- Supports click selection on the image itself.
- Keeps image outlines in the same spirit as Blender's node selection colors.
- Arranges selected images as a row, column, or automatic grid.
- Matches selected image width or height to the active image.
- Scales image boards with `S`, including multiple selected nodes.

## Supported image formats

RefBoard currently accepts:

- PNG
- JPG / JPEG
- TGA
- BMP
- EXR
- WEBP

## Installation

For a normal install, use the packaged zip from the `release` folder:

```text
release/refboard-1.2.0.zip
```

In Blender:

1. Open `Edit > Preferences > Add-ons`.
2. Choose `Install from Disk`.
3. Select `refboard-1.2.0.zip`.
4. Enable `RefBoard`.

The add-on is also being prepared for Blender Extensions, so the long-term goal is installation directly from Blender.

## Basic use

Open a Node Editor and switch to the `RefBoard` tree type.

You can then:

- drag images into the editor;
- use the `RefBoard` tab in the sidebar;
- select images by clicking their drawn image area;
- use `Row`, `Column`, or `Grid` to tidy up selected images;
- use `Width` or `Height` under `Match Size` to match selected images to the active one;
- use `S` to scale selected RefBoard images.

## Notes

This is still early release work. The current focus is keeping the add-on simple, predictable, and comfortable to use inside Blender.

If something feels off, please open an issue with:

- Blender version;
- operating system;
- what you clicked or dragged;
- a short screenshot or screen recording if possible.

## License

RefBoard is licensed under GPL-3.0-or-later.

