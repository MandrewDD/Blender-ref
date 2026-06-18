bl_info = {
    "name": "RefBoard",
    "author": "Mandrew3D",
    "version": (1, 2, 0),
    "blender": (5, 1, 0),
    "category": "Node",
}

import bpy
import gpu
import gpu.texture
import math
import os
from gpu_extras.batch import batch_for_shader

_handle = None
_keymaps = []
_click_candidate = None
NODE_HEADER_HEIGHT = 120
NODE_SPACING = 50
DRAW_HANDLER_TYPE = "PRE_VIEW"
OUTLINE_WIDTH = 2.0
SCALE_EPSILON = 0.0001
CLICK_DRAG_THRESHOLD = 5


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
        w = n.image.size[0] * n.scale

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
        h = n.image.size[1] * n.scale

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

    max_width = max(n.image.size[0] * n.scale for n in ordered_nodes)
    max_height = max(n.image.size[1] * n.scale for n in ordered_nodes)
    cell_width = max_width + NODE_SPACING
    cell_height = max_height + NODE_HEADER_HEIGHT + NODE_SPACING

    for index, n in enumerate(ordered_nodes):
        col = index % cols
        row = index // cols

        n.location.x = start_x + col * cell_width
        n.location.y = start_y - row * cell_height


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


def update_node_draw(self, context):
    tag_refboard_redraw(context)


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
    ui_scale = get_ui_scale()

    return (loc[0] / ui_scale, loc[1] / ui_scale)


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
    ui_scale = get_ui_scale()

    return (loc[0] / ui_scale, loc[1] / ui_scale)


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
    ui_scale = get_ui_scale()

    return (loc[0] / ui_scale, loc[1] / ui_scale)


def find_image_node_at_location(tree, location):
    x, y = location

    nodes = sorted(
        [n for n in tree.nodes if n.bl_idname == "RefBoardImageNodeType" and n.image],
        key=lambda n: n.z_order,
        reverse=True
    )

    for node in nodes:
        image_width = node.image.size[0] * node.scale
        image_height = node.image.size[1] * node.scale

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


# =========================================================
# UI SCALE
# =========================================================

def get_ui_scale():
    prefs = bpy.context.preferences
    dpi_fac = prefs.system.dpi / 72.0
    ui_fac = getattr(prefs.view, "ui_scale", 1.0)
    return dpi_fac * ui_fac


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
            target_width = active.image.size[0] * active.scale

            for n in nodes:
                if n.image.size[0] > 0:
                    n.scale = target_width / n.image.size[0]

        elif self.mode == "HEIGHT":
            target_height = active.image.size[1] * active.scale

            for n in nodes:
                if n.image.size[1] > 0:
                    n.scale = target_height / n.image.size[1]

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

        if self._shift or self._ctrl:
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

    def apply_scale(self, context, factor):
        nodes = self.get_nodes(context)

        for node in nodes:
            initial_location = self._initial_locations[node.name]

            if len(nodes) > 1:
                node.location.x = self._pivot[0] + (initial_location[0] - self._pivot[0]) * factor
                node.location.y = self._pivot[1] + (initial_location[1] - self._pivot[1]) * factor

            node.scale = self._initial_scales[node.name] * factor

        tag_refboard_redraw(context)

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

        if not self._start_mouse_location:
            return {'CANCELLED'}

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):

        if not is_refboard_context(context):
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            current_location = get_event_view_location(context, event)

            if current_location:
                factor = get_scale_factor_from_mouse(
                    self._pivot,
                    self._start_mouse_location,
                    current_location
                )
                self.apply_scale(context, factor)

        elif event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'SPACE'} and event.value == 'RELEASE':
            return {'FINISHED'}

        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            self.restore_transform(context)
            return {'CANCELLED'}

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
    ui_scale = get_ui_scale()

    image_shader = gpu.shader.from_builtin("IMAGE_SCENE_LINEAR_TO_REC709_SRGB")
    outline_shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    outline_colors = get_refboard_outline_colors()
    active_node = tree.nodes.active
    #srgb = True
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(OUTLINE_WIDTH)

    nodes = sorted(
        [n for n in tree.nodes if n.bl_idname == "RefBoardImageNodeType" and n.image],
        key=lambda n: n.z_order
    )

    for node in nodes:

        img = node.image
        tex = gpu.texture.from_image(img)

        w = img.size[0] * node.scale
        h = img.size[1] * node.scale

        if DRAW_HANDLER_TYPE in {"PRE_VIEW", "POST_VIEW"}:
            x1 = node.location.x * ui_scale
            y1 = node.location.y * ui_scale
            x2 = (node.location.x + w) * ui_scale
            y2 = (node.location.y + h) * ui_scale
        else:
            x1, y1 = v2d.view_to_region(node.location.x * ui_scale, node.location.y * ui_scale, clip=False)
            x2, y2 = v2d.view_to_region((node.location.x + w) * ui_scale, (node.location.y + h) * ui_scale, clip=False)

        coords = (
            (x1, y1),
            (x2, y1),
            (x2, y2),
            (x1, y2),
        )

        uvs = (
            (0, 0),
            (1, 0),
            (1, 1),
            (0, 1),
        )

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

        tree = context.space_data.node_tree
        paths = []

        if self.files:
            paths = [os.path.join(self.directory, f.name) for f in self.files]
        elif self.filepath:
            paths = [self.filepath]

        if not paths:
            return {'CANCELLED'}

        location = get_view_center_location(context)

        for node in tree.nodes:
            node.select = False

        created_nodes = []

        for filepath in paths:
            img = bpy.data.images.load(filepath, check_existing=True)

            node = tree.nodes.new("RefBoardImageNodeType")
            node.image = img
            node.location = location

            node.select = True
            created_nodes.append(node)

        tree.nodes.active = created_nodes[0]
        align_nodes_row(created_nodes, created_nodes[0])

        tag_refboard_redraw(context)

        return {'FINISHED'}


