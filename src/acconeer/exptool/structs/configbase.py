import enum
import inspect
import json
import os
from copy import copy
from weakref import WeakKeyDictionary

import attr
import numpy as np


class Category(enum.Enum):
    BASIC = enum.auto()
    ADVANCED = enum.auto()


class Severity(enum.IntEnum):
    ERROR = enum.auto()
    WARNING = enum.auto()
    INFO = enum.auto()


@attr.s
class Alert:
    param = attr.ib()
    msg = attr.ib()


class Error(Alert):
    severity = Severity.ERROR


class Warning(Alert):
    severity = Severity.WARNING


class Info(Alert):
    severity = Severity.INFO


class Parameter:
    def __init__(self, **kwargs):
        self.label = kwargs.pop("label")
        self.is_live_updateable = kwargs.pop("updateable", False)
        self.does_dump = kwargs.pop("does_dump", False)
        self.category = kwargs.pop("category", Category.BASIC)
        self.order = kwargs.pop("order", -1)
        self.help = kwargs.pop("help", None)
        self.visible = kwargs.pop("visible", True)

        self._pidget_class = kwargs.pop("_pidget_class", None)

        # don't care if unused
        kwargs.pop("default_value", None)

        if kwargs:
            a_key = next(iter(kwargs.keys()))
            raise TypeError("Got unexpected keyword argument ({})".format(a_key))

        if not self.visible:
            self._pidget_class = None
        elif self._pidget_class is None:
            self.visible = False

        self.pidgets = WeakKeyDictionary()

        doc = self.generate_doc()
        if doc:
            self.__doc__ = doc.strip()

    def update_pidget(self, obj, alerts=None):
        pidget = self.get_pidget(obj)
        if pidget is not None:
            pidget.update(alerts)

    def get_pidget(self, obj):
        return self.pidgets.get(obj)

    def create_pidget(self, obj):
        from acconeer.exptool.structs import qtpidgets

        if self._pidget_class is None:
            return None

        if obj not in self.pidgets:
            pidget_class = getattr(qtpidgets, self._pidget_class)
            self.pidgets[obj] = pidget_class(self, obj)

        return self.pidgets[obj]

    def pidget_event_handler(self, *args, **kwargs):
        pass

    def dump(self):
        pass

    def load(self):
        pass

    def generate_doc(self):
        if self.help is None:
            return None

        return inspect.cleandoc(self.help)


class ConstantParameter(Parameter):
    def __init__(self, **kwargs):
        self.value = kwargs.pop("value")
        super().__init__(**kwargs)

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self

        return self.value

    def __set__(self, obj, value):
        raise AttributeError("Unsettable parameter")


class ValueParameter(Parameter):
    def __init__(self, **kwargs):
        self.default_value = kwargs.pop("default_value")
        self.is_optional = kwargs.pop("optional", False)

        if self.is_optional:
            self.optional_label = kwargs.pop("optional_label", "Set")

            if self.default_value is None:
                self.optional_default_set_value = kwargs.pop("optional_default_set_value")
            else:
                self.optional_default_set_value = self.default_value

        kwargs.setdefault("does_dump", True)

        self.values = WeakKeyDictionary()

        super().__init__(**kwargs)

        self.default_value = self.sanitize(self.default_value)

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self

        return copy(self.values.get(obj, default=self.default_value))

    def __set__(self, obj, value):
        value = self.sanitize(value)
        self.values[obj] = value

    def __delete__(self, obj):
        self.values.pop(obj, None)

    def pidget_event_handler(self, obj, val):
        self.__set__(obj, val)  # might raise an exception

        obj._parameter_event_handler()

    def sanitize(self, value):
        if not (self.is_optional and value is None):
            value = self._sanitize(value)

        return value

    def _sanitize(self, value):
        return value

    def dump(self, obj):
        return self.__get__(obj)

    def load(self, obj, value):
        self.__set__(obj, value)

    def generate_doc(self):
        s = ""

        s_help = super().generate_doc()
        if s_help:
            s += s_help
            s += "\n\n"

        type_str = getattr(self, "type_str", None)
        if type_str:
            s += "| Type: {}\n".format(type_str)

        unit = getattr(self, "unit", None)
        if unit:
            s += "| Unit: {}\n".format(unit)

        s += "| Default value: {}\n".format(self.default_value)

        return s


class BoolParameter(ValueParameter):
    type_str = "bool"

    def __init__(self, **kwargs):
        kwargs.setdefault("_pidget_class", "BoolCheckboxPidget")

        super().__init__(**kwargs)

    def _sanitize(self, value):
        return bool(value)


class EnumParameter(ValueParameter):
    def __init__(self, **kwargs):
        self.enum = kwargs.pop("enum")

        kwargs.setdefault("_pidget_class", "ComboBoxPidget")

        super().__init__(**kwargs)

    def dump(self, obj):
        return self.__get__(obj).name

    def load(self, obj, value):
        value = self.enum[value]
        self.__set__(obj, value)


