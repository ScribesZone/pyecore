"""
The resource proposes all the concepts that are related to Resource handling.
A Resource represents a model resource and many of them can be contained in a
ResourceSet.
"""
from uuid import uuid4
import urllib.request
from os import path
from collections import ChainMap
from .. import ecore as Ecore

global_registry = {}


class ResourceSet(object):
    def __init__(self):
        self.resources = {}
        self.metamodel_registry = ChainMap({}, global_registry)
        self.resource_factory = dict(ResourceSet.resource_factory)

    def create_resource(self, uri):
        if isinstance(uri, str):
            uri = URI(uri)
        try:
            resource = self.resource_factory[uri.extension](uri)
        except KeyError:
            resource = self.resource_factory['*'](uri)
        self.resources[uri.normalize()] = resource
        resource._resourceset = self
        resource._decoders.insert(0, self)
        return resource

    def remove_resource(self, resource):
        if not resource:
            return
        for key, value in list(self.resources.items()):
            if value is resource:
                del self.resources[key]

    def get_resource(self, uri):
        if isinstance(uri, str):
            uri = URI(uri)
        # We check first if the resource already exists in the ResourceSet
        if uri.normalize() in self.resources:
            return self.resources[uri.normalize()]
        # If not, we create a new resource
        resource = self.create_resource(uri)
        try:
            resource.load()
        except Exception as e:
            self.remove_resource(resource)
            raise e
        return resource

    def can_resolve(self, uri_path, from_resource=None):
        uri_path = Resource.normalize(uri_path)
        fragment = uri_path.split('#')
        if len(fragment) == 2:
            uri_str, fragment = fragment
        else:
            return False
        if uri_str in self.resources:
            return True
        start = from_resource.uri.normalize() if from_resource else '.'
        apath = path.dirname(start)
        uri = URI(path.join(apath, uri_str))
        return uri.normalize() in self.resources

    def resolve(self, uri, from_resource=None):
        upath = Resource.normalize(uri)
        uri_str, fragment = upath.split('#')
        if uri_str in self.resources:
            return Resource._navigate_from(fragment, self.resources[uri_str])
        start = from_resource.uri.normalize() if from_resource else '.'
        apath = path.dirname(start)
        uri = URI(path.join(apath, uri_str))
        epackage = self.resources[uri.normalize()]
        if isinstance(epackage, Resource):
            epackage = epackage.contents[0]
        return Resource._navigate_from(fragment, epackage)


class URI(object):
    _uri_norm = {'http': lambda x: x,
                 'https': lambda x: x,
                 'file': lambda x: path.abspath(x.replace('file://', ''))}

    _uri_split = {'http': '/',
                  'https': '/',
                  'file': path.sep}

    def __init__(self, uri):
        if uri is None:
            raise TypeError('URI cannot be None')
        self._uri = uri
        self._split()
        self.__stream = None

    def _split(self):
        if '://' in self._uri:
            self._protocol, rest = self._uri.split('://', maxsplit=1)
        else:
            self._protocol, rest = None, self._uri
        uri_sep = self._uri_split.get(self._protocol, path.sep)
        self._segments = rest.split(uri_sep)
        self._last_segment = self._segments[-1:][0]
        if '.' in self._last_segment:
            self._extension = self._last_segment.split('.')[-1:][0]
        else:
            self._extension = None

    @property
    def protocol(self):
        return self._protocol

    @property
    def extension(self):
        return self._extension

    @property
    def plain(self):
        return self._uri

    @property
    def segments(self):
        return self._segments

    @property
    def last_segment(self):
        return self._last_segment

    def create_instream(self):
        self.__stream = open(self.plain, 'rb')
        return self.__stream

    def close_stream(self):
        if self.__stream:
            self.__stream.close()

    def create_outstream(self):
        self.__stream = open(self.plain, 'wb')
        return self.__stream

    def normalize(self):
        return self._uri_norm.get(self.protocol, path.abspath)(self._uri)

    def relative_from_me(self, uri):
        normalized = path.dirname(self.normalize())
        other = uri
        if isinstance(uri, URI):
            other = uri.normalize()
        return path.relpath(other, normalized)