# =========================================================
# FILE HANDLER
# =========================================================

class RB_FH_image_drop(bpy.types.FileHandler):
    bl_idname = "RB_FH_image_drop"
    bl_label = "RefBoard Image Drop"

    bl_import_operator = "refboard.drop_image"
    bl_file_extensions = ".png;.jpg;.jpeg;.tga;.bmp;.exr;.webp"

    @classmethod
    def poll_drop(cls, context):
        return is_refboard_context(context)


# =========================================================
# ADD IMAGE
# =========================================================

class RB_OT_add_image_node(bpy.types.Operator):
    bl_idname = "refboard.add_image"
    bl_label = "Add Image"
    bl_description = "Choose an image file and add it as a RefBoard image node"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    location: bpy.props.FloatVectorProperty(size=2)

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def invoke(self, context, event):

        self.location = get_add_image_location(context, event)

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):

        tree = context.space_data.node_tree
        img = bpy.data.images.load(self.filepath, check_existing=True)

        node = tree.nodes.new("RefBoardImageNodeType")
        node.image = img
        node.location = self.location

        node.select = True
        tree.nodes.active = node

        tag_refboard_redraw(context)

        return {'FINISHED'}


# =========================================================
# MENU
# =========================================================

class RB_OT_add_image_menu(bpy.types.Operator):
    bl_idname = "refboard.add_image_menu"
    bl_label = "Add Image"
    bl_description = "Choose an image file and add it to the current RefBoard"

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

        layout.separator()

        box = layout.box()
        box.label(text="Arrange")

        box.label(text="Layout")
        row = box.row(align=True)
        op = row.operator("refboard.align_nodes", text="Row")
        op.mode = "ROW"

        op = row.operator("refboard.align_nodes", text="Column")
        op.mode = "COL"

        op = row.operator("refboard.align_nodes", text="Grid")
        op.mode = "GRID"

        box.separator()
        box.label(text="Match Size")
        row = box.row(align=True)
        op = row.operator("refboard.match_size", text="Width")
        op.mode = "WIDTH"

        op = row.operator("refboard.match_size", text="Height")
        op.mode = "HEIGHT"


# =========================================================
# REGISTER
# =========================================================

classes = (
    RefBoardTree,
    RefBoardImageNode,
    RB_OT_z_adjust,
    RB_OT_align_nodes,
    RB_OT_match_size,
    RB_OT_select_image,
    RB_OT_scale_with_images,
    RB_OT_drop_image_node,
    RB_FH_image_drop,
    RB_OT_add_image_menu,
    RB_OT_add_image_node,
    RB_PT_panel,
)


_handle = None


def register():

    global _handle, _keymaps

    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.NODE_MT_add.append(draw_in_node_add_menu)

    _handle = bpy.types.SpaceNodeEditor.draw_handler_add(
        draw_callback, (), "WINDOW", DRAW_HANDLER_TYPE
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


def unregister():

    global _handle, _keymaps

    bpy.types.NODE_MT_add.remove(draw_in_node_add_menu)

    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)

    _keymaps.clear()

    if _handle:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_handle, "WINDOW")
        _handle = None

    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
