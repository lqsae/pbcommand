""" Commandline Parser for Tools. Supports Tool Contracts

# Author: Michael Kocher
"""
import abc
import os
import logging
import argparse
import functools
import warnings
import re

import jsonschema

from .common import SymbolTypes, TaskOptionTypes
from pbcommand.common_options import (add_base_options_with_emit_tool_contract,
                                      add_subcomponent_versions_option)
from .tool_contract import (ToolDriver,
                            InputFileType, OutputFileType,
                            ToolContract, ToolContractTask,
                            ScatterToolContractTask, GatherToolContractTask)

log = logging.getLogger(__name__)

__version__ = "0.1.1"

__all__ = ["PbParser",
           "PyParser",
           "ToolContractParser",
           "get_pbparser",
           "get_scatter_pbparser",
           "get_gather_pbparser"]

RX_TASK_ID = re.compile(r'^([A-z0-9_]*)\.tasks\.([A-z0-9_]*)$')
RX_TASK_OPTION_ID = re.compile(r'^([A-z0-9_]*)\.task_options\.([A-z0-9_\.]*)')


def _to_file_type(format_):
    return "pacbio.file_types.{x}".format(x=format_)


# FIXME obsolete
class JsonSchemaTypes(object):
    # array is a native type, but not supported
    BOOL = "boolean"
    INT = "integer"
    NUM = "number"
    STR = "string"
    NULL = "null"
    OBJ = "object"

    @staticmethod
    def from_task_option_type(t):
        return {TaskOptionTypes.INT: JsonSchemaTypes.INT,
                TaskOptionTypes.FLOAT: JsonSchemaTypes.NUM,
                TaskOptionTypes.BOOL: JsonSchemaTypes.BOOL,
                TaskOptionTypes.STR: JsonSchemaTypes.STR,
                TaskOptionTypes.CHOICE: JsonSchemaTypes.STR,
                TaskOptionTypes.CHOICE_INT: JsonSchemaTypes.INT,
                TaskOptionTypes.CHOICE_FLOAT: JsonSchemaTypes.NUM}.get(t)


def _validate_file(label, path):
    if os.path.exists(path):
        return os.path.abspath(path)
    else:
        raise IOError("Unable to find '{x}' file '{p}'".format(x=label, p=path))


def _validate_option_or_cast(dtype, dvalue):
    if isinstance(dvalue, dtype):
        return dvalue
    else:
        # XXX this is almost always going to be the case...
        if isinstance(dvalue, basestring):
            try:
                return dtype(dvalue)
            except ValueError as e:
                pass
        raise TypeError("Invalid option type: '{a}' provided, '{e}' "
                        "expected".format(a=dvalue, e=dtype))


def _validate_option(dtype, dvalue):
    if isinstance(dvalue, dtype):
        return dvalue
    else:
        raise TypeError("Invalid option type: '{a}' provided, '{e}' "
                        "expected".format(a=dvalue, e=dtype))


def _validate_id(prog, idtype, tid):
    if prog.match(tid):
        return tid
    else:
        raise ValueError("Invalid format {t}: '{i}' {p}".format(t=idtype, i=tid, p=repr(prog.pattern)))

_validate_task_id = functools.partial(_validate_id, RX_TASK_ID, 'task id')
_validate_task_option_id = functools.partial(_validate_id, RX_TASK_OPTION_ID,
                                             'task option id')


def to_opt_id(namespace, s):
    return ".".join([namespace, "options", s])


def validate_value(schema, v):
    return jsonschema.validate(v, schema)


def is_valid(schema, v):
    """Returns a bool if the schema is valid"""
    try:
        validate_value(schema, v)
        return True
    except jsonschema.ValidationError:
        pass
    return False


# FIXME deprecated, remove
def validate_schema(f):
    """Deco for validate the returned jsonschema against Draft 4 of the spec"""
    def w(*args, **kwargs):
        schema = f(*args, **kwargs)
        _ = jsonschema.Draft4Validator(schema)
        return schema
    return w