class NumberParameter(ValueParameter):
    def __init__(self, **kwargs):
        self.unit = kwargs.pop("unit", None)
        self.limits = kwargs.pop("limits", None)

        if self.limits is not None:
            assert isinstance(self.limits, (tuple, list))
            assert len(self.limits) == 2

        super().__init__(**kwargs)


class IntParameter(NumberParameter):
    type_str = "int"

    def __init__(self, **kwargs):
        self.step = kwargs.pop("step", 1)

        kwargs.setdefault("_pidget_class", "IntSpinBoxPidget")

        super().__init__(**kwargs)

    def _sanitize(self, value):
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("Not an integer")

        try:
            value = int(value)
        except ValueError:
            raise ValueError("Not a valid integer")

        if self.limits is not None:
            lower, upper = self.limits

            if lower is not None and value < lower:
                raise ValueError("Given value is too low")
            if upper is not None and value > upper:
                raise ValueError("Given value is too high")

        return value


class FloatParameter(NumberParameter):
    type_str = "float"

    def __init__(self, **kwargs):
        self.decimals = kwargs.pop("decimals", 2)
        self.logscale = kwargs.pop("logscale", False)

        limits = kwargs.get("limits", None)
        if limits is not None and not any([lim is None for lim in limits]):
            kwargs.setdefault("_pidget_class", "FloatSpinBoxAndSliderPidget")
        else:
            kwargs.setdefault("_pidget_class", "FloatSpinBoxPidget")

        super().__init__(**kwargs)

        if self.logscale:
            assert self.limits is not None
            assert self.limits[1] > self.limits[0] > 0

    def _sanitize(self, value):
        try:
            value = float(value)
        except ValueError:
            raise ValueError("Not a valid number")

        value = round(value, self.decimals)

        if self.limits is not None:
            lower, upper = self.limits

            if lower is not None and value < lower:
                raise ValueError("Given value is too low")
            if upper is not None and value > upper:
                raise ValueError("Given value is too high")

        return value


class FloatRangeParameter(FloatParameter):
    def __init__(self, **kwargs):
        kwargs.setdefault("_pidget_class", "FloatRangeSpinBoxesPidget")

        super().__init__(**kwargs)

    def _sanitize(self, arg):
        try:
            values = list(arg)
        except (ValueError, TypeError):
            raise ValueError("Not a valid range")

        if len(values) != 2:
            raise ValueError("Given range does not have two values")

        for i in range(2):
            values[i] = super()._sanitize(values[i])

        if values[0] > values[1]:
            raise ValueError("Invalid range")

        return np.array(values)

    def dump(self, obj):
        return list(self.__get__(obj))


