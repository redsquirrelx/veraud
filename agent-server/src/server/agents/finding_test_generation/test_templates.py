"""Rule template rendering: one generic AST rule, one file per rule_id.

The emitted pytest modules import helpers from `_suite_helpers`. That file is
rendered once per suite from `tools/suite_helpers.py` so every rule module
can stay tiny and every change ripples consistently.
"""

import json
from pathlib import Path

from server.runtimes.verification.tools.package_discovery import (
    dotted_module,
    import_root,
)

from .schemas import VerificationSpec

SUITE_HELPER = (Path(__file__).resolve().parents[2] / "runtimes" / "verification" / "tools" / "suite_helpers.py").read_text(encoding="utf-8")


def _header(spec: VerificationSpec) -> str:
    claims = ", ".join(spec.rule_source.document_claim_ids) or "none recorded"
    components = ", ".join(spec.target_components)
    newline = "\n"
    return (
        f'"""Verification {spec.verification_id} â€” {spec.title}.{newline}\n'
        f"{spec.property}{newline}{newline}"
        f"Components: {components}{newline}"
        f"Documentary claims: {claims}{newline}"
        f'Scope: {spec.test_scenario_scope}{newline}"""\n'
    )


def _param_scope(spec: VerificationSpec) -> str:
    scope = spec.rule_params.get("scope", spec.source_scope)
    return scope if isinstance(scope, str) and scope else spec.source_scope


def _param_str_list(value) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def _layer_import_test(spec: VerificationSpec) -> str:
    source_dir = _param_scope(spec)
    forbidden_param = _param_str_list(spec.rule_params.get("forbidden_roots"))
    if forbidden_param is not None:
        forbidden_roots = tuple(forbidden_param)
    else:
        forbidden_roots = tuple(import_root(part) for part in spec.target_components[1:] if part)
    allowed = spec.rule_params.get("allowed_exceptions") or ()
    return (
        _header(spec)
        + "from _suite_helpers import scan_scope\n\n"
        + f"SCOPE = {source_dir!r}\nFORBIDDEN_ROOTS = {forbidden_roots!r}\nALLOWED_EXCEPTIONS = {tuple(allowed)!r}\nTITLE = {json.dumps(spec.title)}\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    offenders = scan_scope(SCOPE, FORBIDDEN_ROOTS, ALLOWED_EXCEPTIONS)\n"
        + "    assert not offenders, f\"Boundary violated ({TITLE}):\\n\" + \"\\n\".join(offenders)\n"
    )


def _private_module_test(spec: VerificationSpec) -> str:
    target = spec.target_components[1] if len(spec.target_components) > 1 else spec.target_components[0]
    package = spec.rule_params.get("owning_package") or target.rsplit("/", 1)[0]
    dotted = spec.rule_params.get("private_module") or dotted_module(target)
    return (
        _header(spec)
        + "from _suite_helpers import find_private_module_imports\n\n"
        + f"PRIVATE_MODULE = {dotted!r}\nOWNING_PACKAGE = {package!r}\nTITLE = {json.dumps(spec.title)}\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    offenders = find_private_module_imports(PRIVATE_MODULE, OWNING_PACKAGE)\n"
        + "    assert not offenders, f\"Private module boundary violated ({TITLE}):\\n\" + \"\\n\".join(offenders)\n"
    )


