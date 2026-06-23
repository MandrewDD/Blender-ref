bl_info = {
    "name": "RefBoard",
    "author": "Mandrew3D <moseenkowam@gmail.com>",
    "version": (1, 4, 0),
    "blender": (4, 2, 0),
    "category": "Node",
}

import bpy
import gpu
import gpu.texture
import ctypes
import json
import math
import os
import struct
import tempfile
import zipfile
from gpu_extras.batch import batch_for_shader

_handle = None
_overlay_handle = None
_keymaps = []
_click_candidate = None
_menu_added = False
_image_shader = None
_scale_overlay = None
NODE_HEADER_HEIGHT = 120
NODE_SPACING = 50
DRAW_HANDLER_TYPE = "PRE_VIEW"
OUTLINE_WIDTH = 2.0
TRANSFORM_LINE_WIDTH = 1.0
TRANSFORM_ARROW_WIDTH = 2.0
TRANSFORM_DASH_LENGTH = 4.0
TRANSFORM_DASH_GAP = 4.0
TRANSFORM_DASH_OFFSET = (-1.0, 1.0)
TRANSFORM_ARROW_OFFSET = 5.0
TRANSFORM_ARROW_LENGTH = 10.0
TRANSFORM_ARROW_SIZE = 5.0
SCALE_EPSILON = 0.0001
CLICK_DRAG_THRESHOLD = 5
IMAGE_FILE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".exr", ".webp"}
REFBMD_EXTENSION = ".refbmd"
REFBMD_FORMAT = "refbmd"
REFBMD_FORMAT_VERSION = 1
IMAGE_SHADER_BUILTINS = (
    "IMAGE_SCENE_LINEAR_TO_REC709_SRGB",
)
IMAGE_VERTEX_SHADER = """
uniform mat4 ModelViewProjectionMatrix;

in vec2 pos;
in vec2 texCoord;

out vec2 uvInterp;

void main()
{
    uvInterp = texCoord;
    gl_Position = ModelViewProjectionMatrix * vec4(pos.xy, 0.0, 1.0);
}
"""
IMAGE_LINEAR_TO_SRGB_FRAGMENT_SHADER = """
uniform sampler2D image;

in vec2 uvInterp;

out vec4 fragColor;

vec3 linear_to_srgb(vec3 color)
{
    vec3 linear_color = max(color, vec3(0.0));
    vec3 lower = linear_color * 12.92;
    vec3 higher = 1.055 * pow(linear_color, vec3(1.0 / 2.4)) - 0.055;
    vec3 cutoff = step(linear_color, vec3(0.0031308));

    return mix(higher, lower, cutoff);
}

void main()
{
    vec4 color = texture(image, uvInterp);
    fragColor = vec4(linear_to_srgb(color.rgb), color.a);
}
"""
NUMERIC_INPUT_KEYS = {
    "ZERO": "0",
    "ONE": "1",
    "TWO": "2",
    "THREE": "3",
    "FOUR": "4",
    "FIVE": "5",
    "SIX": "6",
    "SEVEN": "7",
    "EIGHT": "8",
    "NINE": "9",
    "NUMPAD_0": "0",
    "NUMPAD_1": "1",
    "NUMPAD_2": "2",
    "NUMPAD_3": "3",
    "NUMPAD_4": "4",
    "NUMPAD_5": "5",
    "NUMPAD_6": "6",
    "NUMPAD_7": "7",
    "NUMPAD_8": "8",
    "NUMPAD_9": "9",
}


# =========================================================
# CONTEXT
# =========================================================

def is_refboard_context(context):
    space = getattr(context, "space_data", None)
    tree = getattr(space, "node_tree", None)

    return (
        space
        and space.type == "NODE_EDITOR"
        and tree
        and tree.bl_idname == "RefBoardTreeType"
    )


def align_nodes_row(nodes, active):
    if not nodes:
        return

    if active not in nodes:
        active = nodes[0]

    ordered_nodes = [active] + sorted(
        [n for n in nodes if n != active],
        key=lambda n: n.location.x
    )

    start_x = active.location.x
    y = active.location.y
    offset_x = 0.0

    for n in ordered_nodes:
        w = get_node_image_width(n)

        n.location.x = start_x + offset_x
        n.location.y = y

        offset_x += w + NODE_SPACING


def align_nodes_col(nodes, active):
    if not nodes:
        return

    if active not in nodes:
        active = nodes[0]

    ordered_nodes = [active] + sorted(
        [n for n in nodes if n != active],
        key=lambda n: n.location.y,
        reverse=True
    )

    start_y = active.location.y
    x = active.location.x
    offset_y = 0.0

    for n in ordered_nodes:
        h = get_node_image_height(n)

        if n != active:
            offset_y += h + NODE_HEADER_HEIGHT + NODE_SPACING

        n.location.x = x
        n.location.y = start_y - offset_y


def align_nodes_grid(nodes, active):
    if not nodes:
        return

    if active not in nodes:
        active = nodes[0]

    ordered_nodes = [active] + sorted(
        [n for n in nodes if n != active],
        key=lambda n: (n.location.x, -n.location.y)
    )

    cols = math.ceil(math.sqrt(len(ordered_nodes)))
    start_x = active.location.x
    start_y = active.location.y

    max_width = max(get_node_image_width(n) for n in ordered_nodes)
    max_height = max(get_node_image_height(n) for n in ordered_nodes)
    cell_width = max_width + NODE_SPACING
    cell_height = max_height + NODE_HEADER_HEIGHT + NODE_SPACING

    for index, n in enumerate(ordered_nodes):
        col = index % cols
        row = index // cols

        n.location.x = start_x + col * cell_width
        n.location.y = start_y - row * cell_height


def is_node_image_rotated_sideways(node):
    return int(getattr(node, "rotation_quarters", 0)) % 2 != 0


def get_node_image_base_width(node):
    if is_node_image_rotated_sideways(node):
        return node.image.size[1]

    return node.image.size[0]


def get_node_image_base_height(node):
    if is_node_image_rotated_sideways(node):
        return node.image.size[0]

    return node.image.size[1]


def get_node_image_width(node):
    return get_node_image_base_width(node) * node.scale


def get_node_image_height(node):
    return get_node_image_base_height(node) * node.scale


def get_node_image_uvs(node):
    uvs = [
        [0, 0],
        [1, 0],
        [1, 1],
        [0, 1],
    ]

    if getattr(node, "flip_x", False):
        for uv in uvs:
            uv[0] = 1 - uv[0]

    if getattr(node, "flip_y", False):
        for uv in uvs:
            uv[1] = 1 - uv[1]

    for _ in range(int(getattr(node, "rotation_quarters", 0)) % 4):
        for uv in uvs:
            uv[0], uv[1] = 1 - uv[1], uv[0]

    return tuple((uv[0], uv[1]) for uv in uvs)


def align_nodes_to_active(nodes, active, mode):
    if not nodes:
        return

    if active not in nodes:
        active = nodes[0]

    active_width = get_node_image_width(active)
    active_height = get_node_image_height(active)

    if mode == "H_TOP":
        target = active.location.y + active_height

        for n in nodes:
            n.location.y = target - get_node_image_height(n)

    elif mode == "H_CENTER":
        target = active.location.y + active_height * 0.5

        for n in nodes:
            n.location.y = target - get_node_image_height(n) * 0.5

    elif mode == "H_BOTTOM":
        target = active.location.y - NODE_HEADER_HEIGHT

        for n in nodes:
            n.location.y = target + NODE_HEADER_HEIGHT

    elif mode == "V_LEFT":
        target = active.location.x

        for n in nodes:
            n.location.x = target

    elif mode == "V_CENTER":
        target = active.location.x + active_width * 0.5

        for n in nodes:
            n.location.x = target - get_node_image_width(n) * 0.5

    elif mode == "V_RIGHT":
        target = active.location.x + active_width

        for n in nodes:
            n.location.x = target - get_node_image_width(n)


def tag_refboard_redraw(context):
    screen = getattr(context, "screen", None)
    area = getattr(context, "area", None)

    if screen:
        for screen_area in screen.areas:
            if screen_area.type == "NODE_EDITOR":
                screen_area.tag_redraw()
        return

    if area:
        area.tag_redraw()