# TODO(mkocher):
# This might be better as a base class of PacBioOption without "choice", then
# subclass to add choice field/property. This will enable future types of
# RangeNumberOption which would add min_value, and max_value for int and float.
class PacBioOption(object):
    """
    Base class for all task and pipeline configurable options including
    metadata.  This is represented in JSON as, for example:

        {
            "id": "pbcommand.task_options.alpha",
            "name": "Alpha",
            "description": "Floating-point option",
            "optionTypeId": "pbsmrtpipe.option_types.float",
            "default": 1.234
        }

    with an optional "choices" field for option types that enumerate a list of
    allowed values.  The type is passed explicitly using the IDs included in
    pbcommand.models.common.TaskOptionTypes (as well as Scala and TypeScript
    code).  The default value must be non-null, although empty strings are
    allowed for string types.

    :param option_id: equivalent to "id" field in JSON, a fully-qualified unique
                      identifier (<TASK>.task_options.<ID>).
    :param name: display name/label/title
    :param default: default value, must be appropriate for type (non-null)
    :param description: help text
    :param pb_option_type: equivalent to "optionTypeId" in JSON, one of the
                           pre-defined task option type strings
    :param choices: optional, specifies that this is one of the choice option types
    """
    def __init__(self, option_id, name, default, description, pb_option_type,
                 choices=None):
        if not pb_option_type in TaskOptionTypes.ALL():
            raise ValueError("Invalid optionTypeId '{i}'".format(i=pb_option_type))
        self.option_id = option_id
        self.name = name
        self.default = default
        self.description = description
        self.pb_option_type = pb_option_type
        self.choices = choices

    def __repr__(self):
        _d = dict(i=self.option_id,
                  n=self.name,
                  v=self.default,
                  k=self.__class__.__name__,
                  t=self.pb_option_type)
        return "<{k} {i} name: {n} default: {v} {t} >".format(**_d)

    @staticmethod
    def from_dict(d):
        if "pb_option" in d:
            return PacBioOption.from_jsonschema(d)
        return PacBioOption(d['id'], d['name'], d['default'], d['description'], d['optionTypeId'], d.get("choices", None))

    def to_dict(self):
        return dict(id=self.option_id,
                    name=self.name,
                    default=self.default,
                    description=self.description,
                    optionTypeId=self.pb_option_type,
                    choices=self.choices)

    # FIXME obsolete, to be removed
    @staticmethod
    def from_jsonschema(opt_jschema_d):
        """
        Create a new instance from the old-style dictionary
        """
        warnings.warn("This is obsolete and will disappear soon", DeprecationWarning)
        types_d = {JsonSchemaTypes.BOOL: TaskOptionTypes.BOOL,
                   JsonSchemaTypes.INT: TaskOptionTypes.INT,
                   JsonSchemaTypes.STR: TaskOptionTypes.STR,
                   JsonSchemaTypes.NUM: TaskOptionTypes.FLOAT}
        choice_types_d = {JsonSchemaTypes.STR: TaskOptionTypes.CHOICE,
                          JsonSchemaTypes.INT: TaskOptionTypes.CHOICE_INT,
                          JsonSchemaTypes.NUM: TaskOptionTypes.CHOICE_FLOAT}

        opt_id = opt_jschema_d['pb_option']['option_id']
        name = opt_jschema_d['pb_option']['name']
        default = opt_jschema_d['pb_option']['default']
        desc = opt_jschema_d['pb_option']['description']
        choices = opt_jschema_d['pb_option'].get("choices", None)
        jschema_type = opt_jschema_d['pb_option']['type']
        pb_option_type_id = types_d[jschema_type]
        if choices is not None:
            pb_option_type_id = choice_types_d[jschema_type]
        return PacBioOption(opt_id, name, default, desc, pb_option_type_id,
                            choices)


def to_option(option_id, type_id, display_name, description, default_value, choices=None):
    """
    Simple util factory method
    :param dtype_or_dtypes: single data type or list of data types
    :param option_id: globally unique task option id. Must begin with
    'pbsmrtpipe.task_options.'
    :param display_name: display name of task options
    :param description: Short description of the task options
    :param required: Is the option required.
    """
    # annoying that you can't specify a tuple
    dtype_or_dtypes = JsonSchemaTypes.from_task_option_type(type_id)
    if isinstance(dtype_or_dtypes, tuple):
        dtype_or_dtypes = list(dtype_or_dtypes)

    _validate_task_option_id(option_id)

    # Steps toward moving away from JSON schema as the format, but reuse
    # the jsonschema defined types. Only non-union types are supported.
    # FIXME use PacBioOption model
    pbd = {"option_id": option_id,
           "type": dtype_or_dtypes,
           "optionTypeId": type_id,
           "default": default_value,
           "name": display_name,
           "description": description,
           "choices": choices}

    d = {'$schema': "http://json-schema.org/draft-04/schema#",
         'type': 'object',
         'title': "JSON Schema for {o}".format(o=option_id),
         'properties': {option_id: {'description': description,
                                    'title': display_name,
                                    'type': dtype_or_dtypes},
                        },
         "pb_option": pbd
         }

    d['required'] = [option_id]
    d['properties'][option_id]['default'] = default_value
    return d


