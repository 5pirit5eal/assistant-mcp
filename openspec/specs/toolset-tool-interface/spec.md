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

Every tool MUST return a structured output: a pydantic model returned as structured content. Tools MUST NOT return a plain unstructured string as their result. Binary artifacts (generated documents) are not embedded in tool results; they are uploaded to the public GCS document bucket and returned as a public resource URL inside the structured content (see the `gcs-document-delivery` capability).

#### Scenario: Pydantic output returned as structured content

- **WHEN** a client calls a tool whose output is a pydantic model
- **THEN** the response contains structured content matching that model's schema

#### Scenario: URL outputs returned as structured content

- **WHEN** a client calls a tool that produces binary content, such as `generate_pdf`
- **THEN** the response contains structured content with a `url` field, and
  no embedded binary file result

### Requirement: Bootstrap toolsets are removed

The server MUST NOT expose the `echo` and `time` bootstrap toolsets. The toolset registry MUST contain only production toolsets.

#### Scenario: Bootstrap tools are gone

- **WHEN** a client lists the tools of all registered toolsets
- **THEN** no `echo` or `now_utc` tool is offered

#### Scenario: Registry compliance

- **WHEN** a client connects to each toolset registered in the toolset registry
- **THEN** every toolset mounts successfully and all of its tools comply with the input and output requirements above

### Requirement: Tools offload blocking work off the event loop

Every tool exposed by a registered toolset MUST perform blocking work (document rendering, subprocess execution, file I/O, network uploads) off the asyncio event loop, so that a long-running tool call does not prevent the server from serving other concurrent tool calls. Validation and error behavior MUST stay unchanged: a tool that fails MUST still return the same meaningful error instead of a result, regardless of which thread performed the work.

#### Scenario: Event loop stays responsive during slow tool work

- **WHEN** a client calls a tool that performs slow blocking work (such as PDF rendering or an Office conversion) while another client concurrently invokes a fast tool on the same server
- **THEN** the fast call completes without waiting for the slow call to finish, instead of stalling until the blocking work is done

#### Scenario: Tool errors surface unchanged after offloading

- **WHEN** a client calls a tool whose offloaded work fails (for example an invalid Office container or a rendering failure)
- **THEN** the tool returns the same meaningful error message as before the offloading, instead of a result or an unhandled exception

#### Scenario: Results are unchanged after offloading

- **WHEN** a client calls any tool after the offloading change
- **THEN** the tool returns the same structured output as before the change for equivalent input
