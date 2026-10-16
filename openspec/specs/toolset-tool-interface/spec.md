# toolset-tool-interface Specification

## Purpose

Governs how every toolset defines its tool interfaces: inputs are flat parameters annotated with pydantic Field metadata (descriptions, examples, constraints) and outputs are structured, so all toolsets are consistent, validated, and self-documenting as the server grows.

## Requirements

### Requirement: Annotated input parameters for all tools

Every tool exposed by a registered toolset MUST declare its inputs as flat parameters, each annotated with pydantic `Field` metadata via `Annotated[type, Field(...)]`: a non-empty human-readable description and at least one example, plus validation constraints where applicable. Annotations MUST NOT change the externally callable interface (parameter names and types) of tools that predate this convention.

#### Scenario: Input schema carries descriptions and examples

- **WHEN** a client lists the tools of every registered toolset and inspects each tool's input schema
- **THEN** every parameter carries a non-empty description and at least one example, derived from its `Field` metadata

#### Scenario: Existing tools keep their callable interface

- **WHEN** a client calls `generate_pdf` with `{"text": ...}` or `convert_to_pdf` with `{"content": ..., "format": ...}`
- **THEN** the call succeeds with the same result as before the change, because the annotated parameters expose the same names and types

### Requirement: Structured tool outputs

Every tool MUST return a structured output: a pydantic model returned as structured content, or a file result for binary content. Tools MUST NOT return a plain unstructured string as their result.

#### Scenario: Pydantic output returned as structured content

- **WHEN** a client calls a tool whose output is a pydantic model
- **THEN** the response contains structured content matching that model's schema

#### Scenario: Binary outputs returned as file results

- **WHEN** a client calls a tool that produces binary content, such as `generate_pdf`
- **THEN** the response contains the binary content as a file result (a structured MCP content response), not as a plain string

### Requirement: Bootstrap toolsets are removed

The server MUST NOT expose the `echo` and `time` bootstrap toolsets. The toolset registry MUST contain only production toolsets.

#### Scenario: Bootstrap tools are gone

- **WHEN** a client lists the tools of all registered toolsets
- **THEN** no `echo` or `now_utc` tool is offered

#### Scenario: Registry compliance

- **WHEN** a client connects to each toolset registered in the toolset registry
- **THEN** every toolset mounts successfully and all of its tools comply with the input and output requirements above
