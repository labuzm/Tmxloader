import struct
import weakref
from operator import attrgetter
from collections import defaultdict, namedtuple

FLIPPED_VERTICALLY_FLAG = 0x40000000
FLIPPED_DIAGONALLY_FLAG = 0x20000000
FLIPPED_HORIZONTALLY_FLAG = 0x80000000

TextureFlags = namedtuple('flags', ('flipped_horizontally', 'flipped_vertically', 'flipped_diagonally'))


class AnimationFrame(object):
    __slots__ = ('gid', 'duration', '_root')

    def __init__(self, gid, duration, root):
        self.gid = gid
        self.duration = duration
        self._root = weakref.ref(root)

    def __unicode__(self):
        return u'{}@{}'.format(self.__class__.__name__, self.gid)

    def __repr__(self):
        return self.__unicode__()

    @property
    def root(self):
        return self._root()

    @property
    def image(self):
        tile = self.root.tiles[self.gid]
        return tile.image

    @property
    def duration_seconds(self):
        return self.duration / 1000.0


def is_not_dunder(name):
    dunder = '__'
    if len(name) > 4 and name.startswith(dunder) and name.endswith(dunder):
        return False
    return True


class Enum(object):
    class __metaclass__(type):
        def __iter__(self):
            for name, value in self.__dict__.iteritems():
                if is_not_dunder(name) and not callable(value):
                    yield value


class ObjectType(Enum):
    Tile = 'tile'
    Ellipse = 'ellipse'
    Polygon = 'polygon'
    Polyline = 'polyline'
    Rectangle = 'rectangle'


class LayerType(Enum):
    TileLayer = 'layer'
    ImageLayer = 'imagelayer'
    ObjectGroup = 'objectgroup'


BOOLEAN_VALUES = {
    True: ('true', 'yes', '1'),
    False: ('false', 'no', '0')
}


def convert_to_bool(value):
    try:
        bool(int(value))
    except ValueError:
        pass

    for boolean, values in BOOLEAN_VALUES.iteritems():
        if value in values:
            return boolean

    raise Exception('Unknown boolean value: {}'.format(value))


PROPERTIES_TYPES = defaultdict(lambda: str)
PROPERTIES_TYPES.update({
    'compression': str,
    'columns': str,
    'encoding': str,
    'firstgid': int,
    'gid': int,
    'height': int,
    'id': int,
    'margin': int,
    'name': str,
    'opacity': float,
    'orientation': str,
    'rotation': float,
    'source': str,
    'spacing': int,
    'tilecount': int,
    'tileheight': int,
    'tilewidth': int,
    'trans': str,
    'type': str,
    'value': str,
    'version': float,
    'visible': convert_to_bool,
    'width': int,
    'x': float,
    'y': float,
    'tileid': int,
    'duration': int
})


def to_python(property_name, value):
    return PROPERTIES_TYPES[property_name](value)


def unpack_struct(data):
    l = len(data)
    template = '<%dI'
    format_size = struct.calcsize(template % 1)
    return struct.unpack(template % (l / format_size), data)


def decode_gid(gid):
    flipped_horizontally = gid & FLIPPED_HORIZONTALLY_FLAG == FLIPPED_HORIZONTALLY_FLAG
    flipped_vertically = gid & FLIPPED_VERTICALLY_FLAG == FLIPPED_VERTICALLY_FLAG
    flipped_diagonally = gid & FLIPPED_DIAGONALLY_FLAG == FLIPPED_DIAGONALLY_FLAG
    flags = TextureFlags(flipped_horizontally, flipped_vertically, flipped_diagonally)
    gid &= ~(FLIPPED_HORIZONTALLY_FLAG | FLIPPED_VERTICALLY_FLAG | FLIPPED_DIAGONALLY_FLAG)
    return gid, flags


class MultipleElementsException(Exception):
    pass


class ElementNotFound(Exception):
    pass


class FilterIterator(object):
    def __init__(self, iterable):
        self.iterable = iterable

    def __iter__(self):
        return self.iterable

    def get(self, **kwargs):
        filtered_list = list(self._filter(**kwargs))
        l = len(filtered_list)
        if l == 0:
            raise ElementNotFound(u'No element was found using {}'.format(kwargs))
        elif l > 1:
            raise MultipleElementsException(u'Multiple elements were found using {}'.format(kwargs))
        return filtered_list[0]

    def filter(self, **kwargs):
        return FilterIterator(self._filter(**kwargs))

    def _filter(self, **kwargs):
        # attrgetter uses dots to perform nested lookups but dots are not allowed in parameters name,
        # so we use dunder instead.
        attr_names = (l.replace('__', '.') for l in kwargs.iterkeys())
        attr_values = kwargs.values()
        getter = attrgetter(*attr_names)

        for obj in self:
            try:
                values = getter(obj)
            except AttributeError:
                continue
            else:
                # attrgetter has a bit inconsistent behavior
                # it return a single value if there was only one kwarg
                # and tuple of values if there were multiple kwargs
                if not isinstance(values, tuple):
                    values = (values, )

            if tuple(attr_values) == values:
                yield obj

    def list(self):
        return list(self.iterable)