def get_refboard_node_editor_context(context=None, tree=None):
    area = getattr(context, "area", None) if context else None
    space = getattr(context, "space_data", None) if context else None
    window = getattr(context, "window", None) if context else None
    screen = getattr(context, "screen", None) if context else None

    if (
        window
        and screen
        and area
        and area.type == "NODE_EDITOR"
        and space
        and getattr(space, "type", None) == "NODE_EDITOR"
        and (not tree or getattr(space, "node_tree", None) == tree)
    ):
        region = next((r for r in area.regions if r.type == "WINDOW"), None)

        if region:
            return window, screen, area, region, space

    windows = []

    if window:
        windows.append(window)

    windows.extend(
        win for win in bpy.context.window_manager.windows
        if win not in windows
    )

    for win in windows:
        win_screen = getattr(win, "screen", None)

        if not win_screen:
            continue

        for screen_area in win_screen.areas:
            if screen_area.type != "NODE_EDITOR":
                continue

            screen_space = screen_area.spaces.active

            if tree and getattr(screen_space, "node_tree", None) != tree:
                continue

            region = next((r for r in screen_area.regions if r.type == "WINDOW"), None)

            if region:
                return win, win_screen, screen_area, region, screen_space

    return None, None, None, None, None


def run_refboard_frame_selected(context=None, tree=None):
    window, screen, area, region, space = get_refboard_node_editor_context(context, tree)

    if not window or not screen or not area or not region or not space:
        return False

    try:
        with bpy.context.temp_override(
            window=window,
            screen=screen,
            area=area,
            region=region,
            space_data=space
        ):
            bpy.ops.node.view_selected()
    except Exception as exc:
        print(f"RefBoard: could not frame selected nodes: {exc}")
        return False

    area.tag_redraw()
    return True


def frame_refboard_selected(context, tree=None):
    run_refboard_frame_selected(context, tree)

    def deferred_frame():
        run_refboard_frame_selected(None, tree)
        return None

    try:
        bpy.app.timers.register(deferred_frame, first_interval=0.05)
    except Exception as exc:
        print(f"RefBoard: could not schedule frame selected: {exc}")

    tag_refboard_redraw(context)


def get_image_filepaths(operator):
    if operator.files:
        return [
            bpy.path.abspath(os.path.join(operator.directory, f.name))
            for f in operator.files
        ]

    if operator.filepath:
        return [bpy.path.abspath(operator.filepath)]

    return []


def load_image_for_operator(operator, filepath, pack_image=False, cleanup_file=False):
    try:
        image = bpy.data.images.load(filepath, check_existing=True)
    except RuntimeError as exc:
        operator.report({'WARNING'}, f"Could not load image: {filepath}")
        print(f"RefBoard: could not load image {filepath!r}: {exc}")
        return None

    if pack_image:
        try:
            image.pack()
        except RuntimeError as exc:
            operator.report({'WARNING'}, f"Could not pack image: {filepath}")
            print(f"RefBoard: could not pack image {filepath!r}: {exc}")
        else:
            image.name = "Clipboard Image"

            if cleanup_file:
                try:
                    os.remove(filepath)
                except OSError as exc:
                    print(f"RefBoard: could not remove clipboard temp file {filepath!r}: {exc}")

    return image


def is_supported_image_path(filepath):
    return os.path.splitext(filepath)[1].lower() in IMAGE_FILE_EXTENSIONS


def is_supported_refbmd_path(filepath):
    return os.path.splitext(filepath)[1].lower() == REFBMD_EXTENSION


def split_refboard_transfer_paths(paths):
    image_paths = []
    refbmd_paths = []

    for filepath in paths:
        if not os.path.isfile(filepath):
            continue

        if is_supported_image_path(filepath):
            image_paths.append(filepath)
        elif is_supported_refbmd_path(filepath):
            refbmd_paths.append(filepath)

    return image_paths, refbmd_paths


def get_clipboard_transfer_filepaths():
    if os.name != "nt":
        return [], False

    user32 = ctypes.windll.user32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.CloseClipboard.restype = ctypes.c_bool
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p

    if not user32.OpenClipboard(None):
        return [], False

    try:
        paths = get_clipboard_hdrop_filepaths()

        if paths:
            return paths, False

        return get_clipboard_dib_filepaths(), True
    finally:
        user32.CloseClipboard()


def get_clipboard_hdrop_filepaths():
    CF_HDROP = 15
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    shell32.DragQueryFileW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    ]
    shell32.DragQueryFileW.restype = ctypes.c_uint

    if not user32.IsClipboardFormatAvailable(CF_HDROP):
        return []

    handle = user32.GetClipboardData(CF_HDROP)

    if not handle:
        return []

    count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
    paths = []

    for index in range(count):
        length = shell32.DragQueryFileW(handle, index, None, 0)
        buffer = ctypes.create_unicode_buffer(length + 1)
        shell32.DragQueryFileW(handle, index, buffer, length + 1)
        filepath = bpy.path.abspath(buffer.value)

        if (
            os.path.isfile(filepath)
            and (is_supported_image_path(filepath) or is_supported_refbmd_path(filepath))
        ):
            paths.append(filepath)

    return paths


def get_clipboard_dib_filepaths():
    CF_DIB = 8
    CF_DIBV5 = 17
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t

    for clipboard_format in (CF_DIBV5, CF_DIB):
        if not user32.IsClipboardFormatAvailable(clipboard_format):
            continue

        handle = user32.GetClipboardData(clipboard_format)

        if not handle:
            continue

        size = kernel32.GlobalSize(handle)
        pointer = kernel32.GlobalLock(handle)

        if not pointer:
            continue

        try:
            dib_bytes = ctypes.string_at(pointer, size)
        finally:
            kernel32.GlobalUnlock(handle)

        filepath = save_dib_to_temp_bmp(dib_bytes)

        if filepath:
            return [filepath]

    return []


def save_dib_to_temp_bmp(dib_bytes):
    if len(dib_bytes) < 4:
        return None

    header_size = struct.unpack_from("<I", dib_bytes, 0)[0]

    if header_size < 12 or header_size > len(dib_bytes):
        return None

    color_table_size = 0

    if header_size == 12 and len(dib_bytes) >= 10:
        bit_count = struct.unpack_from("<H", dib_bytes, 10)[0]

        if bit_count <= 8:
            color_table_size = (1 << bit_count) * 3
    elif header_size >= 40 and len(dib_bytes) >= 36:
        bit_count = struct.unpack_from("<H", dib_bytes, 14)[0]
        compression = struct.unpack_from("<I", dib_bytes, 16)[0]
        colors_used = struct.unpack_from("<I", dib_bytes, 32)[0]

        if colors_used:
            color_table_size = colors_used * 4
        elif bit_count <= 8:
            color_table_size = (1 << bit_count) * 4
        elif compression == 3 and header_size == 40:
            color_table_size = 12

    pixel_offset = 14 + header_size + color_table_size
    file_size = 14 + len(dib_bytes)
    bmp_header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, pixel_offset)
    directory = os.path.join(bpy.app.tempdir or tempfile.gettempdir(), "refboard_clipboard")
    os.makedirs(directory, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".bmp",
        prefix="clipboard_",
        dir=directory,
        delete=False
    ) as temp_file:
        temp_file.write(bmp_header)
        temp_file.write(dib_bytes)
        return temp_file.name


def add_image_nodes_from_paths(
    operator,
    context,
    paths,
    location,
    align_multiple=True,
    pack_images=False,
    cleanup_files=False
):
    tree = context.space_data.node_tree

    for node in tree.nodes:
        node.select = False

    created_nodes = []

    for filepath in paths:
        img = load_image_for_operator(
            operator,
            filepath,
            pack_image=pack_images,
            cleanup_file=cleanup_files
        )

        if not img:
            continue

        node = tree.nodes.new("RefBoardImageNodeType")
        node.image = img
        node.location = location

        node.select = True
        created_nodes.append(node)

    if not created_nodes:
        return []

    tree.nodes.active = created_nodes[0]

    if align_multiple and len(created_nodes) > 1:
        align_nodes_row(created_nodes, created_nodes[0])

    tag_refboard_redraw(context)
    frame_refboard_selected(context, tree)

    return created_nodes


def sanitize_refbmd_filename(name):
    safe_name = "".join(
        c if c not in '<>:"/\\|?*' and ord(c) >= 32 else "_"
        for c in name.strip()
    ).strip(" .")

    return safe_name or "RefBoard"


def ensure_refbmd_extension(filepath):
    root, ext = os.path.splitext(filepath)

    if ext.lower() == REFBMD_EXTENSION:
        return filepath

    return root + REFBMD_EXTENSION if ext else filepath + REFBMD_EXTENSION


def get_desktop_directory():
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")

    if os.path.isdir(desktop):
        return desktop

    return os.path.expanduser("~")


def get_refbmd_default_directory():
    blend_filepath = bpy.data.filepath

    if blend_filepath:
        directory = os.path.dirname(bpy.path.abspath(blend_filepath))

        if directory:
            return directory

    return get_desktop_directory()