class HttpURI(URI):
    def __init__(self, uri):
        super().__init__(uri)

    def create_instream(self):
        self.__stream = urllib.request.urlopen(self.plain)
        return self.__stream

    def create_outstream(self):
        raise NotImplementedError('Cannot create an outstream for HttpURI')


# class StdioURI(URI):
#     def __init__(self):
#         super().__init__('stdio')
#
#     def create_instream(self):
#         self.__stream = sys.stdin.buffer
#         return self.__stream
#
#     def create_outstream(self):
#         self.__stream = sys.stdout.buffer
#         return self.__stream
#
#     def close_stream(self):
#         pass


class MetamodelDecoder(object):
    def split_path(path):
        path = Resource.normalize(path)
        fragment = path.split('#')
        if len(fragment) == 2:
            uri, fragment = fragment
        else:
            uri = None
        return uri, fragment

    def can_resolve(path, registry):
        uri, fragment = MetamodelDecoder.split_path(path)
        return uri in registry

    def resolve(path, registry):
        path = Resource.normalize(path)
        uri, fragment = path.split('#')
        epackage = registry[uri]
        return Resource._navigate_from(fragment, epackage)


class Global_URI_decoder(object):
    def can_resolve(path, from_resource=None):
        return MetamodelDecoder.can_resolve(path, global_registry)

    def resolve(path, from_resource=None):
        return MetamodelDecoder.resolve(path, global_registry)


class LocalMetamodelDecoder(object):
    def can_resolve(path, from_resource=None):
        if from_resource is None or from_resource.resource_set is None:
            return False
        rset = from_resource.resource_set
        return MetamodelDecoder.can_resolve(path, rset.metamodel_registry)

    def resolve(path, from_resource=None):
        rset = from_resource.resource_set
        return MetamodelDecoder.resolve(path, rset.metamodel_registry)