class PbParserBase(object):

    __metaclass__ = abc.ABCMeta

    def __init__(self, tool_id, version, name, description):
        self.tool_id = _validate_task_id(tool_id)
        self.version = version
        self.description = description
        self.name = name

    def __repr__(self):
        _d = dict(k=self.__class__.__name__, i=self.tool_id, v=self.version)
        return "<{k} id:{i} {v} >".format(**_d)

    @abc.abstractmethod
    def add_input_file_type(self, file_type, file_id, name, description):
        """
        Add a mandatory input file parameter.  On the Python argparse side,
        this will be a positional argument.

        :param file_type: file type ID from pbcommand.models.common, e.g.
                          FileTypes.DS_REF
        :param file_id: parameter name, mainly used on argparse side
        :param name: plain-English name
        :param description: help string
        """
        raise NotImplementedError

    @abc.abstractmethod
    def add_output_file_type(self, file_type, file_id, name, description, default_name):
        """
        Add a mandatory output file parameter.  On the Python argparse side,
        this will be a positional argument.

        :param file_type: file type ID from pbcommand.models.common, e.g.
                          FileTypes.DS_REF
        :param file_id: parameter name, mainly used on argparse side
        :param name: plain-English name
        :param description: help string
        :param default_name: tuple of form (base_name, extension) specifying
                             the default output file name
        """
        raise NotImplementedError

    @abc.abstractmethod
    def add_int(self, option_id, option_str, default, name, description):
        """
        Add an optional integer keyword argument (e.g. "--n=10" or "--n 10" on
        the command line).

        :param option_id: fully-qualified option name used in tool contract
                          layer, of form "pbcommand.task_options.my_option"
        :param option_str: shorter parameter name, mainly used in Python
                           argparse layer, but *without* leading dashes
        :param default: default value (must be an actual integer, not None)
        :param name: plain-English name
        :param description: help string
        """
        raise NotImplementedError

    @abc.abstractmethod
    def add_float(self, option_id, option_str, default, name, description):
        """
        Add an optional float keyword argument (e.g. "--n=10" or "--n 10" on
        the command line).

        :param option_id: fully-qualified option name used in tool contract
                          layer, of form "pbcommand.task_options.my_option"
        :param option_str: shorter parameter name, mainly used in Python
                           argparse layer, but *without* leading dashes
        :param default: default value (must be an actual number, not None)
        :param name: plain-English name
        :param description: help string
        """
        raise NotImplementedError

    @abc.abstractmethod
    def add_str(self, option_id, option_str, default, name, description):
        """
        Add a generic keyword argument whose type is a string.

        :param option_id: fully-qualified option name used in tool contract
                          layer, of form "pbcommand.task_options.my_option"
        :param option_str: shorter parameter name, mainly used in Python
                           argparse layer, but *without* leading dashes
        :param default: default value (can be blank, but not None)
        :param name: plain-English name
        :param description: help string
        """
        raise NotImplementedError

    @abc.abstractmethod
    def add_boolean(self, option_id, option_str, default, name, description):
        """
        Add a boolean option.

        :param option_id: fully-qualified option name used in tool contract
                          layer, of form "pbcommand.task_options.my_option"
        :param option_str: shorter parameter name, mainly used in Python
                           argparse layer, but *without* leading dashes
        :param default: specifies the boolean value of this option **if the
                        argument was supplied**, i.e. on the argparse layer,
                        default=True is equivalent to action="store_true"
        :param name: plain-English name
        :param description: help string
        """
        raise NotImplementedError

    @abc.abstractmethod
    def add_choice_str(self, option_id, option_str, name, description, default=None):
        """
        Add a generic enumerated argument whose type is a string.

        :param option_id: fully-qualified option name used in tool contract
                          layer, of form "pbcommand.task_options.my_option"
        :param option_str: shorter parameter name, mainly used in Python
                           argparse layer, but *without* leading dashes
        :param choices: allowed values
        :param name: plain-English name
        :param description: help string
        :param default: default value (if None, will use first choice)
        """
        raise NotImplementedError

    @abc.abstractmethod
    def add_choice_int(self, option_id, option_str, name, description, default=None):
        """
        Add a generic enumerated argument whose type is an integer.

        :param option_id: fully-qualified option name used in tool contract
                          layer, of form "pbcommand.task_options.my_option"
        :param option_str: shorter parameter name, mainly used in Python
                           argparse layer, but *without* leading dashes
        :param choices: allowed values
        :param name: plain-English name
        :param description: help string
        :param default: default value (if None, will use first choice)
        """
        raise NotImplementedError

    @abc.abstractmethod
    def add_choice_float(self, option_id, option_str, name, description, default=None):
        """
        Add a generic enumerated argument whose type is a float.

        :param option_id: fully-qualified option name used in tool contract
                          layer, of form "pbcommand.task_options.my_option"
        :param option_str: shorter parameter name, mainly used in Python
                           argparse layer, but *without* leading dashes
        :param choices: allowed values
        :param name: plain-English name
        :param description: help string
        :param default: default value (if None, will use first choice)
        """
        raise NotImplementedError