def get_refbmd_default_export_path(tree):
    filename = sanitize_refbmd_filename(tree.name) + REFBMD_EXTENSION

    return os.path.join(get_refbmd_default_directory(), filename)


def get_unique_refboard_name(base_name):
    clean_name = base_name.strip() or "RefBoard"
    existing_names = set(bpy.data.node_groups.keys())

    if clean_name not in existing_names:
        return clean_name

    index = 1

    while True:
        candidate = f"{clean_name} {index:03d}"

        if candidate not in existing_names:
            return candidate

        index += 1


def get_image_export_extension(image):
    filepath = bpy.path.abspath(image.filepath) if image.filepath else ""
    ext = os.path.splitext(filepath)[1].lower()

    if ext in IMAGE_FILE_EXTENSIONS:
        return ext

    return ".png"


def write_image_to_refbmd(zip_file, image, archive_path, temp_dir):
    packed_file = getattr(image, "packed_file", None)
    filepath = bpy.path.abspath(image.filepath) if image.filepath else ""

    if packed_file:
        packed_data = getattr(packed_file, "data", None)

        if packed_data:
            zip_file.writestr(archive_path, bytes(packed_data))
            return

    if filepath and os.path.isfile(filepath):
        zip_file.write(filepath, archive_path)
        return

    temp_path = os.path.join(temp_dir, os.path.basename(archive_path))

    try:
        image.save_render(temp_path, scene=bpy.context.scene)
    except Exception:
        image.save_render(temp_path)

    zip_file.write(temp_path, archive_path)


def coerce_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in {"1", "true", "yes", "on"}:
            return True

        if normalized in {"0", "false", "no", "off"}:
            return False

    return default


def coerce_location(value):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return (0.0, 0.0)

    return (coerce_float(value[0], 0.0), coerce_float(value[1], 0.0))


def safe_refbmd_member_path(path):
    if not isinstance(path, str):
        return None

    normalized = path.replace("\\", "/").lstrip("/")

    if (
        not normalized
        or normalized.startswith("../")
        or "/../" in normalized
        or normalized == ".."
    ):
        return None

    return normalized


def import_refbmd_file(operator, context, filepath):
    board_base_name = os.path.splitext(os.path.basename(filepath))[0]
    board_name = get_unique_refboard_name(board_base_name)
    imported_count = 0
    tree = None

    try:
        with tempfile.TemporaryDirectory(prefix="refbmd_import_") as temp_dir:
            with zipfile.ZipFile(filepath, "r") as zip_file:
                manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))

                if not isinstance(manifest, dict):
                    manifest = {}

                node_entries = manifest.get("nodes", [])

                if not isinstance(node_entries, list):
                    node_entries = []

                tree = bpy.data.node_groups.new(board_name, "RefBoardTreeType")

                for index, node_data in enumerate(node_entries):
                    if not isinstance(node_data, dict):
                        continue

                    archive_path = safe_refbmd_member_path(node_data.get("image"))

                    if not archive_path or archive_path not in zip_file.namelist():
                        continue

                    image_ext = os.path.splitext(archive_path)[1].lower()

                    if image_ext not in IMAGE_FILE_EXTENSIONS:
                        image_ext = ".png"

                    temp_image_path = os.path.join(temp_dir, f"image_{index:04d}{image_ext}")

                    with open(temp_image_path, "wb") as temp_image_file:
                        temp_image_file.write(zip_file.read(archive_path))

                    image = load_image_for_operator(operator, temp_image_path)

                    if not image:
                        continue

                    try:
                        image.pack()
                    except RuntimeError as exc:
                        print(f"RefBoard: could not pack imported image {archive_path!r}: {exc}")

                    node = tree.nodes.new("RefBoardImageNodeType")
                    node.image = image
                    location = coerce_location(node_data.get("location"))
                    node.location.x = location[0]
                    node.location.y = location[1]
                    node.scale = max(coerce_float(node_data.get("scale"), 1.0), SCALE_EPSILON)
                    node.z_order = int(coerce_float(node_data.get("z_order"), index))
                    node.rotation_quarters = int(coerce_float(node_data.get("rotation_quarters"), 0)) % 4
                    node.flip_x = coerce_bool(node_data.get("flip_x"), False)
                    node.flip_y = coerce_bool(node_data.get("flip_y"), False)
                    node.select = True

                    if imported_count == 0:
                        tree.nodes.active = node

                    imported_count += 1
    except Exception:
        if tree:
            bpy.data.node_groups.remove(tree)

        raise

    if imported_count == 0:
        if tree:
            bpy.data.node_groups.remove(tree)

        return None, 0

    return tree, imported_count


def set_context_refboard_tree(context, tree):
    space = getattr(context, "space_data", None)

    if space and space.type == "NODE_EDITOR":
        try:
            space.node_tree = tree
            return
        except Exception:
            pass

    window = getattr(context, "window", None)
    windows = []

    if window:
        windows.append(window)

    windows.extend(
        win for win in bpy.context.window_manager.windows
        if win not in windows
    )

    for win in windows:
        screen = getattr(win, "screen", None)

        if not screen:
            continue

        for area in screen.areas:
            if area.type != "NODE_EDITOR":
                continue

            try:
                area.spaces.active.node_tree = tree
                return
            except Exception:
                pass


def import_refbmd_files(operator, context, paths):
    imported_boards = 0
    imported_images = 0
    last_tree = None

    for filepath in paths:
        try:
            tree, image_count = import_refbmd_file(operator, context, filepath)
        except Exception as exc:
            operator.report({'WARNING'}, f"Could not import {os.path.basename(filepath)}: {exc}")
            continue

        if not tree:
            operator.report({'WARNING'}, f"No images in {os.path.basename(filepath)}")
            continue

        imported_boards += 1
        imported_images += image_count
        last_tree = tree

    if last_tree:
        set_context_refboard_tree(context, last_tree)
        tag_refboard_redraw(context)
        frame_refboard_selected(context, last_tree)

    return imported_boards, imported_images


def update_node_draw(self, context):
    tag_refboard_redraw(context)


def get_refboard_view_scale():
    prefs = bpy.context.preferences
    dpi_fac = prefs.system.dpi / 72.0
    return dpi_fac


def view_to_refboard_location(location):
    scale = get_refboard_view_scale()

    return (location[0] / scale, location[1] / scale)


def refboard_to_view_location(x, y):
    scale = get_refboard_view_scale()

    return (x * scale, y * scale)


def get_add_image_location(context, event):
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)

    if not area:
        return (0.0, 0.0)

    window_region = None

    for area_region in area.regions:
        if area_region.type == "WINDOW":
            window_region = area_region
            break

    if not window_region or not getattr(window_region, "view2d", None):
        return (0.0, 0.0)

    if region == window_region:
        mouse_x = event.mouse_region_x
        mouse_y = event.mouse_region_y
    else:
        mouse_x = event.mouse_x - window_region.x
        mouse_y = event.mouse_y - window_region.y

        if (
            mouse_x < 0
            or mouse_y < 0
            or mouse_x > window_region.width
            or mouse_y > window_region.height
        ):
            mouse_x = window_region.width * 0.5
            mouse_y = window_region.height * 0.5

    loc = window_region.view2d.region_to_view(mouse_x, mouse_y)

    return view_to_refboard_location(loc)


def get_event_view_location(context, event):
    area = getattr(context, "area", None)

    if not area:
        return None

    window_region = None

    for area_region in area.regions:
        if area_region.type == "WINDOW":
            window_region = area_region
            break

    if not window_region or not getattr(window_region, "view2d", None):
        return None

    mouse_x = event.mouse_x - window_region.x
    mouse_y = event.mouse_y - window_region.y

    if (
        mouse_x < 0
        or mouse_y < 0
        or mouse_x > window_region.width
        or mouse_y > window_region.height
    ):
        return None

    loc = window_region.view2d.region_to_view(mouse_x, mouse_y)

    return view_to_refboard_location(loc)


def get_view_center_location(context):
    area = getattr(context, "area", None)

    if not area:
        return (0.0, 0.0)

    window_region = None

    for area_region in area.regions:
        if area_region.type == "WINDOW":
            window_region = area_region
            break

    if not window_region or not getattr(window_region, "view2d", None):
        return (0.0, 0.0)

    loc = window_region.view2d.region_to_view(
        window_region.width * 0.5,
        window_region.height * 0.5
    )

    return view_to_refboard_location(loc)


