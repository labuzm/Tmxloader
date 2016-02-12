import os
import zlib
import weakref
from base64 import b64decode
from xml.etree import ElementTree
from itertools import islice, product, ifilter, imap, chain

from utils import to_python, unpack_struct, decode_gid,\
    AnimationFrame, ObjectType, LayerType


class Element(object):
    description_attribute = None

    def __init__(self):
        self.properties = {}

    def __unicode__(self):
        return u'<{}@{}>'.format(
                self.__class__.__name__,
                getattr(self, self.description_attribute)
        )

    def __repr__(self):
        return self.__unicode__()

    def set_property(self, name, value):
        try:
            prepare = getattr(self, 'prepare_prop_{}'.format(name))
        except AttributeError:
            pass
        else:
            value = prepare(value)
        self.properties[name] = value

    def set_properties_from_node(self, properties_node):
        if properties_node is None:
            return

        iter_children = islice(properties_node.iter(), 1, None)
        for prop in iter_children:
            key = prop.get('name')
            if key in self.properties:
                raise Exception('Property {} is already set on {}.'.format(key, self))

            self.set_property(key, prop.get('value'))

    def set_attr(self, attr_name, value):
        # omit all attributes that aren't explicitly set on instance
        if not hasattr(self, attr_name):
            return
        # cast to appropriate type
        value = to_python(attr_name, value)
        try:
            # some additional processing if required
            prepare = getattr(self, 'prepare_attr_{}'.format(attr_name))
        except AttributeError:
            pass
        else:
            value = prepare(value)
        setattr(self, attr_name, value)

    def set_attrs_from_node(self, node):
        for attr_name, value in node.items():
            self.set_attr(attr_name, value)

    def init_from_node(self, node):
        self.set_attrs_from_node(node)
        self.set_properties_from_node(node.find('properties'))


class ChildMixin(object):
    __slots__ = ('_parent', )

    def __init__(self, parent):
        super(ChildMixin, self).__init__()
        self._parent = weakref.ref(parent)

    @property
    def parent(self):
        return self._parent()

    @property
    def root(self):
        node = self
        while node.parent:
            node = node.parent
        return node


class AbsoluteSourceMixin(object):
    def prepare_attr_source(self, value):
        base_dir = os.path.dirname(self.root.source)
        return os.path.abspath(os.path.join(base_dir, value))


class ObjectElement(ChildMixin, Element):
    description_attribute = 'type'

    def __init__(self, node, parent):
        super(ObjectElement, self).__init__(parent)
        self.type = ObjectType.Rectangle
        self.flags = None

        self.x = 0
        self.y = self.prepare_attr_y(0)
        self.id = None
        self.gid = None
        self.width = 0
        self.height = 0
        self.name = None
        self.points = None
        self.visible = True
        self.rotation = None

        self.init_from_node(node)
        # TODO: testing required

    @property
    def pos(self):
        # TODO: in orthogonal orientation object's image is aligned to the bottom-left
        return self.x, self.y

    @property
    def size(self):
        return self.width, self.height

    @property
    def tile(self):
        if self.gid is None:
            return
        return self.root.tiles[self.gid]

    @property
    def image(self):
        if self.gid is None:
            return
        return self.tile.image

    def init_from_node(self, node):
        super(ObjectElement, self).init_from_node(node)

        for object_type in ObjectType:
            object_node = node.find(object_type)
            if object_node is not None:
                self.type = object_type
                self.set_attrs_from_node(object_node)
                break

    def prepare_attr_gid(self, gid):
        map_obj = self.root
        gid, self.flags = decode_gid(gid)
        # object uses tile as a image
        self.type = ObjectType.Tile
        if gid not in map_obj.tiles:
            # but the gid isn't registered yet
            tileset = map_obj.get_tileset_by_gid(gid)
            tileset.add_tile(None, gid=gid, width=tileset.tilewidth, height=tileset.tileheight)
        return gid

    def prepare_attr_y(self, y):
        map_obj = self.root
        if map_obj.invert_y:
            y = map_obj.size[1] - y
        return y

    def prepare_attr_points(self, value):
        points = []
        x, y = self.pos
        for cords in value.split():
            # local cords relative to object cords
            local_x, local_y = cords.split(',')
            points.append((x + float(local_x), y + float(local_y)))
        return tuple(points)


