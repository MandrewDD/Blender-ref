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
NODE_HEADER_HEIGHT = 120
NODE_SPACING = 50
DRAW_HANDLER_TYPE = "PRE_VIEW"


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

    shader = gpu.shader.from_builtin("IMAGE_SCENE_LINEAR_TO_REC709_SRGB")
    #srgb = True
    gpu.state.blend_set('ALPHA')

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

        batch = batch_for_shader(shader, "TRI_FAN", {
            "pos": coords,
            "texCoord": uvs,
        })

        shader.bind()
        shader.uniform_sampler("image", tex)
        batch.draw(shader)

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
        box.label(text="Match Active")
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
    RB_OT_drop_image_node,
    RB_FH_image_drop,
    RB_OT_add_image_menu,
    RB_OT_add_image_node,
    RB_PT_panel,
)


_handle = None


def register():

    global _handle

    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.NODE_MT_add.append(draw_in_node_add_menu)

    _handle = bpy.types.SpaceNodeEditor.draw_handler_add(
        draw_callback, (), "WINDOW", DRAW_HANDLER_TYPE
    )


def unregister():

    global _handle

    bpy.types.NODE_MT_add.remove(draw_in_node_add_menu)

    if _handle:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_handle, "WINDOW")
        _handle = None

    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