def find_image_node_at_location(tree, location):
    x, y = location

    nodes = sorted(
        [n for n in tree.nodes if n.bl_idname == "RefBoardImageNodeType" and n.image],
        key=lambda n: n.z_order,
        reverse=True
    )

    for node in nodes:
        image_width = get_node_image_width(node)
        image_height = get_node_image_height(node)

        if (
            node.location.x <= x <= node.location.x + image_width
            and node.location.y <= y <= node.location.y + image_height
        ):
            return node

    return None


def color_from_theme(owner, names, fallback):
    for name in names:
        value = getattr(owner, name, None)

        if value is not None:
            color = tuple(value)

            if len(color) == 3:
                return (color[0], color[1], color[2], 1.0)

            return color

    return fallback


def get_refboard_outline_colors():
    theme = bpy.context.preferences.themes[0].node_editor

    return {
        "normal": color_from_theme(
            theme,
            ("node_outline", "wire", "grid"),
            (0.45, 0.45, 0.45, 1.0)
        ),
        "selected": color_from_theme(
            theme,
            ("node_selected", "wire_select", "selected_text"),
            (1.0, 0.62, 0.18, 1.0)
        ),
        "active": color_from_theme(
            theme,
            ("node_active", "active_node", "node_selected"),
            (1.0, 0.86, 0.25, 1.0)
        ),
    }


def get_node_outline_color(node, active_node, colors):
    if node == active_node and node.select:
        return colors["active"]

    if node.select:
        return colors["selected"]

    return colors["normal"]


def get_theme_rgb(owner, name, fallback, alpha=1.0):
    value = getattr(owner, name, None)

    if value is None:
        return fallback

    color = tuple(value)

    if len(color) < 3:
        return fallback

    return (color[0], color[1], color[2], alpha)


def get_transform_line_colors():
    theme = bpy.context.preferences.themes[0]
    editor_theme = getattr(theme, "node_editor", None)

    if not editor_theme:
        return (0.0, 0.0, 0.0, 1.0), None

    if bpy.app.version >= (5, 0, 0):
        fg = get_theme_rgb(editor_theme, "text_hi", (1.0, 1.0, 1.0, 1.0), 1.0)
        bg = get_theme_rgb(editor_theme, "back", (0.0, 0.0, 0.0, 0.5), 0.5)
        return fg, bg

    return get_theme_rgb(editor_theme, "view_overlay", (0.0, 0.0, 0.0, 1.0), 1.0), None


def make_dashed_line(start, end, dash_length, dash_gap):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)

    if length <= 0.0:
        return []

    coords = []
    distance = 0.0

    while distance < length:
        segment_end = min(distance + dash_length, length)
        start_factor = distance / length
        end_factor = segment_end / length
        dash_start = (
            start[0] + dx * start_factor,
            start[1] + dy * start_factor
        )
        dash_end = (
            start[0] + dx * end_factor,
            start[1] + dy * end_factor
        )
        coords.extend((dash_start, dash_end))
        distance += dash_length + dash_gap

    return coords


def make_transform_arrow(center, angle, direction):
    offset = TRANSFORM_ARROW_OFFSET * direction
    length = TRANSFORM_ARROW_LENGTH * direction
    size = TRANSFORM_ARROW_SIZE * direction
    axis = (math.cos(angle), math.sin(angle))
    perp = (-axis[1], axis[0])

    base = (
        center[0] + axis[0] * offset,
        center[1] + axis[1] * offset
    )
    tip = (
        center[0] + axis[0] * (offset + length),
        center[1] + axis[1] * (offset + length)
    )
    wing_center = (
        center[0] + axis[0] * (offset + length - size),
        center[1] + axis[1] * (offset + length - size)
    )
    wing_a = (
        wing_center[0] + perp[0] * abs(size),
        wing_center[1] + perp[1] * abs(size)
    )
    wing_b = (
        wing_center[0] - perp[0] * abs(size),
        wing_center[1] - perp[1] * abs(size)
    )

    return (base, tip, tip, wing_a, tip, wing_b)


def offset_coords(coords, offset):
    return [(x + offset[0], y + offset[1]) for x, y in coords]


def draw_line_coords(coords, width, color):
    if not coords:
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": coords})

    gpu.state.line_width_set(width)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def get_image_shader():
    global _image_shader

    if _image_shader:
        return _image_shader

    for shader_name in IMAGE_SHADER_BUILTINS:
        try:
            _image_shader = gpu.shader.from_builtin(shader_name)
            return _image_shader
        except ValueError:
            continue

    try:
        _image_shader = gpu.types.GPUShader(
            IMAGE_VERTEX_SHADER,
            IMAGE_LINEAR_TO_SRGB_FRAGMENT_SHADER
        )
    except Exception:
        _image_shader = gpu.shader.from_builtin("IMAGE")

    return _image_shader


def draw_scale_overlay():
    if not _scale_overlay:
        return

    region = bpy.context.region

    if not region or not getattr(region, "view2d", None):
        return

    pivot = _scale_overlay.get("pivot")
    current = _scale_overlay.get("current")

    if not pivot or not current:
        return

    start_view = refboard_to_view_location(pivot[0], pivot[1])
    end_view = refboard_to_view_location(current[0], current[1])
    start_region = region.view2d.view_to_region(start_view[0], start_view[1], clip=False)
    end_region = region.view2d.view_to_region(end_view[0], end_view[1], clip=False)
    line_coords = make_dashed_line(
        start_region,
        end_region,
        TRANSFORM_DASH_LENGTH,
        TRANSFORM_DASH_GAP
    )
    fg_color, bg_color = get_transform_line_colors()

    if bg_color:
        draw_line_coords(line_coords, TRANSFORM_LINE_WIDTH, bg_color)
        draw_line_coords(
            offset_coords(line_coords, TRANSFORM_DASH_OFFSET),
            TRANSFORM_LINE_WIDTH,
            fg_color
        )
    else:
        draw_line_coords(line_coords, TRANSFORM_LINE_WIDTH, fg_color)

    dx = end_region[0] - start_region[0]
    dy = end_region[1] - start_region[1]

    if dx == 0.0 and dy == 0.0:
        return

    angle = math.atan2(dy, dx)
    arrow_coords = []
    arrow_coords.extend(make_transform_arrow(end_region, angle, 1.0))
    arrow_coords.extend(make_transform_arrow(end_region, angle, -1.0))

    if bg_color:
        draw_line_coords(arrow_coords, TRANSFORM_ARROW_WIDTH * 2.0, bg_color)

    draw_line_coords(arrow_coords, TRANSFORM_ARROW_WIDTH, fg_color)


def draw_scale_overlay_callback():
    space = bpy.context.space_data

    if (
        not space
        or space.type != "NODE_EDITOR"
        or not space.node_tree
        or space.node_tree.bl_idname != "RefBoardTreeType"
    ):
        return

    gpu.state.blend_set('ALPHA')

    try:
        draw_scale_overlay()
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')


def get_selection_center(nodes):
    total_x = sum(n.location.x for n in nodes)
    total_y = sum(n.location.y for n in nodes)
    count = len(nodes)

    return (total_x / count, total_y / count)


def get_scale_pivot(nodes):
    if len(nodes) == 1:
        node = nodes[0]
        node_width = getattr(node, "width", 0.0)
        node_height = getattr(node, "height", NODE_HEADER_HEIGHT)

        return (
            node.location.x + node_width * 0.5,
            node.location.y - node_height * 0.5
        )

    return get_selection_center(nodes)


def get_scale_factor_from_mouse(pivot, start_location, current_location):
    start_distance = math.hypot(
        start_location[0] - pivot[0],
        start_location[1] - pivot[1]
    )
    current_distance = math.hypot(
        current_location[0] - pivot[0],
        current_location[1] - pivot[1]
    )

    if start_distance <= SCALE_EPSILON:
        return 1.0

    return max(current_distance / start_distance, SCALE_EPSILON)


def get_axis_scale_factor_from_mouse(pivot, start_location, current_location, axis):
    if axis == "X":
        axis_index = 0
    elif axis == "Y":
        axis_index = 1
    else:
        return get_scale_factor_from_mouse(pivot, start_location, current_location)

    start_distance = abs(start_location[axis_index] - pivot[axis_index])
    current_distance = abs(current_location[axis_index] - pivot[axis_index])

    if start_distance <= SCALE_EPSILON:
        return 1.0

    return max(current_distance / start_distance, SCALE_EPSILON)


def parse_scale_numeric_input(text):
    if text in {"", "-", ".", "-."}:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def get_numeric_input_text(event):
    if event.type in NUMERIC_INPUT_KEYS:
        return NUMERIC_INPUT_KEYS[event.type]

    if event.type in {"PERIOD", "NUMPAD_PERIOD", "COMMA"}:
        return "."

    if event.type in {"MINUS", "NUMPAD_MINUS"}:
        return "-"

    return None