class Resource(object):
    _decoders = [LocalMetamodelDecoder, Global_URI_decoder]

    def __init__(self, uri=None, use_uuid=False):
        self.uuid_dict = {}
        self._use_uuid = use_uuid
        self.prefixes = {}
        self._resourceset = None
        self._uri = uri
        self._decoders = list(Resource._decoders)
        self._contents = []
        self._resolve_mem = {}

    @property
    def uri(self):
        return self._uri

    @property
    def resource_set(self):
        return self._resourceset

    @property
    def contents(self):
        return self._contents

    def resolve(self, fragment, resource=None):
        fragment = self.normalize(fragment)
        if fragment in self._resolve_mem:
            return self._resolve_mem[fragment]
        if self._use_uuid:
            try:
                frag = fragment[1:] if fragment.startswith('#') \
                                    else fragment
                frag = frag[2:] if frag.startswith('//') else frag
                return self.uuid_dict[frag]
            except KeyError:
                pass
        result = None
        for root in self._contents:
            result = self._navigate_from(fragment, root)
            if result:
                self._resolve_mem[fragment] = result
                return result

    def prefix2epackage(self, prefix):
        nsURI = None
        try:
            nsURI = self.prefixes[prefix]
        except KeyError:
            return None
        try:
            return self.resource_set.metamodel_registry[nsURI]
        except Exception:
            return global_registry.get(nsURI)

    def get_metamodel(self, nsuri):
        try:
            if self.resource_set:
                return self.resource_set.metamodel_registry[nsuri]
            else:
                return global_registry[nsuri]
        except KeyError:
            raise KeyError('Unknown metamodel with uri: {0}'.format(nsuri))

    @staticmethod
    def normalize(fragment):
        return fragment.split()[-1:][0] if ' ' in fragment else fragment

    def _is_external(self, path):
        path = self.normalize(path)
        uri, fragment = path.split('#') if '#' in path else (None, path)
        return uri, fragment

    def _get_href_decoder(self, path):
        decoder = next((x for x in self._decoders
                        if x.can_resolve(path, self)), None)
        uri, _ = self._is_external(path)
        if not decoder and uri:
            raise TypeError('Resource "{0}" cannot be resolved'.format(uri))
        return decoder if decoder else self

    @staticmethod
    def _navigate_from(path, start_obj):
        if '#' in path[:1]:
            path = path[1:]
        features = [x for x in path.split('/') if x]
        feat_info = [x.split('.') for x in features]
        obj = start_obj
        annot_content = False
        for feat in feat_info:
            key, index = feat if len(feat) > 1 else (feat[0], None)
            if key.startswith('@'):
                tmp_obj = obj.__getattribute__(key[1:])
                try:
                    obj = tmp_obj[int(index)] if index else tmp_obj
                except IndexError:
                    raise ValueError('Index in path is not the collection,'
                                     ' broken proxy?')
            elif key.startswith('%'):
                key = key[1:-1]
                obj = obj.eAnnotations.select(lambda x: x.source == key)[0]
                annot_content = True
            elif annot_content:
                annot_content = False
                obj = obj.contents.select(lambda x: x.name == key)[0]
            else:
                try:
                    subpack = next((p for p in obj.eSubpackages
                                    if p.name == key),
                                   None)
                    if subpack:
                        obj = subpack
                        continue
                except Exception:
                    pass
                try:
                    obj = obj.getEClassifier(key)
                except AttributeError:
                    obj = next((c for c in obj.eContents
                               if hasattr(c, 'name') and c.name == key),
                               None)
        return obj

    # Refactor me
    def _build_path_from(self, obj):
        if isinstance(obj, type):
            obj = obj.eClass

        if isinstance(obj, Ecore.EProxy) and not obj._resolved:
            return (obj._proxy_path, True)

        if obj.eResource != self:
            eclass = obj.eClass
            prefix = eclass.ePackage.nsPrefix
            _type = '{0}:{1}'.format(prefix, eclass.name)
            uri_fragment = obj.eURIFragment()
            crossref = False
            if obj.eResource:
                uri = self.uri.relative_from_me(obj.eResource.uri)
                crossref = True
            else:
                uri = ''
                root = obj.eRoot()
                mm_registry = None
                if self.resource_set:
                    mm_registry = self.resource_set.metamodel_registry
                else:
                    mm_registry = global_registry
                for reguri, value in mm_registry.items():
                    if value is root:
                        uri = reguri
                        break
                else:
                    return '', False
            if not uri_fragment.startswith('#'):
                uri_fragment = '#' + uri_fragment
            if crossref:
                return ('{0}{1}'.format(uri, uri_fragment), True)
            else:
                return ('{0} {1}{2}'.format(_type, uri, uri_fragment), False)
        if self._use_uuid:
            self._assign_uuid(obj)
            return (obj._xmiid, False)
        return (obj.eURIFragment(), False)

    def _assign_uuid(self, obj):
        # sets an uuid if the resource should deal with
        # and obj has none yet (addition to the resource for example)
        if not obj._xmiid:
            uuid = str(uuid4())
            self.uuid_dict[uuid] = obj
            obj._xmiid = uuid

    def append(self, root):
        if not isinstance(root, Ecore.EObject):
            raise ValueError('The resource requires an EObject type, '
                             'but received {0} instead.'.format(type(root)))
        self._contents.append(root)
        root._eresource = self
        for eobject in root.eAllContents():
            eobject._eresource = self

    def open_out_stream(self, other=None):
        if other and not isinstance(other, URI):
            other = URI(other)
        return (other.create_outstream() if other
                else self.uri.create_outstream())

    def extend(self, values):
        [self.append(x) for x in values]
