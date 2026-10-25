import ast
import io
from pathlib import Path

import pytest
from fastmcp import Client
from pypdf import PdfReader

from assistant_mcp.server import build_server
from assistant_mcp.toolsets import TOOLSETS
from assistant_mcp.toolsets.storage import GCS_BUCKET_ENV, PUBLIC_URL_TEMPLATE

_UPLOADS: dict[str, tuple[str, bytes]] = {}


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """Capture uploads so URL outputs can be verified without hitting GCS."""
    _UPLOADS.clear()
    monkeypatch.setenv(GCS_BUCKET_ENV, "test-bucket")

    async def fake_upload(data: bytes, object_name: str, content_type: str) -> str:
        _UPLOADS[object_name] = (content_type, bytes(data))
        return PUBLIC_URL_TEMPLATE.format(bucket="test-bucket", object=object_name)

    monkeypatch.setattr("assistant_mcp.toolsets.pdf.upload_document", fake_upload)
    yield
    _UPLOADS.clear()

TOOLSETS_SRC_DIR = Path(__file__).parent.parent / "src" / "assistant_mcp" / "toolsets"
MUTATING_METHODS = frozenset(
    {"append", "extend", "add", "update", "pop", "setdefault", "remove", "insert", "clear"}
)


def _bound_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Tuple | ast.List):
        return {name for element in target.elts for name in _bound_names(element)}
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return set()


def _module_level_names(module: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_bound_names(target))
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            names.update(_bound_names(node.target))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.For | ast.AsyncFor):
            names.update(_bound_names(node.target))
    return names


def _is_attribute_on_module_name(target: ast.expr, module_names: set[str]) -> bool:
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id in module_names
    )


def _statelessness_violations(source: str) -> list[str]:
    """Describe the statelessness violations in ``source``, if any.

    Detects global statements, module-level augmented assignment, mutating
    method calls on module-level names, and attribute assignment on
    module-level names (the violation classes of design decision D4).
    """
    module = ast.parse(source)
    module_names = _module_level_names(module)
    violations: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Global):
            violations.append(f"global statement ({', '.join(node.names)})")
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if _is_attribute_on_module_name(target, module_names):
                    violations.append(
                        f"attribute assignment on module-level name ({ast.unparse(target)})"
                    )
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in MUTATING_METHODS
                and isinstance(func.value, ast.Name)
                and func.value.id in module_names
            ):
                violations.append(
                    f"mutating method call on module-level name ({ast.unparse(func)})"
                )
    for node in module.body:
        if isinstance(node, ast.AugAssign):
            violations.append(
                f"augmented assignment to module-level name ({ast.unparse(node.target)})"
            )
    return violations


SYNTHETIC_VIOLATING_SOURCE = '''
_CONSTANT_LIST = []
_CONSTANT_DICT = {}
_CONSTANT_OBJECT = object()
_COUNTER = 0
_TOP_LEVEL = []


def misbehave() -> None:
    global _COUNTER
    _COUNTER += 1
    _CONSTANT_LIST.append("value")
    _CONSTANT_DICT.update({"key": "value"})
    _CONSTANT_OBJECT.attribute = "value"


_TOP_LEVEL += ["entry"]
'''


def test_scanner_rejects_synthetic_violating_module():
    violations = _statelessness_violations(SYNTHETIC_VIOLATING_SOURCE)
    assert any("global statement" in violation for violation in violations)
    assert any("augmented assignment" in violation for violation in violations)
    assert any("mutating method call" in violation for violation in violations)
    assert any("attribute assignment" in violation for violation in violations)


def test_toolset_modules_hold_no_module_level_mutable_state():
    module_paths = sorted(TOOLSETS_SRC_DIR.glob("*.py"))
    assert module_paths, f"no toolset modules found under {TOOLSETS_SRC_DIR}"
    findings = []
    for path in module_paths:
        violations = _statelessness_violations(path.read_text())
        if violations:
            findings.append(f"{path.name}: " + "; ".join(violations))
    assert not findings, "toolset modules hold cross-request state: " + " | ".join(findings)


async def test_no_bootstrap_tools_offered():
    assert TOOLSETS, "toolset registry is empty"
    for name, toolset in TOOLSETS.items():
        async with Client(toolset) as client:
            tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        assert "echo" not in tool_names, f"toolset {name} offers bootstrap tool 'echo'"
        assert "now_utc" not in tool_names, f"toolset {name} offers bootstrap tool 'now_utc'"


async def test_registry_compliance_tool_parameters_and_outputs():
    assert TOOLSETS, "toolset registry is empty"
    for name, toolset in TOOLSETS.items():
        async with Client(toolset) as client:
            tools = await client.list_tools()
        for tool in tools:
            properties = tool.input_schema.get("properties", {})
            for param_name, schema in properties.items():
                description = (schema or {}).get("description", "")
                assert description and description.strip(), (
                    f"parameter {param_name!r} of tool {tool.name!r} "
                    f"in toolset {name!r} lacks a non-empty description"
                )
                examples = (schema or {}).get("examples", [])
                assert isinstance(examples, list) and examples, (
                    f"parameter {param_name!r} of tool {tool.name!r} "
                    f"in toolset {name!r} lacks at least one example"
                )
            output_schema = tool.output_schema
            plain_string_output = output_schema is not None and (
                output_schema.get("type") == "string"
                or output_schema.get("x-fastmcp-wrap-result", False)
            )
            assert not plain_string_output, (
                f"tool {tool.name!r} in toolset {name!r} "
                f"returns a plain unstructured string"
            )


DETERMINISM_MARKDOWN = "# Determinism Probe\n\nFirst paragraph.\n\n- item one\n- item two\n"


async def test_two_server_instances_return_identical_tool_results(
    cleared_auth_env, fake_storage
):
    extracted_texts = []
    for _ in range(2):
        server = build_server()
        async with Client(server) as client:
            result = await client.call_tool("pdf_generate_pdf", {"text": DETERMINISM_MARKDOWN})
        assert not result.is_error
        url = result.structured_content["url"]
        assert url.startswith("https://storage.googleapis.com/") and url.endswith(".pdf")
        object_name = url.removeprefix("https://storage.googleapis.com/test-bucket/")
        pdf = _UPLOADS[object_name][1]
        reader = PdfReader(io.BytesIO(pdf))
        extracted_texts.append("\n".join(page.extract_text() or "" for page in reader.pages))
    assert "Determinism Probe" in extracted_texts[0]
    assert extracted_texts[0] == extracted_texts[1]