def _contract_states_dynamic_test(spec: VerificationSpec) -> str:
    module = spec.target_components[0]
    params = spec.rule_params
    forbidden = tuple(_param_str_list(params.get("forbidden_collaborators")) or ())
    method = str(params.get("method", "assess"))
    return (
        _header(spec)
        + "import datetime\nimport importlib\nimport inspect\nimport os\nimport sys\nfrom pathlib import Path\nfrom unittest.mock import MagicMock\n\n"
        + f"MODULE_RELPATH = {module!r}\nMETHOD = {method!r}\nTITLE = {json.dumps(spec.title)}\nFORBIDDEN = {forbidden!r}\n\n\n"
        + "def _repo_root() -> Path:\n"
        + "    override = os.environ.get('TALLERCITO_REPO_ROOT')\n"
        + "    return Path(override).resolve() if override else Path(__file__).resolve().parents[2]\n\n\n"
        + "def _dotted(relpath: str) -> str:\n"
        + "    parts = [part for part in relpath.replace('\\\\', '/').split('/') if part]\n"
        + "    if 'src' in parts:\n"
        + "        parts = parts[parts.index('src') + 1:]\n"
        + "    if parts[-1].endswith('.py'):\n"
        + "        parts[-1] = parts[-1][:-3]\n"
        + "        if parts[-1] == '__init__':\n"
        + "            parts.pop()\n"
        + "    return '.'.join(parts)\n\n\n"
        + "def _scalar_value(base):\n"
        + "    if base is bool: return True\n"
        + "    if base is int: return 42\n"
        + "    if base is float: return 1.5\n"
        + "    if base is str: return 'input'\n"
        + "    if base is bytes: return b'input'\n"
        + "    if base is datetime.datetime: return datetime.datetime(2020, 1, 1)\n"
        + "    if base is datetime.date: return datetime.date(2020, 1, 1)\n"
        + "    return None\n\n\n"
        + "def _synthesize(annotation, depth=0):\n"
        + "    if annotation is inspect.Parameter.empty:\n"
        + "        return MagicMock(name='unreachable')\n"
        + "    if not isinstance(annotation, type):\n"
        + "        return MagicMock(name='unreachable')\n"
        + "    if getattr(annotation, '_is_protocol', False):\n"
        + "        return MagicMock(name=annotation.__name__)\n"
        + "    scalar = _scalar_value(annotation)\n"
        + "    if scalar is not None:\n"
        + "        return scalar\n"
        + "    if depth >= 3:\n"
        + "        return MagicMock(name=annotation.__name__)\n"
        + "    try:\n"
        + "        sig = inspect.signature(annotation)\n"
        + "        params = {k: p for k, p in sig.parameters.items() if k != 'self'}\n"
        + "    except (TypeError, ValueError):\n"
        + "        return MagicMock(name=annotation.__name__)\n"
        + "    kwargs = {}\n"
        + "    for name, param in params.items():\n"
        + "        if param.default is not inspect.Parameter.empty:\n"
        + "            continue\n"
        + "        kwargs[name] = _synthesize(param.annotation, depth + 1)\n"
        + "    try:\n"
        + "        return annotation(**kwargs)\n"
        + "    except Exception:\n"
        + "        return MagicMock(name=annotation.__name__)\n\n\n"
        + "def _first_parameter_annotation(fn):\n"
        + "    try:\n"
        + "        params = list(inspect.signature(fn).parameters.values())\n"
        + "    except (TypeError, ValueError):\n"
        + "        return inspect.Parameter.empty\n"
        + "    for param in params:\n"
        + "        if param.name == 'self':\n"
        + "            continue\n"
        + "        return param.annotation\n"
        + "    return inspect.Parameter.empty\n\n\n"
        + "def _variants(module):\n"
        + "    return [obj for obj in vars(module).values() if isinstance(obj, type) and callable(getattr(obj, METHOD, None))]\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    root = _repo_root()\n"
        + "    src = root / 'src'\n"
        + "    if src.is_dir() and str(src) not in sys.path:\n"
        + "        sys.path.insert(0, str(src))\n"
        + "    module_name = _dotted(MODULE_RELPATH)\n"
        + "    try:\n"
        + "        module = importlib.import_module(module_name)\n"
        + "    except Exception as error:\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: module could not be imported (' + type(error).__name__ + '): ' + str(error))\n"
        + "    variants = _variants(module)\n"
        + "    if not variants:\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: no assess implementations found in ' + MODULE_RELPATH)\n"
        + "    mocks = []\n"
        + "    vocabularies = {}\n"
        + "    for cls in variants:\n"
        + "        collaborators = {}\n"
        + "        try:\n"
        + "            init_sig = inspect.signature(cls)\n"
        + "            init_params = {k: p for k, p in init_sig.parameters.items() if k != 'self'}\n"
        + "        except (TypeError, ValueError):\n"
        + "            init_params = {}\n"
        + "        for name, param in init_params.items():\n"
        + "            if param.default is inspect.Parameter.empty:\n"
        + "                collaborators[name] = MagicMock(name=name)\n"
        + "        try:\n"
        + "            instance = cls(**collaborators)\n"
        + "        except Exception as error:\n"
        + "            raise RuntimeError('NOT_VERIFIABLE: ' + cls.__name__ + ' could not be constructed (' + type(error).__name__ + '): ' + str(error))\n"
        + "        mocks.append((cls, collaborators))\n"
        + "        try:\n"
        + "            fn = getattr(instance, METHOD)\n"
        + "            input_arg = _synthesize(_first_parameter_annotation(fn))\n"
        + "            result = fn(input_arg)\n"
        + "        except TypeError as error:\n"
        + "            raise RuntimeError('NOT_VERIFIABLE: ' + cls.__name__ + '.' + METHOD + ' rejected the synthesized input: ' + str(error))\n"
        + "        except Exception as error:\n"
        + "            raise RuntimeError('NOT_VERIFIABLE: ' + cls.__name__ + '.' + METHOD + ' raised ' + type(error).__name__ + ': ' + str(error))\n"
        + "        if not isinstance(result, str):\n"
        + "            raise RuntimeError('NOT_VERIFIABLE: ' + cls.__name__ + '.' + METHOD + ' did not return a string literal vocabulary')\n"
        + "        vocabularies[cls.__name__] = {result}\n"
        + "    names = sorted(vocabularies)\n"
        + "    for left in range(len(names)):\n"
        + "        for right in range(left + 1, len(names)):\n"
        + "            shared = vocabularies[names[left]] & vocabularies[names[right]]\n"
        + "            assert shared, (TITLE + ' violated: variants ' + names[left] + ' and ' + names[right] + ' return disjoint vocabularies: '\n"
        + "                + repr(sorted(vocabularies[names[left]])) + ' vs ' + repr(sorted(vocabularies[names[right]])))\n"
        + "    if FORBIDDEN:\n"
        + "        for cls, collaborators in mocks:\n"
        + "            for dotted in FORBIDDEN:\n"
        + "                parts = dotted.split('.')\n"
        + "                target = collaborators.get(parts[0])\n"
        + "                if target is None:\n"
        + "                    continue\n"
        + "                for part in parts[1:]:\n"
        + "                    target = getattr(target, part)\n"
        + "                assert target.call_count == 0, (TITLE + ' violated: forbidden collaborator ' + dotted + ' was invoked by ' + cls.__name__)\n"
    )


