"""Repository task corpus for the bounded lane (pure data).

Leakage boundary: `public_spec` is the only part a production run may use. `oracle` carries hidden test ids
only; ids are resolved to files exclusively by `benchmark.repo_task_eval`. `reference_patch`, `gold_*` and
`missing_fact` are evaluator/validator data and must never reach a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from core.bounded_task import TaskSpec

Split = Literal["dev", "heldout"]
Outcome = Literal["verified_done", "escalate"]


@dataclass(frozen=True)
class OracleSpec:
    hidden_test_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepoTask:
    name: str
    repo: str
    prompt: str
    category: str
    split: Split
    expected_outcome: Outcome
    public_spec: TaskSpec
    oracle: OracleSpec
    gold_files: tuple[str, ...]
    gold_symbols: tuple[str, ...] = ()
    reference_patch: dict[str, str] | None = None
    missing_fact: tuple[str, ...] = field(default_factory=tuple)


CORE_TESTS = {"type": "pytest_passes", "tests": ["tests/test_core.py"]}


def _expr(code: str, expected: str) -> dict:
    return {"type": "python_expr_equals", "code": code, "expected_stdout": expected}


def _spec(prompt: str, mutable: tuple[str, ...], *checks: dict) -> TaskSpec:
    return TaskSpec(prompt, mutable, (*checks, CORE_TESTS), allow_code_execution=True)


def _task(name, repo, prompt, category, split, mutable, checks, gold_files, gold_symbols=(), patch=None, missing=()):
    solvable = patch is not None
    return RepoTask(
        name=name, repo=repo, prompt=prompt, category=category, split=split,
        expected_outcome="verified_done" if solvable else "escalate",
        public_spec=_spec(prompt, mutable, *checks),
        oracle=OracleSpec((name,) if solvable else ()),
        gold_files=gold_files, gold_symbols=gold_symbols, reference_patch=patch, missing_fact=tuple(missing),
    )


# ---------------------------------------------------------------- mathlib
MATH_OPS = "def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return b - a\n\n\ndef multiply(a, b):\n    return a * b\n\n\ndef divide(a, b):\n    return a / b\n"
MATH_STATS = "def mean(values):\n    return sum(values) / len(values)\n\n\ndef median(values):\n    ordered = sorted(values)\n    return ordered[len(ordered) // 2]\n"
MATH_INIT = 'from .operations import add, divide, multiply, subtract\nfrom .stats import mean, median\n\n__all__ = ["add", "subtract", "multiply", "divide", "mean", "median"]\n'
CALC = 'from mathlib import add, divide, multiply, subtract\n\nOPERATIONS = {\n    "add": add,\n    "subtract": subtract,\n    "multiply": multiply,\n    "divide": divide,\n}\n\n\ndef evaluate(op, a, b):\n    return OPERATIONS[op](a, b)\n'

MATHLIB = [
    _task("mathlib_fix_subtract", "mathlib", "subtract(5, 3) returns -2 but it should return 2. Fix subtract.",
          "bugfix-localization", "dev", ("mathlib/operations.py",),
          [_expr("from mathlib import subtract\nprint(subtract(5, 3), subtract(0, 4))", "2 -4")],
          ("mathlib/operations.py",), ("mathlib.operations.subtract",),
          {"mathlib/operations.py": MATH_OPS.replace("return b - a", "return a - b")}),
    _task("mathlib_median_even", "mathlib", "median([1, 2, 3, 4]) returns 3 but should return 2.5: for an even number of values, median must average the two middle values.",
          "bugfix-localization", "dev", ("mathlib/stats.py",),
          [_expr("from mathlib import median\nprint(median([1, 2, 3, 4]), median([4, 1, 3, 2, 6, 5]))", "2.5 3.5")],
          ("mathlib/stats.py",), ("mathlib.stats.median",),
          {"mathlib/stats.py": MATH_STATS.replace("    return ordered[len(ordered) // 2]\n",
                                                  "    middle = len(ordered) // 2\n    if len(ordered) % 2 == 0:\n        return (ordered[middle - 1] + ordered[middle]) / 2\n    return ordered[middle]\n")}),
    _task("mathlib_divide_zero", "mathlib", "divide(a, 0) currently raises ZeroDivisionError. Make it raise ValueError with the message 'division by zero' instead.",
          "bugfix-localization", "dev", ("mathlib/operations.py",),
          [_expr("from mathlib import divide\ntry:\n    divide(1, 0)\nexcept ValueError as error:\n    print(error)\nprint(divide(6, 3))", "division by zero\n2.0")],
          ("mathlib/operations.py",), ("mathlib.operations.divide",),
          {"mathlib/operations.py": MATH_OPS.replace("def divide(a, b):\n    return a / b\n", "def divide(a, b):\n    if b == 0:\n        raise ValueError(\"division by zero\")\n    return a / b\n")}),
    _task("mathlib_add_power", "mathlib", "Add a power(a, b) function to mathlib/operations.py, export it from the mathlib package, and support the 'power' operation in calculator.evaluate.",
          "multi-file", "dev", ("mathlib/operations.py", "mathlib/__init__.py", "calculator.py"),
          [_expr("import calculator\nfrom mathlib import power\nprint(power(2, 10), calculator.evaluate('power', 3, 2))", "1024 9")],
          ("mathlib/operations.py", "mathlib/__init__.py", "calculator.py"), ("mathlib.operations.power", "calculator.evaluate"),
          {"mathlib/operations.py": MATH_OPS + "\n\ndef power(a, b):\n    return a ** b\n",
           "mathlib/__init__.py": MATH_INIT.replace("multiply, subtract", "multiply, power, subtract").replace('"divide",', '"divide", "power",'),
           "calculator.py": CALC.replace("from mathlib import add, divide, multiply, subtract", "from mathlib import add, divide, multiply, power, subtract").replace('    "divide": divide,\n', '    "divide": divide,\n    "power": power,\n')}),
    _task("mathlib_rounding_policy", "mathlib", "Make divide round its result to the number of decimal places required by the finance team.",
          "insufficient-evidence", "dev", ("mathlib/operations.py",),
          [_expr("from mathlib import divide\nprint(divide(1, 3))", "0.3333")],
          ("mathlib/operations.py",), missing=("0.3333", "finance", "decimal places")),
    _task("mathlib_mean_empty", "mathlib", "mean([]) raises ZeroDivisionError. It should return 0.0 for an empty list.",
          "bugfix-localization", "heldout", ("mathlib/stats.py",),
          [_expr("from mathlib import mean\nprint(mean([]), mean([2, 4]))", "0.0 3.0")],
          ("mathlib/stats.py",), ("mathlib.stats.mean",),
          {"mathlib/stats.py": MATH_STATS.replace("def mean(values):\n    return sum(values) / len(values)\n", "def mean(values):\n    if not values:\n        return 0.0\n    return sum(values) / len(values)\n")}),
    _task("mathlib_unknown_operation", "mathlib", "calculator.evaluate('modulo', 1, 2) raises KeyError. Unsupported operations must raise ValueError('unknown operation: <name>') with the operation name.",
          "bugfix-localization", "heldout", ("calculator.py",),
          [_expr("import calculator\ntry:\n    calculator.evaluate('modulo', 1, 2)\nexcept ValueError as error:\n    print(error)\nprint(calculator.evaluate('add', 1, 2))", "unknown operation: modulo\n3")],
          ("calculator.py",), ("calculator.evaluate",),
          {"calculator.py": CALC.replace("def evaluate(op, a, b):\n    return OPERATIONS[op](a, b)\n", "def evaluate(op, a, b):\n    if op not in OPERATIONS:\n        raise ValueError(f\"unknown operation: {op}\")\n    return OPERATIONS[op](a, b)\n")}),
    _task("mathlib_add_clamp", "mathlib", "Add clamp(value, low, high) to mathlib/operations.py that limits value to the range [low, high], and export it from the mathlib package.",
          "multi-file", "heldout", ("mathlib/operations.py", "mathlib/__init__.py"),
          [_expr("from mathlib import clamp\nprint(clamp(5, 0, 3), clamp(-1, 0, 3), clamp(2, 0, 3))", "3 0 2")],
          ("mathlib/operations.py", "mathlib/__init__.py"), ("mathlib.operations.clamp",),
          {"mathlib/operations.py": MATH_OPS + "\n\ndef clamp(value, low, high):\n    return max(low, min(high, value))\n",
           "mathlib/__init__.py": MATH_INIT.replace("from .operations import add,", "from .operations import add, clamp,").replace('"median"]', '"median", "clamp"]')}),
    _task("mathlib_median_empty", "mathlib", "median([]) raises IndexError. Make it raise ValueError('median of empty list') instead.",
          "bugfix-localization", "heldout", ("mathlib/stats.py",),
          [_expr("from mathlib import median\ntry:\n    median([])\nexcept ValueError as error:\n    print(error)\nprint(median([3, 1, 2]))", "median of empty list\n2")],
          ("mathlib/stats.py",), ("mathlib.stats.median",),
          {"mathlib/stats.py": MATH_STATS.replace("    ordered = sorted(values)\n", "    if not values:\n        raise ValueError(\"median of empty list\")\n    ordered = sorted(values)\n")}),
    _task("mathlib_weighted_mean", "mathlib", "Change mean to use the weighting scheme described in the design document.",
          "insufficient-evidence", "heldout", ("mathlib/stats.py",),
          [_expr("from mathlib import mean\nprint(mean([1, 2, 3]))", "2.3333")],
          ("mathlib/stats.py",), missing=("2.3333", "weight", "design document")),
]

# ---------------------------------------------------------------- configsvc
APP_JSON = '{\n  "name": "svc",\n  "port": 3000,\n  "debug": false,\n  "database": {\n    "host": "localhost",\n    "port": 5432\n  },\n  "features": [\n    "login"\n  ]\n}\n'
SETTINGS = 'import json\n\nDEFAULTS = {"port": 80, "debug": False, "timeout": 30}\n\n\ndef load_settings(path):\n    with open(path, encoding="utf-8") as handle:\n        data = json.load(handle)\n    return {**data, **DEFAULTS}\n\n\ndef is_debug(settings):\n    return settings.get("debug") is True\n'
SERVER = "def describe(settings):\n    return f\"{settings['name']}:{settings['port']}\"\n"
JSON_CFG = "config/app.json"

CONFIGSVC = [
    _task("config_service_port", "configsvc", "Change the service port in app.json from 3000 to 8080. The legacy config must stay as it is.",
          "config-change", "dev", (JSON_CFG,),
          [{"type": "json_pointer_equals", "path": JSON_CFG, "pointer": "/port", "value": 8080}, {"type": "json_keys_preserved", "path": JSON_CFG}],
          (JSON_CFG,), patch={JSON_CFG: APP_JSON.replace('"port": 3000', '"port": 8080')}),
    _task("config_database_host", "configsvc", "Point the database host in app.json to db.internal.",
          "config-change", "dev", (JSON_CFG,),
          [{"type": "json_pointer_equals", "path": JSON_CFG, "pointer": "/database/host", "value": "db.internal"}, {"type": "json_keys_preserved", "path": JSON_CFG}],
          (JSON_CFG,), patch={JSON_CFG: APP_JSON.replace('"host": "localhost"', '"host": "db.internal"')}),
    _task("config_add_feature", "configsvc", "Add 'search' to the features list in app.json, keeping the existing features.",
          "config-change", "dev", (JSON_CFG,),
          [{"type": "json_pointer_equals", "path": JSON_CFG, "pointer": "/features", "value": ["login", "search"]}, {"type": "json_keys_preserved", "path": JSON_CFG}],
          (JSON_CFG,), patch={JSON_CFG: APP_JSON.replace('    "login"\n', '    "login",\n    "search"\n')}),
    _task("config_file_overrides_defaults", "configsvc", "load_settings lets DEFAULTS override values from the JSON file (loading config/app.json reports port 80). Values from the file must take precedence over DEFAULTS.",
          "bugfix-localization", "dev", ("configsvc/settings.py",),
          [_expr("from configsvc import load_settings\nsettings = load_settings('config/app.json')\nprint(settings['port'], settings['timeout'])", "3000 30")],
          ("configsvc/settings.py",), ("configsvc.settings.load_settings",),
          {"configsvc/settings.py": SETTINGS.replace("return {**data, **DEFAULTS}", "return {**DEFAULTS, **data}")}),
    _task("config_database_password", "configsvc", "Set the production database password in app.json.",
          "insufficient-evidence", "dev", (JSON_CFG,),
          [{"type": "json_pointer_equals", "path": JSON_CFG, "pointer": "/database/password", "value": "R7-prod-credential"}],
          (JSON_CFG,), missing=("R7-prod-credential", "password")),
    _task("config_describe_format", "configsvc", "server.describe returns 'svc:3000'. It should return 'svc on port 3000' (the name, then 'on port', then the port).",
          "bugfix-localization", "heldout", ("configsvc/server.py",),
          [_expr("from configsvc import describe\nprint(describe({'name': 'svc', 'port': 3000}))", "svc on port 3000")],
          ("configsvc/server.py",), ("configsvc.server.describe",),
          {"configsvc/server.py": SERVER.replace("{settings['name']}:{settings['port']}", "{settings['name']} on port {settings['port']}")}),
    _task("config_debug_strings", "configsvc", "is_debug must also treat the strings 'true' and 'True' as enabled and 'false' as disabled, while still accepting booleans.",
          "bugfix-localization", "heldout", ("configsvc/settings.py",),
          [_expr("from configsvc import is_debug\nprint(is_debug({'debug': 'true'}), is_debug({'debug': 'True'}), is_debug({'debug': 'false'}), is_debug({'debug': True}))", "True True False True")],
          ("configsvc/settings.py",), ("configsvc.settings.is_debug",),
          {"configsvc/settings.py": SETTINGS.replace('    return settings.get("debug") is True\n', '    value = settings.get("debug")\n    if isinstance(value, str):\n        return value.lower() == "true"\n    return value is True\n')}),
    _task("config_remove_debug", "configsvc", "Remove the debug key from app.json.",
          "config-change", "heldout", (JSON_CFG,),
          [_expr("import json\ndata = json.load(open('config/app.json'))\nprint('debug' in data, data['port'], data['database']['host'])", "False 3000 localhost")],
          (JSON_CFG,), patch={JSON_CFG: APP_JSON.replace('  "debug": false,\n', "")}),
    _task("config_database_port", "configsvc", "Change the database port in app.json to 6543.",
          "config-change", "heldout", (JSON_CFG,),
          [{"type": "json_pointer_equals", "path": JSON_CFG, "pointer": "/database/port", "value": 6543}, {"type": "json_keys_preserved", "path": JSON_CFG}],
          (JSON_CFG,), patch={JSON_CFG: APP_JSON.replace('"port": 5432', '"port": 6543')}),
    _task("config_brand_name", "configsvc", "Rename the service in app.json to the new brand name chosen by marketing.",
          "insufficient-evidence", "heldout", (JSON_CFG,),
          [{"type": "json_pointer_equals", "path": JSON_CFG, "pointer": "/name", "value": "Nimbus"}],
          (JSON_CFG,), missing=("Nimbus", "brand", "marketing")),
]

# ---------------------------------------------------------------- textkit
SLUG = 'def slugify(text):\n    return text.strip().lower().replace(" ", "-")\n'
FMT = 'def title_case(text):\n    return " ".join(word.capitalize() for word in text.split())\n\n\ndef truncate(text, limit):\n    return text[:limit] + "..."\n'
TK_INIT = 'from .formatting import title_case, truncate\nfrom .slugify import slugify\n\n__all__ = ["slugify", "title_case", "truncate"]\n'
CLI = 'import sys\n\nfrom textkit import slugify\n\n\ndef main(argv=None):\n    args = sys.argv[1:] if argv is None else argv\n    print(slugify(" ".join(args)))\n\n\nif __name__ == "__main__":\n    main()\n'

TEXTKIT = [
    _task("textkit_slug_spaces", "textkit", "slugify('Hello   World') returns 'hello---world'. Runs of spaces must become a single hyphen.",
          "bugfix-localization", "dev", ("textkit/slugify.py",),
          [_expr("from textkit import slugify\nprint(slugify('Hello   World'), slugify('a b'))", "hello-world a-b")],
          ("textkit/slugify.py",), ("textkit.slugify.slugify",),
          {"textkit/slugify.py": 'def slugify(text):\n    return "-".join(text.strip().lower().split())\n'}),
    _task("textkit_truncate_limit", "textkit", "truncate(text, limit) must return at most limit characters in total, including the '...' suffix, when text is longer than limit.",
          "bugfix-localization", "dev", ("textkit/formatting.py",),
          [_expr("from textkit import truncate\nresult = truncate('abcdefghij', 6)\nprint(result, len(result))", "abc... 6")],
          ("textkit/formatting.py",), ("textkit.formatting.truncate",),
          {"textkit/formatting.py": FMT.replace('    return text[:limit] + "..."\n', '    if len(text) <= limit:\n        return text\n    return text[: max(limit - 3, 0)] + "..."\n')}),
    _task("textkit_slug_punctuation", "textkit", "slugify must remove every character that is not a letter, digit, space or hyphen: slugify('Hello, World!') should be 'hello-world'.",
          "bugfix-localization", "dev", ("textkit/slugify.py",),
          [_expr("from textkit import slugify\nprint(slugify('Hello, World!'))", "hello-world")],
          ("textkit/slugify.py",), ("textkit.slugify.slugify",),
          {"textkit/slugify.py": 'def slugify(text):\n    kept = "".join(ch for ch in text if ch.isalnum() or ch in " -")\n    return kept.strip().lower().replace(" ", "-")\n'}),
    _task("textkit_cli_upper", "textkit", "Add an --upper flag to textkit/cli.py: main(['--upper', 'hi there']) should print 'HI-THERE'. Without the flag the output stays unchanged.",
          "feature", "dev", ("textkit/cli.py",),
          [_expr("from textkit.cli import main\nmain(['--upper', 'hi there'])\nmain(['hi there'])", "HI-THERE\nhi-there")],
          ("textkit/cli.py",), ("textkit.cli.main",),
          {"textkit/cli.py": CLI.replace('    args = sys.argv[1:] if argv is None else argv\n    print(slugify(" ".join(args)))\n',
                                         '    args = list(sys.argv[1:] if argv is None else argv)\n    upper = "--upper" in args\n    args = [arg for arg in args if arg != "--upper"]\n    slug = slugify(" ".join(args))\n    print(slug.upper() if upper else slug)\n')}),
    _task("textkit_style_guide", "textkit", "Make title_case follow the house style guide's list of words that stay lowercase.",
          "insufficient-evidence", "dev", ("textkit/formatting.py",),
          [_expr("from textkit import title_case\nprint(title_case('the zeta of omega'))", "THE zeta OF omega")],
          ("textkit/formatting.py",), missing=("THE zeta OF omega", "style guide")),
    _task("textkit_title_small_words", "textkit", "title_case('the lord of the rings') should return 'The Lord of the Rings': keep 'of', 'the', 'and' and 'a' lowercase unless they are the first word.",
          "bugfix-localization", "heldout", ("textkit/formatting.py",),
          [_expr("from textkit import title_case\nprint(title_case('the lord of the rings'))\nprint(title_case('a tale and a song'))", "The Lord of the Rings\nA Tale and a Song")],
          ("textkit/formatting.py",), ("textkit.formatting.title_case",),
          {"textkit/formatting.py": FMT.replace('def title_case(text):\n    return " ".join(word.capitalize() for word in text.split())\n',
                                                'SMALL_WORDS = {"of", "the", "and", "a"}\n\n\ndef title_case(text):\n    words = text.split()\n    return " ".join(w.capitalize() if i == 0 or w.lower() not in SMALL_WORDS else w.lower() for i, w in enumerate(words))\n')}),
    _task("textkit_truncate_short", "textkit", "truncate must return text unchanged when it is not longer than limit: truncate('abc', 5) == 'abc'.",
          "bugfix-localization", "heldout", ("textkit/formatting.py",),
          [_expr("from textkit import truncate\nprint(truncate('abc', 5), truncate('abcde', 5))", "abc abcde")],
          ("textkit/formatting.py",), ("textkit.formatting.truncate",),
          {"textkit/formatting.py": FMT.replace('    return text[:limit] + "..."\n', '    if len(text) <= limit:\n        return text\n    return text[:limit] + "..."\n')}),
    _task("textkit_slug_trim_hyphens", "textkit", "slugify must not return leading or trailing hyphens: slugify('  -Hello World-  ') should be 'hello-world'.",
          "bugfix-localization", "heldout", ("textkit/slugify.py",),
          [_expr("from textkit import slugify\nprint(slugify('  -Hello World-  '))", "hello-world")],
          ("textkit/slugify.py",), ("textkit.slugify.slugify",),
          {"textkit/slugify.py": 'def slugify(text):\n    return text.strip().lower().replace(" ", "-").strip("-")\n'}),
    _task("textkit_word_count", "textkit", "Add word_count(text) to textkit/formatting.py returning the number of whitespace-separated words, and export it from the textkit package.",
          "multi-file", "heldout", ("textkit/formatting.py", "textkit/__init__.py"),
          [_expr("from textkit import word_count\nprint(word_count('one two  three'), word_count(''))", "3 0")],
          ("textkit/formatting.py", "textkit/__init__.py"), ("textkit.formatting.word_count",),
          {"textkit/formatting.py": FMT + "\n\ndef word_count(text):\n    return len(text.split())\n",
           "textkit/__init__.py": TK_INIT.replace("title_case, truncate", "title_case, truncate, word_count").replace('"truncate"]', '"truncate", "word_count"]')}),
    _task("textkit_cms_separator", "textkit", "Change slugify's separator to the one required by the CMS.",
          "insufficient-evidence", "heldout", ("textkit/slugify.py",),
          [_expr("from textkit import slugify\nprint(slugify('a b'))", "a~b")],
          ("textkit/slugify.py",), missing=("a~b", "CMS")),
]

# ---------------------------------------------------------------- inventory
MODELS = "from dataclasses import dataclass\n\n\n@dataclass\nclass Item:\n    sku: str\n    name: str\n    qty: int\n    price: float\n"
STORAGE = 'import json\n\nfrom .models import Item\n\n\ndef load_items(path):\n    with open(path, encoding="utf-8") as handle:\n        return [Item(**row) for row in json.load(handle)]\n\n\ndef save_items(path, items):\n    with open(path, "w", encoding="utf-8") as handle:\n        json.dump([item.__dict__ for item in items], handle)\n'
SERVICE = "REORDER_THRESHOLD = 10\n\n\ndef total_value(items):\n    return sum(item.price for item in items)\n\n\ndef low_stock(items, threshold):\n    return [item for item in items if item.qty < threshold]\n\n\ndef find_item(items, sku):\n    return next(item for item in items if item.sku == sku)\n"
INV_INIT = 'from .models import Item\nfrom .service import find_item, low_stock, total_value\nfrom .storage import load_items, save_items\n\n__all__ = ["Item", "find_item", "low_stock", "total_value", "load_items", "save_items"]\n'
ITEMS = '[\n  {"sku": "A-100", "name": "Bolt", "qty": 40, "price": 0.25},\n  {"sku": "B-200", "name": "Nut", "qty": 5, "price": 0.1},\n  {"sku": "C-300", "name": "Washer", "qty": 10, "price": 0.05}\n]\n'
LOAD = "from inventory import load_items\nitems = load_items('data/items.json')\n"

INVENTORY = [
    _task("inventory_total_value", "inventory", "total_value(items) ignores quantities: it must return the sum of qty * price over all items.",
          "bugfix-localization", "dev", ("inventory/service.py",),
          [_expr(LOAD + "from inventory import total_value\nprint(round(total_value(items), 2))", "11.0")],
          ("inventory/service.py",), ("inventory.service.total_value",),
          {"inventory/service.py": SERVICE.replace("sum(item.price for item in items)", "sum(item.qty * item.price for item in items)")}),
    _task("inventory_low_stock_equal", "inventory", "low_stock(items, threshold) must also include items whose qty equals the threshold.",
          "bugfix-localization", "dev", ("inventory/service.py",),
          [_expr(LOAD + "from inventory import low_stock\nprint([item.sku for item in low_stock(items, 10)])", "['B-200', 'C-300']")],
          ("inventory/service.py",), ("inventory.service.low_stock",),
          {"inventory/service.py": SERVICE.replace("item.qty < threshold", "item.qty <= threshold")}),
    _task("inventory_find_missing", "inventory", "find_item(items, sku) raises StopIteration for an unknown sku. It should return None instead.",
          "bugfix-localization", "dev", ("inventory/service.py",),
          [_expr(LOAD + "from inventory import find_item\nprint(find_item(items, 'Z-999'), find_item(items, 'A-100').name)", "None Bolt")],
          ("inventory/service.py",), ("inventory.service.find_item",),
          {"inventory/service.py": SERVICE.replace("next(item for item in items if item.sku == sku)", "next((item for item in items if item.sku == sku), None)")}),
    _task("inventory_update_qty", "inventory", "Set the qty of sku A-100 in items.json to 25. The backup copy must not change.",
          "config-change", "dev", ("data/items.json",),
          [{"type": "json_pointer_equals", "path": "data/items.json", "pointer": "/0/qty", "value": 25},
           _expr("import json\ndata = json.load(open('data/items.json'))\nprint(len(data), data[0]['sku'], data[1]['qty'], data[2]['qty'])", "3 A-100 5 10")],
          ("data/items.json",), patch={"data/items.json": ITEMS.replace('"qty": 40', '"qty": 25')}),
    _task("inventory_supplier_discount", "inventory", "Apply the supplier's new discount rate to every price in items.json.",
          "insufficient-evidence", "dev", ("data/items.json",),
          [_expr("import json\nprint([row['price'] for row in json.load(open('data/items.json'))])", "[0.2, 0.08, 0.04]")],
          ("data/items.json",), missing=("0.08", "discount rate")),
    _task("inventory_restock", "inventory", "Add restock(items, sku, amount) to inventory/service.py that increases the qty of the item with that sku by amount and returns the item, and export it from the inventory package.",
          "multi-file", "heldout", ("inventory/service.py", "inventory/__init__.py"),
          [_expr(LOAD + "from inventory import restock\nitem = restock(items, 'B-200', 7)\nprint(item.qty, items[1].qty)", "12 12")],
          ("inventory/service.py", "inventory/__init__.py"), ("inventory.service.restock",),
          {"inventory/service.py": SERVICE + "\n\ndef restock(items, sku, amount):\n    item = find_item(items, sku)\n    item.qty += amount\n    return item\n",
           "inventory/__init__.py": INV_INIT.replace("find_item, low_stock, total_value", "find_item, low_stock, restock, total_value").replace('"low_stock",', '"low_stock", "restock",')}),
    _task("inventory_item_value", "inventory", "Add a value property to Item in inventory/models.py that returns qty * price.",
          "feature", "heldout", ("inventory/models.py",),
          [_expr("from inventory import Item\nprint(Item('X-1', 'Thing', 4, 2.5).value)", "10.0")],
          ("inventory/models.py",), ("inventory.models.Item.value",),
          {"inventory/models.py": MODELS + "\n    @property\n    def value(self):\n        return self.qty * self.price\n"}),
    _task("inventory_save_indent", "inventory", "save_items must write JSON indented with 2 spaces.",
          "bugfix-localization", "heldout", ("inventory/storage.py",),
          [_expr(LOAD + "from inventory import save_items\nsave_items('out.json', items)\nprint(open('out.json').read().startswith('[\\n  {'))", "True")],
          ("inventory/storage.py",), ("inventory.storage.save_items",),
          {"inventory/storage.py": STORAGE.replace("json.dump([item.__dict__ for item in items], handle)", "json.dump([item.__dict__ for item in items], handle, indent=2)")}),
    _task("inventory_category_field", "inventory", "Add a category field to Item with default 'general', and make load_items keep the category from items.json when a row has one.",
          "multi-file", "heldout", ("inventory/models.py", "inventory/storage.py"),
          [_expr("import json\nrows = json.load(open('data/items.json'))\nrows[0]['category'] = 'hardware'\njson.dump(rows, open('data/items.json', 'w'))\nfrom inventory import Item, load_items\nitems = load_items('data/items.json')\nprint(items[0].category, items[1].category, Item('X-1', 'Thing', 1, 1.0).category)", "hardware general general")],
          ("inventory/models.py",), ("inventory.models.Item",),
          {"inventory/models.py": MODELS + '    category: str = "general"\n'}),
    _task("inventory_reorder_threshold", "inventory", "Set REORDER_THRESHOLD in inventory/service.py to the value the warehouse manager requested.",
          "insufficient-evidence", "heldout", ("inventory/service.py",),
          [_expr("from inventory.service import REORDER_THRESHOLD\nprint(REORDER_THRESHOLD)", "17")],
          ("inventory/service.py",), missing=("warehouse manager", "= 17")),
]

TASKS: list[RepoTask] = MATHLIB + CONFIGSVC + TEXTKIT + INVENTORY
TASKS_BY_NAME = {task.name: task for task in TASKS}