_validate_argparse_int = functools.partial(_validate_option_or_cast, int)
_validate_argparse_float = functools.partial(_validate_option_or_cast, float)
_validate_argparse_bool = functools.partial(_validate_option_or_cast, bool)
_validate_argparse_str = functools.partial(_validate_option_or_cast, str)


class PyParser(PbParserBase):
    """PbParser backed that supports argparse"""

    def __init__(self, tool_id, version, name, description, subcomponents=()):
        super(PyParser, self).__init__(tool_id, version, name, description)
        self.parser = argparse.ArgumentParser(#version=version,
                                              description=description,
                                              formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                                              add_help=True)
        self.parser.version = version
        self.parser.add_argument('--version',
                                 action="version",
                                 help="show program's version number and exit")

        if subcomponents:
            add_subcomponent_versions_option(self.parser, subcomponents)

    def add_input_file_type(self, file_type, file_id, name, description):
        # this will propagate up the label to the exception
        vfunc = functools.partial(_validate_file, file_id)
        self.parser.add_argument(file_id, type=vfunc, help=description)

    def add_output_file_type(self, file_type, file_id, name, description, default_name):
        self.parser.add_argument(file_id, type=str, help=description)

    def add_int(self, option_id, option_str, default, name, description):
        # FIXME Need to better define and validate option_str
        opt = "--" + option_str
        self.parser.add_argument(opt, type=_validate_argparse_int,
                                 help=description,
                                 default=_validate_argparse_int(default))

    def add_float(self, option_id, option_str, default, name, description):
        if isinstance(default, int):
            default = float(default)
        opt = "--" + option_str
        self.parser.add_argument(opt, type=_validate_argparse_float,
                                 help=description,
                                 default=_validate_argparse_float(default))

    def add_str(self, option_id, option_str, default, name, description):
        # Fixme
        opt = "--" + option_str
        self.parser.add_argument(opt, type=_validate_argparse_str,
                                 help=description,
                                 default=_validate_argparse_str(default))

    def add_boolean(self, option_id, option_str, default, name, description):
        """
        Note, the default value is set by NOT setting the option.

        Example, if you have option_str of --my-option with a default value of True,
        if --my-option is NOT provided, the value is True, if the --my-option
        is provided, then the value is false.

        """
        d = {True: "store_true", False: "store_false"}
        opt = '--' + option_str
        self.parser.add_argument(opt, action=d[_validate_argparse_bool(not default)],
                                 help=description)

    def _add_choice_base(self, opt_type, option_id, option_str, choices, name,
                         description, default=None):
        if default is None:
            default = choices[0]
        opt = '--' + option_str
        self.parser.add_argument(opt, action="store", choices=choices,
                                 type=opt_type,
                                 help=description, default=default)

    def add_choice_str(self, option_id, option_str, choices, name, description,
                       default=None):
        return self._add_choice_base(str, option_id, option_str, choices, name, description, default)

    def add_choice_int(self, option_id, option_str, choices, name, description,
                       default=None):
        return self._add_choice_base(int, option_id, option_str, choices, name, description, default)

    def add_choice_float(self, option_id, option_str, choices, name, description,
                         default=None):
        return self._add_choice_base(float, option_id, option_str, choices, name, description, default)