# =========================================================
# NODE TREE
# =========================================================

class RefBoardTree(bpy.types.NodeTree):
    bl_idname = "RefBoardTreeType"
    bl_label = "RefBoard"
    bl_icon = "IMAGE"

    @classmethod
    def poll(cls, context):
        return True


# =========================================================
# Z ORDER
# =========================================================

class RB_OT_z_adjust(bpy.types.Operator):
    bl_idname = "refboard.z_adjust"
    bl_label = "Z Adjust"
    bl_description = "Move this image behind or in front of the other RefBoard images"

    node_name: bpy.props.StringProperty()
    direction: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    @classmethod
    def description(cls, context, properties):
        if properties.direction == "BACK":
            return "Send this image behind the other RefBoard images"
        if properties.direction == "FRONT":
            return "Bring this image in front of the other RefBoard images"
        return cls.bl_description

    def execute(self, context):

        tree = context.space_data.node_tree
        node = tree.nodes.get(self.node_name)

        if not node:
            return {'CANCELLED'}

        nodes = [n for n in tree.nodes if n.bl_idname == "RefBoardImageNodeType" and n.image]
        others = [n for n in nodes if n != node]

        if not others:
            node.z_order = 0
            tag_refboard_redraw(context)
            return {'FINISHED'}

        if self.direction == "BACK":
            node.z_order = min(n.z_order for n in others) - 1

        elif self.direction == "FRONT":
            node.z_order = max(n.z_order for n in others) + 1

        tag_refboard_redraw(context)

        return {'FINISHED'}


# =========================================================
# IMAGE TRANSFORM
# =========================================================

class RB_OT_image_transform(bpy.types.Operator):
    bl_idname = "refboard.image_transform"
    bl_label = "Image Transform"
    bl_description = "Rotate or mirror a RefBoard image"

    node_name: bpy.props.StringProperty()
    mode: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    @classmethod
    def description(cls, context, properties):
        descriptions = {
            "ROTATE_CW": "Rotate this image clockwise",
            "ROTATE_CCW": "Rotate this image counter-clockwise",
            "FLIP_X": "Mirror this image horizontally",
            "FLIP_Y": "Mirror this image vertically",
        }

        return descriptions.get(properties.mode, cls.bl_description)

    def execute(self, context):
        tree = context.space_data.node_tree
        node = tree.nodes.get(self.node_name)

        if (
            not node
            or node.bl_idname != "RefBoardImageNodeType"
            or not node.image
        ):
            return {'CANCELLED'}

        if self.mode == "ROTATE_CW":
            node.rotation_quarters = (node.rotation_quarters + 1) % 4
        elif self.mode == "ROTATE_CCW":
            node.rotation_quarters = (node.rotation_quarters - 1) % 4
        elif self.mode == "FLIP_X":
            node.flip_x = not node.flip_x
        elif self.mode == "FLIP_Y":
            node.flip_y = not node.flip_y
        else:
            return {'CANCELLED'}

        tag_refboard_redraw(context)

        return {'FINISHED'}


# =========================================================
# ALIGN OPERATOR (NEW)
# =========================================================

class RB_OT_align_nodes(bpy.types.Operator):
    bl_idname = "refboard.align_nodes"
    bl_label = "Align Nodes"
    bl_description = "Arrange the selected image nodes using the active node as the starting point"

    mode: bpy.props.StringProperty()  # ROW / COL / GRID

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    @classmethod
    def description(cls, context, properties):
        if properties.mode == "ROW":
            return "Arrange selected images in one horizontal row, starting from the active node"
        if properties.mode == "COL":
            return "Arrange selected images in one vertical column, starting from the active node"
        if properties.mode == "GRID":
            return "Arrange selected images into an automatic grid, starting from the active node"
        return cls.bl_description

    def execute(self, context):

        space = context.space_data
        tree = space.node_tree
        active = tree.nodes.active

        nodes = [
            n for n in tree.nodes
            if n.bl_idname == "RefBoardImageNodeType"
            and n.image
            and n.select
        ]

        if not nodes:
            return {'CANCELLED'}

        if active not in nodes:
            active = nodes[0]

        if self.mode == "ROW":
            align_nodes_row(nodes, active)

        elif self.mode == "COL":
            align_nodes_col(nodes, active)

        elif self.mode == "GRID":
            align_nodes_grid(nodes, active)

        tag_refboard_redraw(context)

        return {'FINISHED'}


# =========================================================
# ALIGN TO ACTIVE
# =========================================================

class RB_OT_align_to_active(bpy.types.Operator):
    bl_idname = "refboard.align_to_active"
    bl_label = "Align"
    bl_description = "Align selected RefBoard image nodes to the active image node"

    mode: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    @classmethod
    def description(cls, context, properties):
        descriptions = {
            "H_TOP": "Align selected images by the active image top edge",
            "H_CENTER": "Align selected images by the active image vertical center",
            "H_BOTTOM": "Align selected nodes by the active node bottom edge",
            "V_LEFT": "Align selected images by the active image left edge",
            "V_CENTER": "Align selected images by the active image horizontal center",
            "V_RIGHT": "Align selected images by the active image right edge",
        }

        return descriptions.get(properties.mode, cls.bl_description)

    def execute(self, context):

        tree = context.space_data.node_tree
        active = tree.nodes.active
        nodes = [
            n for n in tree.nodes
            if n.bl_idname == "RefBoardImageNodeType"
            and n.image
            and n.select
        ]

        if not nodes:
            return {'CANCELLED'}

        align_nodes_to_active(nodes, active, self.mode)
        tag_refboard_redraw(context)

        return {'FINISHED'}


# =========================================================
# MATCH SIZE
# =========================================================

class RB_OT_match_size(bpy.types.Operator):
    bl_idname = "refboard.match_size"
    bl_label = "Match Size"
    bl_description = "Resize selected images to match the active image node"

    mode: bpy.props.StringProperty()  # WIDTH / HEIGHT

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    @classmethod
    def description(cls, context, properties):
        if properties.mode == "WIDTH":
            return "Scale selected images so their width matches the active image"
        if properties.mode == "HEIGHT":
            return "Scale selected images so their height matches the active image"
        return cls.bl_description

    def execute(self, context):

        tree = context.space_data.node_tree
        active = tree.nodes.active

        if (
            not active
            or active.bl_idname != "RefBoardImageNodeType"
            or not active.image
        ):
            return {'CANCELLED'}

        nodes = [
            n for n in tree.nodes
            if n.bl_idname == "RefBoardImageNodeType"
            and n.image
            and n.select
            and n != active
        ]

        if not nodes:
            return {'CANCELLED'}

        if self.mode == "WIDTH":
            target_width = get_node_image_width(active)

            for n in nodes:
                image_width = get_node_image_base_width(n)

                if image_width > 0:
                    n.scale = target_width / image_width

        elif self.mode == "HEIGHT":
            target_height = get_node_image_height(active)

            for n in nodes:
                image_height = get_node_image_base_height(n)

                if image_height > 0:
                    n.scale = target_height / image_height

        tag_refboard_redraw(context)

        return {'FINISHED'}


# =========================================================
# SELECT IMAGE
# =========================================================

class RB_OT_select_image(bpy.types.Operator):
    bl_idname = "refboard.select_image"
    bl_label = "Select Image"
    bl_description = "Select the RefBoard node whose image is under the cursor"
    bl_options = {'INTERNAL'}

    _node_name = ""
    _shift = False
    _ctrl = False

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def select_node(self, context):
        tree = context.space_data.node_tree
        node = tree.nodes.get(self._node_name)

        if not node:
            return {'CANCELLED'}

        if self._shift:
            if node.select and tree.nodes.active != node:
                tree.nodes.active = node
            elif node.select:
                node.select = False

                if tree.nodes.active == node:
                    tree.nodes.active = next((n for n in tree.nodes if n.select), None)
            else:
                node.select = True
                tree.nodes.active = node

        elif self._ctrl:
            node.select = not node.select

            if not node.select and tree.nodes.active == node:
                tree.nodes.active = next((n for n in tree.nodes if n.select), None)
        else:
            for tree_node in tree.nodes:
                tree_node.select = False

            node.select = True

        if node.select:
            tree.nodes.active = node

        tag_refboard_redraw(context)

        return {'FINISHED'}

    def invoke(self, context, event):

        global _click_candidate

        location = get_event_view_location(context, event)

        if not location:
            return {'PASS_THROUGH'}

        tree = context.space_data.node_tree
        node = find_image_node_at_location(tree, location)

        if event.value == "PRESS":
            if not node:
                _click_candidate = None
                return {'PASS_THROUGH'}

            _click_candidate = {
                "node_name": node.name,
                "mouse": (event.mouse_x, event.mouse_y),
                "shift": event.shift,
                "ctrl": event.ctrl,
            }

            return {'PASS_THROUGH'}

        if event.value == "RELEASE":
            if not _click_candidate:
                return {'PASS_THROUGH'}

            dx = event.mouse_x - _click_candidate["mouse"][0]
            dy = event.mouse_y - _click_candidate["mouse"][1]

            if math.hypot(dx, dy) > CLICK_DRAG_THRESHOLD:
                _click_candidate = None
                return {'PASS_THROUGH'}

            if not node or node.name != _click_candidate["node_name"]:
                _click_candidate = None
                return {'PASS_THROUGH'}

            self._node_name = _click_candidate["node_name"]
            self._shift = _click_candidate["shift"]
            self._ctrl = _click_candidate["ctrl"]
            _click_candidate = None

            return self.select_node(context)

        return {'PASS_THROUGH'}


