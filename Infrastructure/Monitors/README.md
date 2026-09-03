# Monitors

A **monitor** wraps a monitoring tool and manages its input pre-processing, (optional)
compilation, execution, and output post-processing. This document describes the
interface a monitor wrapper must implement; the base class lives here in
[`BaseMonitorTemplate.py`](BaseMonitorTemplate.py).

## Where a monitor lives

A monitor consists of two parts in the [Archive](../../Archive/README.md):

- a **Dockerfile** packaging the tool, under `Archive/Docker/Tools/<Name>/`
  (with `tool.properties`; see the [Archive README](../../Archive/README.md)), and
- a **wrapper class**, under `Archive/Implementations/Monitors/<Name>/<Name>.py`.

## Discovery rules

1. The wrapper class **must** extend `BaseMonitorTemplate` (plus the running
   interfaces it supports — see below).
2. The **folder name, file name, and class name must be identical** (case-sensitive),
   and should match the tool `identifier` used in experiment YAML.

```
Archive/Implementations/Monitors/
  TimelyMon/
    TimelyMon.py   → class TimelyMon(BaseMonitorTemplate, OfflineRunnable, OnlineRunnable)
```

A mismatched name prevents the monitor from being discovered.

## Class declaration

A monitor extends `BaseMonitorTemplate` and **one or both** of the running mixins,
depending on which modes it supports:

```python
from Infrastructure.Monitors.BaseMonitorTemplate import (
    BaseMonitorTemplate, OfflineRunnable, OnlineRunnable,
)

class MonPoly(BaseMonitorTemplate, OfflineRunnable, OnlineRunnable):
    ...
```

## Base interface (`BaseMonitorTemplate` / `AutoConvertable`)

**`__init__(self, image: AbstractToolImageManager, name, params: Dict[AnyStr, Any])`**
Connect the monitor to its underlying Docker image. `params` holds the tool's
parameters/options (from the YAML `monitors[].params`) plus any required converters or
utilities. Call `super().__init__(...)`.

**`supported_trace_formats() -> List[InputOutputTraceFormats]`** (static)
**`supported_policy_formats() -> List[InputOutputPolicyFormats]`** (static)
Declare the trace and policy formats the tool accepts. For these formats the platform
performs **automatic conversion** from the source format — you get the converted inputs
for free.

**`preprocessing_data(self, path_to_folder, data_file, trace_source, path_manager)`**
**`preprocessing_policy(self, path_to_folder, policy_file, signature_file, policy_source, path_manager)`**
Custom pre-processing, used only when automatic conversion is *not* available for the
source format. Write all derived files to the private `path_to_folder/scratch`
directory. If the tool relies solely on automatic conversion, raise
`NotImplementedError` (the concrete `preprocessing` method on the base class chooses
between auto-conversion and these hooks).

The base `preprocessing` converts the **policy before the trace**, and hands the same
`params` dict to every converter in both chains, so a policy converter can pass data to
the trace conversion through it. 

## Offline interface (`OfflineRunnable`)

Implement these to support offline (whole-trace) monitoring:

**`construct_offline_command(self) -> Tuple[List[str], Optional[str]]`**
Build the container command (and optional stdin) that runs the monitor on the prepared
inputs, setting the necessary flags from `self.params`.

**`offline_compile(self)`** *(optional; default no-op)*
For *compiled* monitors, synthesize the binary from the policy. Interpreted monitors
omit this.

**`post_processing_offline(self, stdout_input: AnyStr) -> AbstractOutputStructure`**
Parse the tool's raw output into one of the platform's standard verdict structures
(`PropositionList`, `Verdicts`, `OOOVerdicts`, or `PropositionTree`).

## Online interface (`OnlineRunnable`)

Implement these to support online (streaming) monitoring:

**`construct_online_command(self) -> Tuple[List[str], Optional[str]]`**
Build the streaming command (and optional stdin).

**`latency_marker() -> Optional[str]`** (static)
Return the marker the platform uses to measure per-step latency, or `None`.

**`online_compile(self) -> Optional[Dict[str, str]]`** *(optional; default `None`)*
Optional compilation step for online runs.

**`post_processing_online(self, stdout_input: AnyStr) -> AbstractOutputStructure`**
Parse streaming output into a standard verdict structure.

## See also

- [Archive README](../../Archive/README.md) — Dockerfile and `tool.properties` conventions.
- [CLI Usage Guide](../Frontend/CLI/CLI_USAGE.md) — how monitors and their `params` are configured in YAML.
- [Infrastructure README](../README.md) — the other component base classes.