class ToolContractParser(PbParserBase):
    """Parser to support Emitting and running ToolContracts"""

    def __init__(self, tool_id, version, name, description, task_type, driver, nproc_symbol,
                 resource_types):
        """Keeps the required elements for creating an instance of a
        ToolContract"""
        super(ToolContractParser, self).__init__(tool_id, version, name, description)
        self.input_types = []
        self.output_types = []
        self.options = []
        self.driver = driver
        self.name = name
        self.nproc_symbol = nproc_symbol
        self.resource_types = resource_types
        self.task_type = task_type

    def add_input_file_type(self, file_type, file_id, name, description):
        x = InputFileType(file_type.file_type_id, file_id, name, description)
        self.input_types.append(x)

    def add_output_file_type(self, file_type, file_id, name, description, default_name):
        x = OutputFileType(file_type.file_type_id, file_id, name, description, default_name)
        self.output_types.append(x)

    def add_int(self, option_id, option_str, default, name, description):
        self.options.append(to_option(option_id,
                                      TaskOptionTypes.INT, name, description,
                                      _validate_option(int, default)))

    def add_float(self, option_id, option_str, default, name, description):
        if isinstance(default, int):
            default = float(default)
        self.options.append(to_option(option_id,
                                      TaskOptionTypes.FLOAT, name, description,
                                      _validate_option(float, default)))

    def add_str(self, option_id, option_str, default, name, description):
        self.options.append(to_option(option_id,
                                      TaskOptionTypes.STR, name, description,
                                      _validate_option(str, default)))

    def add_boolean(self, option_id, option_str, default, name, description):
        self.options.append(to_option(option_id,
                                      TaskOptionTypes.BOOL, name, description,
                                      _validate_option(bool, default)))

    def add_choice_str(self, option_id, option_str, choices, name, description,
                       default=None):
        if default is None:
            default = choices[0]
        self.options.append(to_option(option_id,
                                      TaskOptionTypes.STR, name, description,
                                      _validate_option(str, default),
                                      choices))
    def add_choice_int(self, option_id, option_str, choices, name, description,
                       default=None):
        if default is None:
            default = choices[0]
        self.options.append(to_option(option_id,
                                      TaskOptionTypes.CHOICE_INT, name, description,
                                      _validate_option(int, default),
                                      choices))

    def add_choice_float(self, option_id, option_str, choices, name, description,
                         default=None):
        if default is None:
            default = choices[0]
        self.options.append(to_option(option_id,
                                      TaskOptionTypes.CHOICE_FLOAT, name, description,
                                      _validate_option(float, default),
                                      choices))

    def to_tool_contract(self):
        # Not a well formed tool contract, must have at least one input and
        # one output
        if not self.input_types and not self.output_types:
            raise ValueError("Malformed tool contract inputs")

        task = ToolContractTask(self.tool_id,
                                self.name,
                                self.description,
                                self.version,
                                self.task_type,
                                self.input_types,
                                self.output_types,
                                self.options,
                                self.nproc_symbol,
                                self.resource_types)
        tc = ToolContract(task, self.driver)
        # this should just return TC, not tc.to_dict()
        return tc


class ScatterToolContractParser(ToolContractParser):

    def __init__(self, tool_id, version, name, description, task_type, driver, nproc_symbol,
                 resource_types, chunk_keys, nchunks):
        super(ScatterToolContractParser, self).__init__(tool_id, version, name, description, task_type, driver,
                                                        nproc_symbol, resource_types)
        self.chunk_keys = chunk_keys
        self.nchunks = nchunks

    def to_tool_contract(self):
        task = ScatterToolContractTask(self.tool_id,
                                       self.name,
                                       self.description,
                                       self.version,
                                       self.task_type,
                                       self.input_types,
                                       self.output_types,
                                       self.options,
                                       self.nproc_symbol,
                                       self.resource_types,
                                       self.chunk_keys,
                                       self.nchunks)
        tc = ToolContract(task, self.driver)
        return tc


class GatherToolContractParser(ToolContractParser):

    def to_tool_contract(self):
        task = GatherToolContractTask(self.tool_id,
                                      self.name,
                                      self.description,
                                      self.version,
                                      self.task_type,
                                      self.input_types,
                                      self.output_types,
                                      self.options,
                                      self.nproc_symbol,
                                      self.resource_types)
        tc = ToolContract(task, self.driver)
        return tc