# =========================================================
# SCALE TRANSFORM
# =========================================================

class RB_OT_scale_with_images(bpy.types.Operator):
    bl_idname = "refboard.scale_with_images"
    bl_label = "Scale Images"
    bl_description = "Scale selected RefBoard images and spread selected nodes from their center"
    bl_options = {'INTERNAL'}

    _node_names = None
    _initial_locations = None
    _initial_scales = None
    _pivot = None
    _start_mouse_location = None
    _current_mouse_location = None
    _axis = None
    _numeric_input = ""
    _numeric_factor = None

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def get_nodes(self, context):
        tree = context.space_data.node_tree

        return [
            tree.nodes[name]
            for name in self._node_names
            if name in tree.nodes
            and tree.nodes[name].bl_idname == "RefBoardImageNodeType"
            and tree.nodes[name].image
        ]

    def get_current_factor(self):
        if self._numeric_input:
            if self._numeric_factor is not None:
                return self._numeric_factor

            return 1.0

        if not self._current_mouse_location:
            return 1.0

        return get_axis_scale_factor_from_mouse(
            self._pivot,
            self._start_mouse_location,
            self._current_mouse_location,
            self._axis
        )

    def update_header(self, context):
        if not context.area:
            return

        axis_text = self._axis if self._axis else "free"

        if self._numeric_input:
            value_text = self._numeric_input
        else:
            value_text = f"{self.get_current_factor():.4g}"

        context.area.header_text_set(
            f"Scale Images: {value_text}  Axis: {axis_text}  "
            "Confirm: Enter/Space/LMB, Cancel: Esc/RMB"
        )

    def clear_header(self, context):
        if context.area:
            context.area.header_text_set(None)

    def update_overlay(self, context):
        global _scale_overlay

        _scale_overlay = {
            "pivot": self._pivot,
            "current": self._current_mouse_location,
        }
        tag_refboard_redraw(context)

    def clear_overlay(self, context):
        global _scale_overlay

        _scale_overlay = None
        tag_refboard_redraw(context)

    def set_cursor(self, context):
        for cursor in ("NONE", "CROSSHAIR"):
            try:
                context.window.cursor_modal_set(cursor)
                return
            except Exception:
                continue

    def restore_cursor(self, context):
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass

    def clear_transform_ui(self, context):
        self.clear_header(context)
        self.restore_cursor(context)
        self.clear_overlay(context)

    def refresh_transform(self, context):
        self.apply_scale(context, self.get_current_factor(), self._axis)
        self.update_overlay(context)
        self.update_header(context)

    def apply_scale(self, context, factor, axis=None):
        nodes = self.get_nodes(context)

        for node in nodes:
            initial_location = self._initial_locations[node.name]

            if len(nodes) > 1:
                if axis in {None, "X"}:
                    node.location.x = self._pivot[0] + (initial_location[0] - self._pivot[0]) * factor
                else:
                    node.location.x = initial_location[0]

                if axis in {None, "Y"}:
                    node.location.y = self._pivot[1] + (initial_location[1] - self._pivot[1]) * factor
                else:
                    node.location.y = initial_location[1]

            if axis is None:
                node.scale = self._initial_scales[node.name] * factor
            else:
                node.scale = self._initial_scales[node.name]

        tag_refboard_redraw(context)

    def set_axis(self, context, axis):
        if self._axis == axis:
            self._axis = None
        else:
            self._axis = axis

        self.set_cursor(context)
        self.refresh_transform(context)

    def append_numeric_input(self, context, text):
        if text == "-":
            if self._numeric_input.startswith("-"):
                self._numeric_input = self._numeric_input[1:]
            else:
                self._numeric_input = "-" + self._numeric_input
        elif text == ".":
            if "." not in self._numeric_input:
                if self._numeric_input in {"", "-"}:
                    self._numeric_input += "0"

                self._numeric_input += "."
        else:
            self._numeric_input += text

        self._numeric_factor = parse_scale_numeric_input(self._numeric_input)
        self.refresh_transform(context)

    def remove_numeric_input(self, context):
        if not self._numeric_input:
            return

        self._numeric_input = self._numeric_input[:-1]
        self._numeric_factor = parse_scale_numeric_input(self._numeric_input)
        self.refresh_transform(context)

    def restore_transform(self, context):
        for node in self.get_nodes(context):
            initial_location = self._initial_locations[node.name]
            node.location.x = initial_location[0]
            node.location.y = initial_location[1]
            node.scale = self._initial_scales[node.name]

        tag_refboard_redraw(context)

    def invoke(self, context, event):

        tree = context.space_data.node_tree
        nodes = [
            n for n in tree.nodes
            if n.bl_idname == "RefBoardImageNodeType"
            and n.image
            and n.select
        ]

        if not nodes:
            return {'PASS_THROUGH'}

        self._node_names = [n.name for n in nodes]
        self._initial_locations = {
            n.name: (n.location.x, n.location.y)
            for n in nodes
        }
        self._initial_scales = {
            n.name: n.scale
            for n in nodes
        }
        self._pivot = get_scale_pivot(nodes)
        self._start_mouse_location = get_event_view_location(context, event)
        self._current_mouse_location = self._start_mouse_location
        self._axis = None
        self._numeric_input = ""
        self._numeric_factor = None

        if not self._start_mouse_location:
            return {'CANCELLED'}

        context.window_manager.modal_handler_add(self)
        self.set_cursor(context)
        self.update_overlay(context)
        self.update_header(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):

        if not is_refboard_context(context):
            self.clear_transform_ui(context)
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            current_location = get_event_view_location(context, event)

            if current_location:
                self._current_mouse_location = current_location

                if self._numeric_factor is None:
                    self.refresh_transform(context)

        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            self.restore_transform(context)
            self.clear_transform_ui(context)
            return {'CANCELLED'}

        elif event.value == "PRESS" and event.type in {"X", "Y"}:
            self.set_axis(context, event.type)

        elif event.value == "PRESS" and event.type == "BACK_SPACE":
            self.remove_numeric_input(context)

        elif event.value == "PRESS":
            text = get_numeric_input_text(event)

            if text:
                self.append_numeric_input(context, text)

        elif (
            event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'SPACE'}
            and event.value == 'RELEASE'
        ):
            self.clear_transform_ui(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}


# =========================================================
# NODE
# =========================================================