class ObjectGroup(ChildMixin, Element):
    description_attribute = 'name'

    def __init__(self, node, parent):
        super(ObjectGroup, self).__init__(parent)

        self.name = None
        self.objects = []
        self.opacity = 1
        self.offsetx = 0
        self.offsety = 0
        self.visible = True
        # Enum?
        self.draworder = 'topdown'

        self.init_from_node(node)

    def __iter__(self):
        return iter(self.objects)

    def init_from_node(self, node):
        super(ObjectGroup, self).init_from_node(node)

        for object_node in node.findall('object'):
            self.add_object(object_node)

    def add_object(self, object_node):
        self.objects.append(self.parent.objectelement_cls(node=object_node, parent=self))


class ImageLayer(ChildMixin, AbsoluteSourceMixin, Element):
    description_attribute = 'name'

    def __init__(self, node, parent):
        super(ImageLayer, self).__init__(parent)
        self.image = None

        self.name = None
        self.offsetx = 0
        # default values aren't stored in the .tmx file
        self.offsety = self.prepare_attr_offsety(0)
        self.opacity = 1
        self.source = None
        self.visible = True

        self.init_from_node(node)

    def prepare_attr_offsety(self, offsety):
        map_obj = self.root
        if map_obj.invert_y:
            offsety = map_obj.size[1] - offsety
        return offsety

    @property
    def pos(self):
        return self.offsetx,  self.offsety

    def init_from_node(self, node):
        super(ImageLayer, self).init_from_node(node)
        self.set_attrs_from_node(node.find('image'))


class TileElement(ChildMixin, AbsoluteSourceMixin, Element):
    description_attribute = 'gid'

    def __init__(self, node, parent, **kwargs):
        super(TileElement, self).__init__(parent)
        self.uvs = None
        self.image = None

        self.width = 0
        self.height = 0
        self.source = None

        self.id = None
        self.gid = None
        self.terrain = None
        self.probability = None

        if node is not None:
            self.init_from_node(node)

        for name, value in kwargs.iteritems():
            self.set_attr(name, value)

    @property
    def size(self):
        return self.width, self.height

    @property
    def rect(self):
        uvs = self.uvs
        if not uvs:
            return
        return uvs[0], uvs[1], self.width, self.height

    def init_from_node(self, node):
        super(TileElement, self).init_from_node(node)

        animation_node = node.find('animation')
        if animation_node is not None:
            self.handle_animation(animation_node)

        image_node = node.find('image')
        if image_node is not None:
            self.set_attrs_from_node(image_node)

        else:
            self.width = self.parent.tilewidth
            self.height = self.parent.tileheight

    def prepare_attr_id(self, local_id):
        self.gid = self.parent.firstgid + local_id
        return local_id

    def handle_animation(self, node):
        frames = []
        map_obj = self.root
        tileset = self.parent
        for frame_node in node.findall('frame'):
            tileid = to_python('tileid', frame_node.get('tileid'))
            gid = tileset.firstgid + tileid
            # add tile required to display animation
            if gid not in map_obj.tiles:
                tileset.add_tile(None, gid=gid, width=tileset.tilewidth, height=tileset.tileheight)
            duration = to_python('duration', frame_node.get('duration'))
            frames.append(AnimationFrame(gid, duration))
        self.set_property('animation_frames', tuple(frames))

    def set_uvs(self, uvs):
        if self.root.invert_tileset_y:
            x, y = uvs
            uvs = (x, self.height - y)
        self.uvs = uvs


class Cell(ChildMixin):
    __slots__ = ('x', 'y', 'gid', 'flags')

    def __init__(self, parent, gid, x, y, flags):
        super(Cell, self).__init__(parent)
        self.gid = gid
        self.flags = flags

        tile = self.tile
        x = x * tile.width
        y = y * tile.height

        map_obj = self.root
        if map_obj.invert_y:
            y = map_obj.size[1] - y

        self.x = x
        self.y = y

    def __unicode__(self):
        return u'{}@{}'.format(self.__class__.__name__, self.gid)

    def __repr__(self):
        return self.__unicode__()

    @property
    def pos(self):
        return self.x, self.y

    @property
    def tile(self):
        return self.root.tiles[self.gid]

    @property
    def image(self):
        return self.tile.image

    @property
    def size(self):
        return self.tile.size