class SensorParameter(ValueParameter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _sanitize(self, arg):
        if isinstance(arg, int):
            arg = [arg]
        elif isinstance(arg, list) and all([isinstance(e, int) for e in arg]):
            arg = copy(arg)
        else:
            raise ValueError("sensor(s) must be an int or a list of ints")

        return arg


class ClassParameter(Parameter):
    def __init__(self, **kwargs):
        self.objtype = kwargs.pop("objtype")

        self.instances = WeakKeyDictionary()

        super().__init__(**kwargs)

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self

        if obj not in self.instances:
            self.instances[obj] = self.objtype(self, obj)

        return self.instances[obj]

    def __set__(self, obj, value):
        raise AttributeError("Unsettable parameter")

    def __delete__(self, obj):
        self.instances.pop(obj, None)


def get_virtual_parameter_class(base_class):
    assert issubclass(base_class, ValueParameter)

    class VirtualParameter(base_class):
        def __init__(self, **kwargs):
            self.get_fun = kwargs.pop("get_fun")
            self.set_fun = kwargs.pop("set_fun", None)

            kwargs.setdefault("does_dump", False)

            kwargs.setdefault("default_value", None)

            super().__init__(**kwargs)

        def __get__(self, obj, objtype=None):
            if obj is None:
                return self

            return self.get_fun(obj)

        def __set__(self, obj, value):
            if self.set_fun is None:
                raise AttributeError("Unsettable parameter")

            self.set_fun(obj, value)

        def __delete__(self, obj):
            pass

        def _sanitize(self, value):
            pass

        def generate_doc(self):
            return None

    return VirtualParameter


class Config:
    class State(enum.Enum):
        UNLOADED = enum.auto()
        LOADED = enum.auto()
        LOADED_READONLY = enum.auto()
        LIVE = enum.auto()

    VERSION = None

    _event_handlers = None
    __state = None

    def __init__(self):
        self._event_handlers = set()
        self.__state = Config.State.UNLOADED

    def __str__(self):
        d = {k: p.dump(self) for k, p in self._get_keys_and_params() if p.does_dump}
        s = self.__class__.__name__
        s += "".join(["\n  {:.<35} {}".format(a + " ", v) for (a, v) in d.items()])
        return s

    def _loads(self, s):
        d = json.loads(s)

        version = d.pop("VERSION", None)
        if version != self.VERSION:
            raise ValueError("Configuration version mismatch")

        params = dict(self._get_keys_and_params())
        for k, v in d.items():
            params[k].load(self, v)

        self._update_pidgets()

    def _dumps(self):
        d = {k: p.dump(self) for k, p in self._get_keys_and_params() if p.does_dump}

        if self.VERSION is not None:
            d["VERSION"] = self.VERSION

        return json.dumps(d)

    def _reset(self):
        params = self._get_params()
        for param in params:
            param.__delete__(self)
            param.update_pidget(self)

        self._parameter_event_handler()

    def _create_pidgets(self):
        params = self._get_params()
        pidgets = [param.create_pidget(self) for param in params]
        return pidgets

    def _update_pidgets(self, additional_alerts=[]):
        alerts = self.check()
        if alerts is None:
            alerts = []
        alerts.extend(additional_alerts)

        for key, param in self._get_keys_and_params():
            param_alerts = [a for a in alerts if a.param in [key, param]]
            param.update_pidget(self, param_alerts)

        return alerts

    def _parameter_event_handler(self):
        for event_handler in self._event_handlers:
            event_handler(self)

    def _get_keys_and_params(self):
        keys = dir(self)
        attrs = [getattr(type(self), key, None) for key in keys]
        z = [(k, a) for k, a in zip(keys, attrs) if isinstance(a, Parameter)]
        return sorted(z, key=lambda t: t[1].order)

    def _get_params(self):
        return [a for k, a in self._get_keys_and_params()]

    @property
    def _state(self):
        return self.__state

    @_state.setter
    def _state(self, state):
        state_changed = self.__state != state
        self.__state = state
        if state_changed:
            self._update_pidgets()

    def check(self):
        return []

    def __setattr__(self, name, value):
        if hasattr(self, name):
            object.__setattr__(self, name, value)
        else:
            fmt = "'{}' object has no attribute '{}'"
            raise AttributeError(fmt.format(self.__class__.__name__, name))


class SensorConfig(Config):
    pass


class ProcessingConfig(Config):
    pass


class ReferenceData:
    def __init__(self, param, parent_instance, buffer_size=50):
        self._param = param
        self._parent_instance = parent_instance

        self._buffer_size = buffer_size  # TODO: make settable from parameter

        self._buffered_data = None
        self._loaded_data = None
        self._use = True
        self._source = None
        self._source_file = None
        self._error = None

    @property
    def buffer_size(self):
        return self._buffer_size

    @buffer_size.setter
    def buffer_size(self, value):
        self._buffer_size = value
        self.__notify()

    @property
    def buffered_data(self):
        return self._buffered_data

    @buffered_data.setter
    def buffered_data(self, value):
        self._buffered_data = value
        self.__notify()

    @property
    def loaded_data(self):
        return self._loaded_data

    @loaded_data.setter
    def loaded_data(self, value):
        self._loaded_data = value
        self.__notify()

    @property
    def use(self):
        return self._use

    @use.setter
    def use(self, value):
        self._use = value
        self.__notify()

    @property
    def source(self):
        return self._source

    @source.setter
    def source(self, value):
        self._source = value
        self.__notify()

    @property
    def source_file(self):
        return self._source_file

    @source_file.setter
    def source_file(self, value):
        self._source_file = value
        self.__notify()

    @property
    def error(self):
        return self._error

    @error.setter
    def error(self, value):
        self._error = value
        self.__notify()

    @property
    def is_loaded(self):
        return self.loaded_data is not None

    @property
    def has_buffered(self):
        return self.buffered_data is not None

    def load_buffered(self):
        self.loaded_data = self.buffered_data
        self.use = True
        self.source = "buffer"
        self.source_file = None

    def unload(self):
        self.loaded_data = None
        self.source = None
        self.source_file = None
        self.error = None

    def load_from_file(self, filename):
        self.loaded_data = np.load(filename, allow_pickle=True)
        self.use = True
        self.source = "file"
        self.source_file = os.path.basename(filename)

    def save_to_file(self, filename):
        np.save(filename, self.loaded_data, allow_pickle=True)
        self.source = "file"
        self.source_file = os.path.basename(filename)

    def __notify(self):
        self._parent_instance._parameter_event_handler()


class ReferenceDataParameter(ClassParameter):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", "Background")
        kwargs.setdefault("_pidget_class", "ReferenceDataPidget")
        kwargs.setdefault("objtype", ReferenceData)
        kwargs.setdefault("updateable", True)

        super().__init__(**kwargs)
