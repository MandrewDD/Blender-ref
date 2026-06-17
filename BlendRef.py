bl_info = {
    "name": "RefBoard Node Editor",
    "author": "Mandrew3D",
    "version": (1, 2, 0),
    "blender": (5, 1, 0),
    "category": "Node",
}

import bpy
import gpu
import gpu.texture
import os
from gpu_extras.batch import batch_for_shader

_handle = None


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

        offset_x += w + 50


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

        n.location.x = x
        n.location.y = start_y - offset_y

        offset_y += h + 50


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

    node_name: bpy.props.StringProperty()
    direction: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

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

    mode: bpy.props.StringProperty()  # ROW / COL

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

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

        tag_refboard_redraw(context)

        return {'FINISHED'}


# =========================================================
# MATCH SIZE
# =========================================================

class RB_OT_match_size(bpy.types.Operator):
    bl_idname = "refboard.match_size"
    bl_label = "Match Size"

    mode: bpy.props.StringProperty()  # WIDTH / HEIGHT

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

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

    image: bpy.props.PointerProperty(type=bpy.types.Image, update=update_node_draw)
    scale: bpy.props.FloatProperty(default=1.0, min=0.01, max=100.0, update=update_node_draw)
    z_order: bpy.props.IntProperty(default=0, update=update_node_draw)

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

        for node in tree.nodes:
            node.select = False

        created_nodes = []

        for filepath in paths:
            img = bpy.data.images.load(filepath, check_existing=True)

            node = tree.nodes.new("RefBoardImageNodeType")
            node.image = img
            node.location = (200, 200)

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
    bl_label = "Add Image Node"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    location: bpy.props.FloatVectorProperty(size=2)

    @classmethod
    def poll(cls, context):
        return is_refboard_context(context)

    def invoke(self, context, event):

        region = context.region
        v2d = region.view2d

        loc = v2d.region_to_view(
            event.mouse_region_x,
            event.mouse_region_y
        )

        self.location = loc

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

        layout.label(text="Add")
        layout.operator("refboard.add_image")

        layout.separator()

        layout.label(text="Grouping")

        row = layout.row()
        op = row.operator("refboard.align_nodes", text="Row")
        op.mode = "ROW"

        op = row.operator("refboard.align_nodes", text="Column")
        op.mode = "COL"

        layout.separator()

        layout.label(text="Match Size")

        row = layout.row()
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
        draw_callback, (), "WINDOW", "POST_PIXEL"
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