def _collaborator_call_test(spec: VerificationSpec) -> str:
    module = spec.target_components[0]
    params = spec.rule_params
    class_name = str(params.get("class_name", ""))
    method = str(params.get("method", "consult"))
    forbidden = tuple(_param_str_list(params.get("forbidden_collaborators")) or ())
    overrides = params.get("inputs") or {}
    if not isinstance(overrides, dict):
        overrides = {}
    return (
        _header(spec)
        + "import datetime\nimport importlib\nimport inspect\nimport os\nimport sys\nfrom pathlib import Path\nfrom unittest.mock import MagicMock\n\n"
        + f"MODULE_RELPATH = {module!r}\nCLASS_NAME = {class_name!r}\nMETHOD = {method!r}\nTITLE = {json.dumps(spec.title)}\nFORBIDDEN = {forbidden!r}\nINPUTS = {overrides!r}\n\n\n"
        + "def _repo_root() -> Path:\n"
        + "    override = os.environ.get('TALLERCITO_REPO_ROOT')\n"
        + "    return Path(override).resolve() if override else Path(__file__).resolve().parents[2]\n\n\n"
        + "def _dotted(relpath: str) -> str:\n"
        + "    parts = [part for part in relpath.replace('\\\\', '/').split('/') if part]\n"
        + "    if 'src' in parts:\n"
        + "        parts = parts[parts.index('src') + 1:]\n"
        + "    if parts[-1].endswith('.py'):\n"
        + "        parts[-1] = parts[-1][:-3]\n"
        + "        if parts[-1] == '__init__':\n"
        + "            parts.pop()\n"
        + "    return '.'.join(parts)\n\n\n"
        + "def _scalar_value(base):\n"
        + "    if base is bool: return True\n"
        + "    if base is int: return 42\n"
        + "    if base is float: return 1.5\n"
        + "    if base is str: return 'input'\n"
        + "    if base is bytes: return b'input'\n"
        + "    if base is datetime.datetime: return datetime.datetime(2020, 1, 1)\n"
        + "    if base is datetime.date: return datetime.date(2020, 1, 1)\n"
        + "    return None\n\n\n"
        + "def _synthesize(annotation, depth=0):\n"
        + "    if annotation is inspect.Parameter.empty:\n"
        + "        return MagicMock(name='unreachable')\n"
        + "    if not isinstance(annotation, type):\n"
        + "        return MagicMock(name='unreachable')\n"
        + "    if getattr(annotation, '_is_protocol', False):\n"
        + "        return MagicMock(name=annotation.__name__)\n"
        + "    scalar = _scalar_value(annotation)\n"
        + "    if scalar is not None:\n"
        + "        return scalar\n"
        + "    if depth >= 3:\n"
        + "        return MagicMock(name=annotation.__name__)\n"
        + "    try:\n"
        + "        sig = inspect.signature(annotation)\n"
        + "        params = {k: p for k, p in sig.parameters.items() if k != 'self'}\n"
        + "    except (TypeError, ValueError):\n"
        + "        return MagicMock(name=annotation.__name__)\n"
        + "    kwargs = {}\n"
        + "    for name, param in params.items():\n"
        + "        if param.default is not inspect.Parameter.empty:\n"
        + "            continue\n"
        + "        kwargs[name] = _synthesize(param.annotation, depth + 1)\n"
        + "    try:\n"
        + "        return annotation(**kwargs)\n"
        + "    except Exception:\n"
        + "        return MagicMock(name=annotation.__name__)\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    root = _repo_root()\n"
        + "    src = root / 'src'\n"
        + "    if src.is_dir() and str(src) not in sys.path:\n"
        + "        sys.path.insert(0, str(src))\n"
        + "    module_name = _dotted(MODULE_RELPATH)\n"
        + "    try:\n"
        + "        module = importlib.import_module(module_name)\n"
        + "    except Exception as error:\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: module could not be imported (' + type(error).__name__ + '): ' + str(error))\n"
        + "    cls = vars(module).get(CLASS_NAME)\n"
        + "    if not isinstance(cls, type):\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: class ' + CLASS_NAME + ' not found in ' + MODULE_RELPATH)\n"
        + "    collaborators = {}\n"
        + "    try:\n"
        + "        init_sig = inspect.signature(cls)\n"
        + "        init_params = {k: p for k, p in init_sig.parameters.items() if k != 'self'}\n"
        + "    except (TypeError, ValueError):\n"
        + "        init_params = {}\n"
        + "    for name, param in init_params.items():\n"
        + "        if param.default is inspect.Parameter.empty:\n"
        + "            collaborators[name] = MagicMock(name=name)\n"
        + "    try:\n"
        + "        instance = cls(**collaborators)\n"
        + "    except Exception as error:\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: ' + CLASS_NAME + ' could not be constructed (' + type(error).__name__ + '): ' + str(error))\n"
        + "    try:\n"
        + "        fn = getattr(instance, METHOD)\n"
        + "        sig = inspect.signature(fn)\n"
        + "    except Exception as error:\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: ' + CLASS_NAME + '.' + METHOD + ' could not be inspected (' + type(error).__name__ + '): ' + str(error))\n"
        + "    params = list(sig.parameters.values())\n"
        + "    if params and params[0].name == 'self':\n"
        + "        params = params[1:]\n"
        + "    kwargs = {}\n"
        + "    for param in params:\n"
        + "        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):\n"
        + "            continue\n"
        + "        if param.name in INPUTS:\n"
        + "            kwargs[param.name] = INPUTS[param.name]\n"
        + "        elif param.default is not inspect.Parameter.empty:\n"
        + "            continue\n"
        + "        else:\n"
        + "            kwargs[param.name] = _synthesize(param.annotation)\n"
        + "    try:\n"
        + "        fn(**kwargs)\n"
        + "    except Exception as error:\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: ' + CLASS_NAME + '.' + METHOD + ' raised ' + type(error).__name__ + ': ' + str(error))\n"
        + "    for dotted in FORBIDDEN:\n"
        + "        parts = dotted.split('.')\n"
        + "        target = collaborators.get(parts[0])\n"
        + "        if target is None:\n"
        + "            continue\n"
        + "        for part in parts[1:]:\n"
        + "            target = getattr(target, part)\n"
        + "        assert target.call_count == 0, (TITLE + ' violated: forbidden collaborator call ' + dotted + ' in ' + CLASS_NAME + '.' + METHOD)\n"
    )


