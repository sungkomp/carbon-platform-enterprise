import importlib
import sys
from types import ModuleType
from typing import Tuple

MODULES = [
    "app.config",
    "app.db",
    "app.models",
    "app.history.models",
    "app.auth.models",
    "app.tenancy.models",
    "app.main",
]


def reload_app_modules() -> Tuple[ModuleType, ModuleType, ModuleType]:
    for mod in MODULES:
        sys.modules.pop(mod, None)
    importlib.invalidate_caches()

    importlib.import_module("app.config")
    db = importlib.import_module("app.db")
    importlib.import_module("app.models")
    importlib.import_module("app.history.models")
    importlib.import_module("app.auth.models")
    tenancy_models = importlib.import_module("app.tenancy.models")
    main = importlib.import_module("app.main")
    return main, db, tenancy_models