class TileLayer(ChildMixin, Element):
    description_attribute = 'name'

    def __init__(self, node, parent):
        super(TileLayer, self).__init__(parent)
        self.data = None

        self.name = None
        self.width = 0
        self.height = 0
        self.opacity = 1
        self.offsetx = 0
        self.offsety = 0
        self.visible = True

        self.init_from_node(node)

    def __iter__(self):
        return ifilter(None, self.data)

    @staticmethod
    def prepare_attr_width(value):
        return int(value)

    @staticmethod
    def prepare_attr_height(value):
        return int(value)

    def init_from_node(self, node):
        super(TileLayer, self).init_from_node(node)

        data_node = node.find('data')
        encoding = data_node.get('encoding')
        data = data_node.text.strip()
        if encoding == 'base64':
            data = b64decode(data)
            compression = data_node.get('compression')
            if compression == 'zlib':
                data = zlib.decompress(data)
            elif compression == 'qzip':
                raise NotImplementedError
            elif compression is not None:
                raise Exception('Unsupported data compression: {}.'.format(compression))
            data = iter(unpack_struct(data))

        elif encoding == 'csv':
            ichain = chain.from_iterable
            data = ichain(imap(int, ifilter(None, line.split(','))) for line in data.splitlines())
        else:
            raise Exception('Unsupported data encoding: {}.'.format(encoding))

        # TODO: handle scenario when gids are stored in <tile>s, rather than <data> tag

        width = self.width
        height = self.height
        add_cell = self.add_cell
        self.data = tuple(add_cell(next(data), x, y) for y in xrange(height) for x in xrange(width))

    def add_cell(self, gid, x, y):
        if not gid:
            return

        gid, flags = decode_gid(gid)
        # add tiles that haven't been listed in tileset
        if gid not in self.parent.tiles:
            self.add_tile(gid)
        return Cell(self, gid, x, y, flags)

    def add_tile(self, gid):
        tileset = self.parent.get_tileset_by_gid(gid)
        tileset.add_tile(None, gid=gid, width=tileset.tilewidth, height=tileset.tileheight)


class TileSet(ChildMixin, AbsoluteSourceMixin, Element):
    description_attribute = 'name'

    def __init__(self, node, parent):
        super(TileSet, self).__init__(parent)
        self.maxgid = 0

        self.width = 0
        self.height = 0
        self.trans = None
        self.source = None

        self.name = None
        self.margin = 0
        self.spacing = 0
        self.tilewidth = 0
        self.tileheight = 0
        self.firstgid = None

        self.init_from_node(node)
        # TODO: handle <tileoffset> tag

    def __iter__(self):
        tiles = self.parent.tiles
        for gid in xrange(self.firstgid, self.firstgid + self.maxgid):
            try:
                yield tiles[gid]
            except KeyError:
                continue

    @property
    def is_images_collection(self):
        return self.source is None

    def init_from_node(self, node):
        super(TileSet, self).init_from_node(node)

        # handle externals tilesets
        source = self.source
        if source and os.path.splitext(source)[1] == '.tsx':
            self.source = None
            external_tileset_node = ElementTree.parse(source).getroot()
            self.init_from_node(external_tileset_node)

        image_node = node.find('image')
        if image_node is not None:
            self.set_attrs_from_node(image_node)

        for tile_node in node.iter('tile'):
            self.add_tile(tile_node)

    def add_tile(self, node, **kwargs):
        tile = TileElement(node, self, **kwargs)
        self.parent.tiles[tile.gid] = tile
        if tile.gid > self.maxgid:
            self.maxgid = tile.gid
        return tile


def default_loader(tileset=None, image_layer=None):
    """
    We are handling here tree types of objects:
    1) tileset with a source (single image tileset)
    2) tileset without a source (image collection tileset, each tile holds own image)
    3) image layer (layer that holds single image source)
    """
    def extract_image(tile=None):
        if tile is None:
            return image_layer.source
        return (tileset or tile).source
    return extract_image