def _one_class_per_module_test(spec: VerificationSpec) -> str:
    """Verify each public class of storage adapters to be a distinct resource.

    Two adapter classes inside a single file signal an overloaded module with
    multiple reasons to change. But note we can only assert what the caller can
    inline: schema or key-based coupling isn't visible at AST level.
    """
    component = spec.target_components[0]
    max_classes = spec.rule_params.get("max_classes", 1)
    if not isinstance(max_classes, int) or max_classes < 1:
        max_classes = 1
    return (
        _header(spec)
        + "import ast\nimport os\nfrom pathlib import Path\n\n"
        + f"MODULE_PATH = {component!r}\nTITLE = {json.dumps(spec.title)}\nMAX_CLASSES = {max_classes}\n\n\n"
        + "def _repo_root() -> Path:\n"
        + "    override = os.environ.get('TALLERCITO_REPO_ROOT')\n"
        + "    return Path(override).resolve() if override else Path(__file__).resolve().parents[2]\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    target = _repo_root() / MODULE_PATH\n"
        + "    if not target.is_file():\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: module not found: ' + str(target))\n"
        + "    tree = ast.parse(target.read_text(encoding='utf-8'))\n"
        + "    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]\n"
        + "    assert len(classes) <= MAX_CLASSES, (\n"
        + "        f'{TITLE} violated: module defines {len(classes)} public classes ({classes}); '\n"
        + "        'the single responsibility principle suggests one resource per adapter file')\n"
    )


