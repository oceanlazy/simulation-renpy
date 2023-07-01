__all__ = ['BASE_DIR', 'orm', 'simulation', 'models', 'profiler', 'renpy']

import logging
import os

from logging.config import dictConfig

from kernel.settings import DEBUG, DEBUG_SIMULATION, DEBUG_ORM, DEBUG_ROUTE_SEARCH, DEBUG_SET_POSITIONS
from kernel.utils import Mock


try:
    import line_profiler  # noqa
except ImportError:
    profiler = Mock()
else:
    profiler = line_profiler.LineProfiler()

try:
    import renpy
except ImportError:
    renpy = Mock({'display_menu': 'cancel', 'generate_menu': 'cancel'})


if DEBUG or isinstance(renpy, Mock):
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
else:
    BASE_DIR = os.path.normpath(renpy.config.basedir)

import kernel.data  # noqa

LOGGING_HANDLERS = ['file']
if DEBUG:
    LOGGING_HANDLERS.append('stream')
LOGGING_CONFIG = {
    'version': 1,
    'formatters': {
        'standard': {
            'format': '%(message)s'
        },
    },
    'handlers': {
        'stream': {
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
        },
        'file': {
            'formatter': 'standard',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'simulation.log'),
            'mode': 'w'
        }
    },
    'loggers': {
        'simulation': {
            'handlers': LOGGING_HANDLERS,
            'level': 'DEBUG' if DEBUG_SIMULATION else 'NOTSET',
            'propagate': False
        },
        'orm': {
            'handlers': LOGGING_HANDLERS,
            'level': 'DEBUG' if DEBUG_ORM else 'NOTSET',
            'propagate': False
        },
        'route': {
            'handlers': LOGGING_HANDLERS,
            'level': 'DEBUG' if DEBUG_ROUTE_SEARCH else 'NOTSET',
            'propagate': False
        },
        'positions': {
            'handlers': LOGGING_HANDLERS,
            'level': 'DEBUG' if DEBUG_SET_POSITIONS else 'NOTSET',
            'propagate': False
        },
    }
}

logging.config.dictConfig(LOGGING_CONFIG)