class TileMap(Element):
    description_attribute = 'source'

    tileset_cls = TileSet
    tilelayer_cls = TileLayer
    tilelement_cls = TileElement
    imagelayer_cls = ImageLayer
    objectgroup_cls = ObjectGroup
    objectelement_cls = ObjectElement

    def __init__(self, map_source, image_loader=None, load_unused_tiles=False,
                 invert_y=True, invert_tileset_y=False):
        super(TileMap, self).__init__()
        self.root = self
        self.parent = None
        self.source = map_source
        self.invert_y = invert_y
        self.invert_tileset_y = invert_tileset_y
        self.load_unused_tiles = load_unused_tiles
        self.load_image = image_loader or default_loader

        self.width = 0
        self.height = 0
        self.tilewidth = 0
        self.tileheight = 0
        self.version = None
        self.renderorder = None
        self.orientation = None
        self.nextobjectid = None

        self.tiles = {}
        self.layers = []
        self.tilesets = []

        self.load_map_data(map_source)

    @property
    def size(self):
        return self.width * self.tilewidth, self.height * self.tileheight

    @property
    def visible_layers(self):
        return self._get_layers(layer_type=None, visible=True)

    def get_tile_layers(self, visible=None):
        return self._get_layers(self.tilelayer_cls, visible)

    def get_image_layers(self, visible=None):
        return self._get_layers(self.imagelayer_cls, visible)

    def get_object_groups(self, visible=None):
        return self._get_layers(self.objectgroup_cls, visible)

    def _get_layers(self, layer_type, visible):
        for layer in self.layers:
            if layer_type is None or isinstance(layer, layer_type):
                if visible is None or layer.visible == visible:
                    yield layer

    def get_tile(self, gid):
        return self.tiles[gid]

    def load_map_data(self, map_source):
        root_node = ElementTree.parse(map_source).getroot()
        return self.init_from_node(root_node)

    def init_from_node(self, node):
        super(TileMap, self).init_from_node(node)

        for child in node.findall('tileset'):
            self.add_tileset(child)

        for child in node.getchildren():
            tag = child.tag
            if tag in LayerType:
                self.add_layer(child)

        self.load_images()

    def add_tileset(self, node):
        self.tilesets.append(self.tileset_cls(node=node, parent=self))

    def add_layer(self, node):
        tag = node.tag
        if tag == LayerType.TileLayer:
            self.layers.append(self.tilelayer_cls(node=node, parent=self))
        elif tag == LayerType.ImageLayer:
            self.layers.append(self.imagelayer_cls(node=node, parent=self))
        elif tag == LayerType.ObjectGroup:
            self.layers.append(self.objectgroup_cls(node=node, parent=self))
        else:
            raise Exception('Unknown layer type: "{}".'.format(tag))

    def load_images(self):
        tiles = self.tiles
        load_image = self.load_image
        load_unused_tiles = self.load_unused_tiles
        for tileset in self.tilesets:
            loader = load_image(tileset=tileset)
            if tileset.is_images_collection:
                for tile in tileset:
                    tile.image = loader(tile=tile)
                continue

            t = tileset
            reversed_uvs_product = product(
                    xrange(t.margin, t.height + 1 - t.tileheight, t.tileheight + t.spacing),
                    xrange(t.margin, t.width + 1 - t.tilewidth, t.tilewidth + t.spacing)
            )
            for gid, (y, x) in enumerate(reversed_uvs_product, t.firstgid):
                tile = tiles.get(gid)
                if tile is None:
                    if not load_unused_tiles:
                        continue
                    tile = tileset.add_tile(None, gid=gid, width=tileset.tilewidth,
                                            height=tileset.tileheight)
                tile.set_uvs((x, y))
                tile.image = loader(tile=tile)

        for image_layer in self.get_image_layers():
            loader = load_image(image_layer=image_layer)
            image_layer.image = loader()

    def get_tileset_by_gid(self, gid):
        for tileset in reversed(self.tilesets):
            if gid >= tileset.firstgid:
                return tileset