def _contract_states_test(spec: VerificationSpec) -> str:
    component = spec.target_components[0]
    return (
        _header(spec)
        + "import ast\nimport os\nfrom pathlib import Path\n\n"
        + f"MODULE_PATH = {component!r}\nTITLE = {json.dumps(spec.title)}\n\n\n"
        + "def _repo_root() -> Path:\n"
        + "    override = os.environ.get('TALLERCITO_REPO_ROOT')\n"
        + "    return Path(override).resolve() if override else Path(__file__).resolve().parents[2]\n\n\n"
        + "def _string_literals(node):\n"
        + "    return {child.value for child in ast.walk(node)\n"
        + "            if isinstance(child, ast.Constant) and isinstance(child.value, str)}\n\n\n"
        + "def _assess_vocabularies(tree):\n"
        + "    vocabularies = {}\n"
        + "    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:\n"
        + "        for item in cls.body:\n"
        + "            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == 'assess':\n"
        + "                vocabularies[cls.name] = _string_literals(item)\n"
        + "    return vocabularies\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    target = _repo_root() / MODULE_PATH\n"
        + "    if not target.is_file():\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: module not found: ' + str(target))\n"
        + "    tree = ast.parse(target.read_text(encoding='utf-8'))\n"
        + "    vocabularies = _assess_vocabularies(tree)\n"
        + "    if not vocabularies:\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: no assess implementations found in ' + MODULE_PATH)\n"
        + "    missing = [name for name, vocab in vocabularies.items() if not vocab]\n"
        + "    if missing:\n"
        + "        raise RuntimeError('NOT_VERIFIABLE: variant ' + ','.join(sorted(missing)) + ' returns no string literals')\n"
        + "    names = sorted(vocabularies)\n"
        + "    for left in range(len(names)):\n"
        + "        for right in range(left + 1, len(names)):\n"
        + "            assert vocabularies[names[left]] & vocabularies[names[right]], (\n"
        + "                f'{TITLE} violated: variants {names[left]} and {names[right]} return disjoint vocabularies: '\n"
        + "                f'{sorted(vocabularies[names[left]])} vs {sorted(vocabularies[names[right]])}')\n"
    )


