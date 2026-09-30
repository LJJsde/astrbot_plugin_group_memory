from .connection import Connection, connect
from .errors import (
    DatabaseError,
    DataError,
    Error,
    IntegrityError,
    InterfaceError,
    InternalError,
    MySQLError,
    NotSupportedError,
    OperationalError,
    ProgrammingError,
    Warning,
)
from .pool import Pool, create_pool

#: Version of the DB-API 2.0 specification this module implements.
apilevel = "2.0"
#: Threads may share the module, but not connections.
threadsafety = 1
#: Placeholders are ``%s`` (positional) and ``%(name)s`` (named).
paramstyle = "pyformat"

__all__ = [
    "Connection",
    "DataError",
    "DatabaseError",
    "Error",
    "IntegrityError",
    "InterfaceError",
    "InternalError",
    "MySQLError",
    "NotSupportedError",
    "OperationalError",
    "Pool",
    "ProgrammingError",
    "Warning",
    "apilevel",
    "connect",
    "create_pool",
    "paramstyle",
    "threadsafety",
]