class PbParser(PbParserBase):
    """
    Wrapper class for managing separate tool contract and argument parsers
    (stored as tool_contract_parser and arg_parser attributes respectively).
    """

    def __init__(self, tool_contract_parser, arg_parser, *parsers, **kwds):
        """

        :param tool_contract_parser:
        :type tool_contract_parser: ToolContractParser
        :param arg_parser:
        :type arg_parser: PyParser
        :param parsers:
        :return:
        """

        # Tool Contract Parser
        self.tool_contract_parser = tool_contract_parser

        # python wrapper parser.
        self.arg_parser = arg_parser
        # add options, so it will show up via --help
        add_base_options_with_emit_tool_contract(self.arg_parser.parser,
            default_level=kwds.get("default_level", "INFO"))

        # a list of other parsers that adhere to the PbParserBase interface
        # can be used.
        self.other_parsers = parsers

        # for now assume parsers have the same version, id, ...
        tool_id = tool_contract_parser.tool_id
        version = tool_contract_parser.version
        name = tool_contract_parser.name
        description = tool_contract_parser.description

        super(PbParser, self).__init__(tool_id, version, name, description)

    @property
    def parsers(self):
        return [self.tool_contract_parser, self.arg_parser]

    def _dispatch(self, f_name, args, kwds):
        for parser in self.parsers:
            f = getattr(parser, f_name)
            f(*args, **kwds)

    def add_input_file_type(self, file_type, file_id, name, description):
        args = file_type, file_id, name, description
        self._dispatch("add_input_file_type", args, {})

    def add_output_file_type(self, file_type, file_id, name, description, default_name):
        args = file_type, file_id, name, description, default_name
        self._dispatch("add_output_file_type", args, {})

    def add_int(self, option_id, option_str, default, name, description):
        args = option_id, option_str, default, name, description
        self._dispatch("add_int", args, {})

    def add_float(self, option_id, option_str, default, name, description):
        args = option_id, option_str, default, name, description
        self._dispatch("add_float", args, {})

    def add_str(self, option_id, option_str, default, name, description):
        args = option_id, option_str, default, name, description
        self._dispatch("add_str", args, {})

    def add_boolean(self, option_id, option_str, default, name, description):
        args = option_id, option_str, default, name, description
        self._dispatch("add_boolean", args, {})

    def add_choice_str(self, option_id, option_str, choices, name, description,
                       default=None):
        args = option_id, option_str, choices, name, description, default
        self._dispatch("add_choice_str", args, {})

    def add_choice_int(self, option_id, option_str, choices, name, description,
                       default=None):
        args = option_id, option_str, choices, name, description, default
        self._dispatch("add_choice_int", args, {})

    def add_choice_float(self, option_id, option_str, choices, name, description,
                         default=None):
        args = option_id, option_str, choices, name, description, default
        self._dispatch("add_choice_float", args, {})

    def to_contract(self):
        return self.tool_contract_parser.to_tool_contract()


def _factory(tool_id, version, name, description, subcomponents, default_level):
    def _f(tc_parser):
        arg_parser = PyParser(tool_id, version, name, description, subcomponents=subcomponents)
        return PbParser(tc_parser, arg_parser, default_level=default_level)
    return _f


def get_pbparser(tool_id, version, name, description, driver_exe, is_distributed=True, nproc=1,
                 resource_types=(), subcomponents=(), serialization='json',
                 default_level="INFO"):
    """
    Central point of creating a Tool contract that can emit and run tool
    contracts.

    :returns: PbParser object
    """
    driver = ToolDriver(driver_exe, serialization=serialization)
    tc_parser = ToolContractParser(tool_id, version, name, description, is_distributed, driver,
                                   nproc, resource_types)
    return _factory(tool_id, version, name, description, subcomponents, default_level)(tc_parser)


def get_scatter_pbparser(tool_id, version, name, description, driver_exe, chunk_keys,
                         is_distributed=True, nproc=1, nchunks=SymbolTypes.MAX_NCHUNKS, resource_types=(),
                         subcomponents=(), serialization='json', default_level="INFO"):
    """Create a Scatter Tool"""
    driver = ToolDriver(driver_exe, serialization=serialization)
    tc_parser = ScatterToolContractParser(tool_id, version, name, description, is_distributed,
                                          driver, nproc, resource_types, chunk_keys,
                                          nchunks)
    return _factory(tool_id, version, name, description, subcomponents, default_level)(tc_parser)


def get_gather_pbparser(tool_id, version, name, description, driver_exe,
                        is_distributed=True, nproc=1, resource_types=(), subcomponents=(), serialization='json', default_level="INFO"):
    """Create a Gather tool"""
    driver = ToolDriver(driver_exe, serialization=serialization)
    tc_parser = GatherToolContractParser(tool_id, version, name, description,
                                         is_distributed, driver, nproc, resource_types)
    return _factory(tool_id, version, name, description, subcomponents, default_level)(tc_parser)