def _restricted_import_test(spec: VerificationSpec) -> str:
    scope = _param_scope(spec)
    allowed = _param_str_list(spec.rule_params.get("allowed_roots")) or ()
    return (
        _header(spec)
        + "from _suite_helpers import restricted_import_check\n\n"
        + f"SCOPE = {scope!r}\nALLOWED_ROOTS = {tuple(allowed)!r}\nTITLE = {json.dumps(spec.title)}\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    offenders = restricted_import_check(SCOPE, ALLOWED_ROOTS)\n"
        + "    assert not offenders, f\"Import boundary violated ({TITLE}):\\n\" + \"\\n\".join(offenders)\n"
    )


def _private_attribute_test(spec: VerificationSpec) -> str:
    target_module = str(spec.rule_params.get("module_prefix") or _import_target_from(spec))
    target_scope = _param_scope(spec)
    attr_prefixes = tuple(_param_str_list(spec.rule_params.get("attr_prefixes")) or ("_",))
    return (
        _header(spec)
        + "from _suite_helpers import forbidden_attribute_check\n\n"
        + f"SCOPE = {target_scope!r}\nMODULE = {target_module!r}\nATTR_PREFIXES = {attr_prefixes!r}\nTITLE = {json.dumps(spec.title)}\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    offenders = forbidden_attribute_check(SCOPE, MODULE, ATTR_PREFIXES)\n"
        + "    assert not offenders, f\"Private access violated ({TITLE}):\\n\" + \"\\n\".join(offenders)\n"
    )


def _no_environ_test(spec: VerificationSpec) -> str:
    scope = _param_scope(spec)
    return (
        _header(spec)
        + "from _suite_helpers import no_environ_in_scope\n\n"
        + f"SCOPE = {scope!r}\nTITLE = {json.dumps(spec.title)}\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    offenders = no_environ_in_scope(SCOPE)\n"
        + "    assert not offenders, f\"Environment boundary violated ({TITLE}):\\n\" + \"\\n\".join(offenders)\n"
    )


def _circular_import_test(spec: VerificationSpec) -> str:
    scope = _param_scope(spec)
    return (
        _header(spec)
        + "from _suite_helpers import circular_import_check\n\n"
        + f"SCOPE = {scope!r}\nTITLE = {json.dumps(spec.title)}\n\n\n"
        + f"def {spec.test_name}():\n"
        + "    offenders = circular_import_check(SCOPE)\n"
        + "    assert not offenders, f\"Circular imports ({TITLE}):\\n\" + \"\\n\".join(offenders)\n"
    )


def _import_target_from(spec: VerificationSpec) -> str:
    dotted = [dotted_module(part) for part in spec.target_components]
    if len(dotted) >= 2:
        return dotted[1]
    return dotted[0] if dotted else ""


_RENDERERS = {
    "layer_import": _layer_import_test,
    "private_module_access": _private_module_test,
    "contract_states": _contract_states_test,
    "contract_states_dynamic": _contract_states_dynamic_test,
    "restricted_import": _restricted_import_test,
    "forbidden_framework_in_layer": _layer_import_test,
    "private_attribute_access": _private_attribute_test,
    "no_environ_in_scope": _no_environ_test,
    "circular_import": _circular_import_test,
    "forbidden_call": _collaborator_call_test,
    "one_class_per_module": _one_class_per_module_test,
}


def render_test_file(spec: VerificationSpec) -> tuple[str, str]:
    if spec.language in ("typescript", "javascript"):
        from .ts_templates import render_ts_test_file
        return render_ts_test_file(spec)
    renderer = _RENDERERS.get(spec.rule_kind or "")
    if renderer is None:
        raise ValueError(f"No rule renderer for {spec.rule_kind!r} (verification {spec.verification_id}).")
    return spec.test_path, renderer(spec)


def render_helper(language: str = "python") -> tuple[str, str]:
    if language in ("typescript", "javascript"):
        from .ts_templates import SUITE_HELPER_TS
        return "tests/helper.ts", SUITE_HELPER_TS
    return "tests/_suite_helpers.py", SUITE_HELPER