class RefBoardImageNode(bpy.types.Node):
    bl_idname = "RefBoardImageNodeType"
    bl_label = "Image"

    image: bpy.props.PointerProperty(
        type=bpy.types.Image,
        description="Image displayed by this RefBoard node",
        update=update_node_draw
    )
    scale: bpy.props.FloatProperty(
        default=1.0,
        min=0.01,
        max=100.0,
        description="Display scale for this image",
        update=update_node_draw
    )
    z_order: bpy.props.IntProperty(
        default=0,
        description="Draw order for this image; higher values are drawn in front",
        update=update_node_draw
    )
    rotation_quarters: bpy.props.IntProperty(
        default=0,
        min=0,
        max=3,
        description="Image rotation in 90 degree clockwise steps",
        update=update_node_draw
    )
    flip_x: bpy.props.BoolProperty(
        default=False,
        description="Mirror this image horizontally",
        update=update_node_draw
    )
    flip_y: bpy.props.BoolProperty(
        default=False,
        description="Mirror this image vertically",
        update=update_node_draw
    )
    show_image_transform: bpy.props.BoolProperty(
        default=False,
        description="Show image transform controls"
    )

    def draw_buttons(self, context, layout):
        layout.template_ID(self, "image", open="image.open")
        layout.prop(self, "scale")

        row = layout.row(align=True)

        op = row.operator("refboard.z_adjust", text="", icon="TRIA_LEFT")
        op.node_name = self.name
        op.direction = "BACK"

        row.prop(self, "z_order", text="Z")

        op = row.operator("refboard.z_adjust", text="", icon="TRIA_RIGHT")
        op.node_name = self.name
        op.direction = "FRONT"

        box = layout.box()
        header = box.row(align=True)
        header.prop(
            self,
            "show_image_transform",
            text="Image Transform",
            icon="TRIA_DOWN" if self.show_image_transform else "TRIA_RIGHT",
            emboss=False
        )

        if self.show_image_transform:
            row = box.row(align=True)

            op = row.operator("refboard.image_transform", text="", icon="LOOP_BACK")
            op.node_name = self.name
            op.mode = "ROTATE_CCW"

            op = row.operator("refboard.image_transform", text="", icon="LOOP_FORWARDS")
            op.node_name = self.name
            op.mode = "ROTATE_CW"

            row = box.row(align=True)

            op = row.operator("refboard.image_transform", text="Flip X", icon="FORWARD")
            op.node_name = self.name
            op.mode = "FLIP_X"

            op = row.operator("refboard.image_transform", text="Flip Y", icon="SORT_DESC")
            op.node_name = self.name
            op.mode = "FLIP_Y"


# =========================================================
# DRAW CALLBACK
# =========================================================

def draw_callback():

    ctx = bpy.context
    space = ctx.space_data
    region = ctx.region

    if not space or space.type != "NODE_EDITOR":
        return

    tree = space.node_tree
    if not tree or tree.bl_idname != "RefBoardTreeType":
        return

    v2d = region.view2d
    image_shader = get_image_shader()
    outline_shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    outline_colors = get_refboard_outline_colors()
    active_node = tree.nodes.active
    #srgb = True
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(OUTLINE_WIDTH)

    try:
        nodes = sorted(
            [n for n in tree.nodes if n.bl_idname == "RefBoardImageNodeType" and n.image],
            key=lambda n: n.z_order
        )

        for node in nodes:

            img = node.image

            try:
                tex = gpu.texture.from_image(img)
            except Exception as exc:
                print(f"RefBoard: could not draw image {img.name!r}: {exc}")
                continue

            w = get_node_image_width(node)
            h = get_node_image_height(node)

            if DRAW_HANDLER_TYPE in {"PRE_VIEW", "POST_VIEW"}:
                x1, y1 = refboard_to_view_location(node.location.x, node.location.y)
                x2, y2 = refboard_to_view_location(node.location.x + w, node.location.y + h)
            else:
                x1_view, y1_view = refboard_to_view_location(node.location.x, node.location.y)
                x2_view, y2_view = refboard_to_view_location(node.location.x + w, node.location.y + h)
                x1, y1 = v2d.view_to_region(x1_view, y1_view, clip=False)
                x2, y2 = v2d.view_to_region(x2_view, y2_view, clip=False)

            coords = (
                (x1, y1),
                (x2, y1),
                (x2, y2),
                (x1, y2),
            )

            uvs = get_node_image_uvs(node)

            batch = batch_for_shader(image_shader, "TRI_FAN", {
                "pos": coords,
                "texCoord": uvs,
            })

            image_shader.bind()
            image_shader.uniform_sampler("image", tex)
            batch.draw(image_shader)

            outline_coords = (
                (x1, y1),
                (x2, y1),
                (x2, y2),
                (x1, y2),
                (x1, y1),
            )
            outline_batch = batch_for_shader(outline_shader, "LINE_STRIP", {
                "pos": outline_coords,
            })

            outline_shader.bind()
            outline_shader.uniform_float(
                "color",
                get_node_outline_color(node, active_node, outline_colors)
            )
            outline_batch.draw(outline_shader)

    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')


# =========================================================
# DROP OPERATOR
# =========================================================

class RB_OT_drop_image_node(bpy.types.Operator):
    bl_idname = "refboard.drop_image"
    bl_label = "Drop Image Node"
    bl_description = "Create RefBoard image nodes from dropped image files"
    bl_options = {'INTERNAL'}

    filepath: bpy.props.StringProperty()
    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def execute(self, context):

        paths = get_image_filepaths(self)
        image_paths, refbmd_paths = split_refboard_transfer_paths(paths)

        if not image_paths and not refbmd_paths:
            return {'CANCELLED'}

        if image_paths:
            location = get_view_center_location(context)
            created_nodes = add_image_nodes_from_paths(self, context, image_paths, location)

            if not created_nodes:
                return {'CANCELLED'}

            return {'FINISHED'}

        imported_boards, imported_images = import_refbmd_files(self, context, refbmd_paths)

        if imported_boards == 0:
            return {'CANCELLED'}

        self.report({'INFO'}, f"Imported {imported_boards} RefBoard file(s), {imported_images} image(s)")
        return {'FINISHED'}


# =========================================================
# FILE HANDLER
# =========================================================

class RB_FH_image_drop(bpy.types.FileHandler):
    bl_idname = "RB_FH_image_drop"
    bl_label = "RefBoard File Drop"

    bl_import_operator = "refboard.drop_image"
    bl_file_extensions = ".png;.jpg;.jpeg;.tga;.bmp;.exr;.webp;.refbmd"

    @classmethod
    def poll_drop(cls, context):
        return is_refboard_context(context)


# =========================================================
# PASTE IMAGE
# =========================================================

class RB_OT_paste_image_node(bpy.types.Operator):
    bl_idname = "refboard.paste_image"
    bl_label = "Paste Image"
    bl_description = "Paste image files or image pixels from the clipboard into the current RefBoard"

    location: bpy.props.FloatVectorProperty(size=2)

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def invoke(self, context, event):

        self.location = get_add_image_location(context, event)
        return self.execute(context)

    def execute(self, context):

        paths, pack_clipboard_images = get_clipboard_transfer_filepaths()

        if not paths:
            self.report({'INFO'}, "Clipboard does not contain RefBoard-compatible data")
            return {'CANCELLED'}

        image_paths, refbmd_paths = split_refboard_transfer_paths(paths)

        if refbmd_paths and not image_paths:
            imported_boards, imported_images = import_refbmd_files(self, context, refbmd_paths)

            if imported_boards == 0:
                return {'CANCELLED'}

            self.report({'INFO'}, f"Imported {imported_boards} RefBoard file(s), {imported_images} image(s)")
            return {'FINISHED'}

        if image_paths:
            paths = image_paths

        created_nodes = add_image_nodes_from_paths(
            self,
            context,
            paths,
            self.location,
            pack_images=pack_clipboard_images,
            cleanup_files=pack_clipboard_images
        )

        if not created_nodes:
            return {'CANCELLED'}

        return {'FINISHED'}


# =========================================================
# ADD IMAGE
# =========================================================

class RB_OT_add_image_node(bpy.types.Operator):
    bl_idname = "refboard.add_image"
    bl_label = "Add Image"
    bl_description = "Choose one or more image files and add them as RefBoard image nodes"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    location: bpy.props.FloatVectorProperty(size=2)

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def invoke(self, context, event):

        self.location = get_add_image_location(context, event)

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):

        paths = get_image_filepaths(self)

        if not paths:
            return {'CANCELLED'}
        created_nodes = add_image_nodes_from_paths(self, context, paths, self.location)

        if not created_nodes:
            return {'CANCELLED'}

        return {'FINISHED'}


# =========================================================
# REFBMD IMPORT / EXPORT
# =========================================================

class RB_OT_export_refbmd(bpy.types.Operator):
    bl_idname = "refboard.export_refbmd"
    bl_label = "Export"
    bl_description = "Export the current RefBoard to a portable .refbmd file"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.refbmd", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def invoke(self, context, event):
        self.filepath = get_refbmd_default_export_path(context.space_data.node_tree)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def check(self, context):
        filepath = ensure_refbmd_extension(self.filepath)

        if filepath != self.filepath:
            self.filepath = filepath
            return True

        return False

    def execute(self, context):
        tree = context.space_data.node_tree
        filepath = ensure_refbmd_extension(self.filepath)
        nodes = [
            node for node in tree.nodes
            if node.bl_idname == "RefBoardImageNodeType"
            and node.image
        ]

        if not nodes:
            self.report({'WARNING'}, "Current RefBoard has no images to export")
            return {'CANCELLED'}

        manifest = {
            "format": REFBMD_FORMAT,
            "format_version": REFBMD_FORMAT_VERSION,
            "nodes": [],
        }

        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
        except OSError:
            pass

        try:
            with tempfile.TemporaryDirectory(prefix="refbmd_export_") as temp_dir:
                with zipfile.ZipFile(filepath, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                    for index, node in enumerate(nodes, start=1):
                        ext = get_image_export_extension(node.image)
                        archive_path = f"images/image_{index:04d}{ext}"
                        write_image_to_refbmd(zip_file, node.image, archive_path, temp_dir)
                        node_entry = {
                            "image": archive_path,
                            "location": [float(node.location.x), float(node.location.y)],
                            "scale": float(node.scale),
                            "z_order": int(node.z_order),
                        }

                        rotation_quarters = int(getattr(node, "rotation_quarters", 0)) % 4

                        if rotation_quarters:
                            node_entry["rotation_quarters"] = rotation_quarters

                        if getattr(node, "flip_x", False):
                            node_entry["flip_x"] = True

                        if getattr(node, "flip_y", False):
                            node_entry["flip_y"] = True

                        manifest["nodes"].append(node_entry)

                    zip_file.writestr(
                        "manifest.json",
                        json.dumps(manifest, ensure_ascii=False, indent=2)
                    )
        except Exception as exc:
            self.report({'ERROR'}, f"Could not export RefBoard: {exc}")
            return {'CANCELLED'}

        self.filepath = filepath
        self.report({'INFO'}, f"Exported RefBoard: {os.path.basename(filepath)}")
        return {'FINISHED'}


class RB_OT_import_refbmd(bpy.types.Operator):
    bl_idname = "refboard.import_refbmd"
    bl_label = "Import"
    bl_description = "Import a portable .refbmd RefBoard file"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.refbmd", options={'HIDDEN'})

    def invoke(self, context, event):
        self.filepath = os.path.join(get_refbmd_default_directory(), "")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "Choose a .refbmd file to import")
            return {'CANCELLED'}

        try:
            tree, imported_count = import_refbmd_file(self, context, self.filepath)
        except Exception as exc:
            self.report({'ERROR'}, f"Could not import RefBoard: {exc}")
            return {'CANCELLED'}

        if not tree:
            self.report({'WARNING'}, "No images were imported from this .refbmd file")
            return {'CANCELLED'}

        set_context_refboard_tree(context, tree)
        self.report({'INFO'}, f"Imported RefBoard: {tree.name}")
        tag_refboard_redraw(context)
        frame_refboard_selected(context, tree)
        return {'FINISHED'}


# =========================================================
# MENU
# =========================================================

class RB_OT_add_image_menu(bpy.types.Operator):
    bl_idname = "refboard.add_image_menu"
    bl_label = "Add Image"
    bl_description = "Choose one or more image files and add them to the current RefBoard"

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def execute(self, context):
        bpy.ops.refboard.add_image('INVOKE_DEFAULT')
        return {'FINISHED'}


def draw_in_node_add_menu(self, context):

    space = context.space_data

    if not space or space.type != "NODE_EDITOR":
        return

    if not space.node_tree:
        return

    if getattr(space.node_tree, "bl_idname", "") != "RefBoardTreeType":
        return

    layout = self.layout
    layout.separator()
    layout.operator("refboard.add_image_menu", text="Add Image", icon="IMAGE_DATA")


# =========================================================
# PANEL
# =========================================================

class RB_PT_panel(bpy.types.Panel):
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "RefBoard"
    bl_label = "RefBoard"

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def draw(self, context):
        layout = self.layout

        layout.label(text="Images")
        layout.operator("refboard.add_image", icon="IMAGE_DATA")
        layout.operator("refboard.paste_image", icon="PASTEDOWN")
        row = layout.row(align=True)
        row.operator("refboard.export_refbmd", icon="EXPORT")
        row.operator("refboard.import_refbmd", icon="IMPORT")

        layout.separator()

        box = layout.box()
        box.label(text="Arrange")

        box.label(text="Match Size")
        row = box.row(align=True)
        op = row.operator("refboard.match_size", text="Width")
        op.mode = "WIDTH"

        op = row.operator("refboard.match_size", text="Height")
        op.mode = "HEIGHT"

        box.separator()
        box.label(text="Layout")
        row = box.row(align=True)
        op = row.operator("refboard.align_nodes", text="Row", icon="RIGHTARROW")
        op.mode = "ROW"

        op = row.operator("refboard.align_nodes", text="Column", icon="DOWNARROW_HLT")
        op.mode = "COL"

        op = row.operator("refboard.align_nodes", text="Grid", icon="SNAP_VERTEX")
        op.mode = "GRID"

        box.separator()
        box.label(text="Align")
        row = box.row(align=True)
        row.label(text="", icon="SPLIT_HORIZONTAL")
        op = row.operator("refboard.align_to_active", text="Top")
        op.mode = "H_TOP"

        op = row.operator("refboard.align_to_active", text="Middle")
        op.mode = "H_CENTER"

        op = row.operator("refboard.align_to_active", text="Bottom")
        op.mode = "H_BOTTOM"

        row = box.row(align=True)
        row.label(text="", icon="SPLIT_VERTICAL")
        op = row.operator("refboard.align_to_active", text="Left")
        op.mode = "V_LEFT"

        op = row.operator("refboard.align_to_active", text="Center")
        op.mode = "V_CENTER"

        op = row.operator("refboard.align_to_active", text="Right")
        op.mode = "V_RIGHT"


# =========================================================
# REGISTER
# =========================================================

classes = (
    RefBoardTree,
    RefBoardImageNode,
    RB_OT_z_adjust,
    RB_OT_image_transform,
    RB_OT_align_nodes,
    RB_OT_align_to_active,
    RB_OT_match_size,
    RB_OT_select_image,
    RB_OT_scale_with_images,
    RB_OT_drop_image_node,
    RB_FH_image_drop,
    RB_OT_paste_image_node,
    RB_OT_add_image_menu,
    RB_OT_add_image_node,
    RB_OT_export_refbmd,
    RB_OT_import_refbmd,
    RB_PT_panel,
)


def register():

    global _handle, _overlay_handle, _keymaps, _menu_added

    for c in classes:
        bpy.utils.register_class(c)

    if not _menu_added:
        bpy.types.NODE_MT_add.append(draw_in_node_add_menu)
        _menu_added = True

    _handle = bpy.types.SpaceNodeEditor.draw_handler_add(
        draw_callback, (), "WINDOW", DRAW_HANDLER_TYPE
    )
    _overlay_handle = bpy.types.SpaceNodeEditor.draw_handler_add(
        draw_scale_overlay_callback, (), "WINDOW", "POST_PIXEL"
    )

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    if kc:
        km = kc.keymaps.new(name="Node Editor", space_type="NODE_EDITOR")
        for value in ("PRESS", "RELEASE"):
            kmi = km.keymap_items.new("refboard.select_image", "LEFTMOUSE", value)
            _keymaps.append((km, kmi))
            kmi = km.keymap_items.new("refboard.select_image", "LEFTMOUSE", value, shift=True)
            _keymaps.append((km, kmi))
            kmi = km.keymap_items.new("refboard.select_image", "LEFTMOUSE", value, ctrl=True)
            _keymaps.append((km, kmi))
            kmi = km.keymap_items.new(
                "refboard.select_image",
                "LEFTMOUSE",
                value,
                shift=True,
                ctrl=True
            )
            _keymaps.append((km, kmi))
        kmi = km.keymap_items.new("refboard.scale_with_images", "S", "PRESS")
        _keymaps.append((km, kmi))
        kmi = km.keymap_items.new("refboard.paste_image", "V", "PRESS", ctrl=True)
        _keymaps.append((km, kmi))


def unregister():

    global _handle, _overlay_handle, _keymaps, _menu_added, _scale_overlay

    if _menu_added:
        try:
            bpy.types.NODE_MT_add.remove(draw_in_node_add_menu)
        except (AttributeError, ValueError):
            pass

        _menu_added = False

    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except RuntimeError:
            pass

    _keymaps.clear()

    if _handle:
        try:
            bpy.types.SpaceNodeEditor.draw_handler_remove(_handle, "WINDOW")
        except (ReferenceError, RuntimeError):
            pass

        _handle = None

    if _overlay_handle:
        try:
            bpy.types.SpaceNodeEditor.draw_handler_remove(_overlay_handle, "WINDOW")
        except (ReferenceError, RuntimeError):
            pass

        _overlay_handle = None

    _scale_overlay = None

    for c in reversed(classes):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass


if __name__ == "__main__":
    register()
