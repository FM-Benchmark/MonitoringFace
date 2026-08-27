# MonitoringFace CLI Documentation

## Overview

MonitoringFace is driven by a command-line interface that runs benchmark experiments
described in YAML configuration files. The CLI itself is a standard `argparse` program
([`cli.py`](cli.py)); the YAML files are loaded and composed with
**[Hydra](https://hydra.cc/) / [OmegaConf](https://omegaconf.readthedocs.io/)**, so
they support structured configs and variable interpolation
([`YamlParser`](../Parser/YamlParser.py)).

A configuration file describes both **build information** (which monitors to build,
from which branch/commit) and **experimental instructions** (the data/policy
generators or case study, the parameters, and any oracle). The platform then
orchestrates the components registered in the [Archive](../../../Archive/README.md).

## Invocation

```bash
python -m Infrastructure.main <config> [options]
```

The `config` argument is a YAML file name resolved **relative to
`Archive/Experiments/`**. The same resolution applies to single experiments and to
suites; if the file is not found locally, the platform attempts to fetch it from the
remote repository.

```bash
# Single experiment  ->  Archive/Experiments/examples/example_synthetic_experiment.yaml
python -m Infrastructure.main examples/example_synthetic_experiment.yaml

# Experiment suite    ->  Archive/Experiments/examples/experiments_suite.yaml
python -m Infrastructure.main examples/experiments_suite.yaml

# Validate without building or running anything
python -m Infrastructure.main examples/example_synthetic_experiment.yaml --dry-run
```

Suites are auto-detected (a top-level `experiments:` key); pass `--suite` to force it.

## Command-line options

| Option | Effect |
|--------|--------|
| `config` (positional) | YAML config name, resolved relative to `Archive/Experiments/`. |
| `--dry-run` | Validate the configuration; do not build or run anything. |
| `--verbose`, `-v` | Print detailed progress and the commands being executed. |
| `--debug` | Preserve the per-execution `scratch` data (converted traces/policies) that is otherwise deleted. |
| `--provenance` / `--no-provenance` | Store each tool's exact final inputs and a `provenance.json` manifest (sources, conversion commands, sha256 of both endpoints) under `results/<run>/provenance/<setting>/<tool>/`. Default on; `--debug` implies it. |
| `--no-measure` | Disable the in-container `/usr/bin/time` measurement of time and memory. |
| `--suite` | Force the config to be treated as an experiment suite (otherwise auto-detected). |
| `--clean` | After running, keep only the latest result/analysis folder for this experiment. |
| `--clean-all` | Remove the entire `results/` and `analysis_results/` folders before running. |
| `--analyze` | Run automated analysis on the results after execution (written to `analysis_results/`). |
| `-h`, `--help` | Show help and exit. |

Results are written to a timestamped folder under `Infrastructure/results/`.

---

## YAML configuration reference

### Single experiment

A single-experiment file is composed of the sections below. `monitors`, `data_setup`,
and `tools_to_build` are required; the rest are optional and apply as noted.

#### `experiment_name` (required)

```yaml
experiment_name: my_experiment      # used to name result/experiment folders
```

#### `runtime_setting` (optional)

```yaml
runtime_setting: offline            # 'offline' (default) or 'online'
```

#### `monitors` (required)

The monitors to build and (potentially) run. Each entry identifies a tool packaged in
the Archive and pins a version by `branch` **or** `commit`.

```yaml
monitors:
  - identifier: TimelyMon           # tool name as packaged in Archive/Docker/Tools
    name: TimelyMon 1               # unique label for this monitor instance
    branch: development             # build from a branch ...
    release: branch                 # optional: 'branch' (default) or 'release'
    params:                         # optional, monitor-specific (see below)
      worker: 1
      output_mode: 1
  - identifier: VeriMon
    name: VeriMon
    commit: 2924d26f95acf539b85f3e71d8518ebad9961983   # ... or pin an exact commit
```

- `identifier` and `name` are required; provide `branch` or `commit`.
- `name` must be unique — it is how the monitor is referenced in `tools_to_build`,
  `oracles`, and `generation_constraints`. Reuse the same `identifier` with different
  `name`s and `params` to compare configurations or versions of one tool.
- `params` are passed to the monitor's wrapper class. They are tool-specific; e.g.
  TimelyMon accepts `worker`, `output_mode`, and `mode` (e.g. `oootps`), while MonPoly
  accepts `replayer`. For online runs, `params` may carry an
  `OnlineExperimentContractTool` block (see [Online experiments](#online-experiments)).

#### `tools_to_build` (required)

The subset of monitor `name`s to actually build and run for this experiment.

```yaml
tools_to_build:
  - TimelyMon 1
  - VeriMon
```

#### `oracles` and `oracle` (optional)

Define available oracles in `oracles`, then activate one with `oracle`.

```yaml
oracles:
  - identifier: VeriMonOracle       # oracle name as packaged in Archive
    name: VeriMonOracle             # unique label
    monitor_name: VeriMon           # monitor this oracle composes with (if any)
    params:
      replayer: gen_data

oracle:
  enabled: true                     # set false (or omit the section) to skip checking
  name: VeriMonOracle               # which entry from `oracles` to use as ground truth
```

When enabled, each monitor's output is compared against the oracle's ground truth and
reported as correct / wrong.

#### `data_setup` (required)

Selects the trace source. The `type` is either a special source (`CaseStudy`,
`Script`) or a **data-generator contract**. For a contract, the platform derives the
generator from the contract name by replacing `Contract` with `Generator`
(e.g. `SignatureContract` → `SignatureGenerator`), and reads the contract's fields from
a nested block named after the `type`.

```yaml
# Synthetic trace generation
data_setup:
  type: SignatureContract
  SignatureContract:
    trace_length: 1000
    event_rate: 1000
```

```yaml
# Fixed case-study trace
data_setup:
  type: CaseStudy
  name: Nokia                       # a case study packaged in Archive
  fixed: false                      # optional; true copies fixed data instead of generating
```

Available data-generator contracts (`type` values) and their key fields are listed in
[Data-generator contracts](#data-generator-contracts).

#### `policy_setup` (optional, required for synthetic experiments)

Selects the policy source, analogous to `data_setup`
(`MfotlPolicyContract` → `MfotlPolicyGenerator`).

```yaml
policy_setup:
  type: MfotlPolicyContract
  MfotlPolicyContract:
    num_preds: 4
    prob_eand: 0
```

#### `synthetic_config` (required for synthetic experiments)

The synthetic parameter ranges. Only the `experiment` block is read; lists produce a
parameterized family (see [Parameter sweeps](#parameter-sweeps)).

```yaml
synthetic_config:
  experiment:
    num_operators: [5]              # formula size(s)
    num_fvs: [2]                    # number(s) of free variables
    num_setting: [0, 1]            # setting index/indices (distinct seeded instances)
    num_data_set_sizes: [50]        # number(s) of traces per setting
```

> Some configs also carry `data_source:`/`policy_source:` keys here. They are
> **cosmetic** — the generators are determined by `data_setup.type` and
> `policy_setup.type`, not by these keys.

#### `runtime_constraints` (optional)

Per-run timeout for monitors, in seconds.

```yaml
runtime_constraints:
  upper_bound: 30                   # kill a monitor run after 30 s
```

#### `generation_constraints` (optional — time-guarded generation)

Regenerate random experiments until a selected tool's runtime falls in `[lower_bound,
upper_bound]` seconds. This excludes trivial or intractable instances.

```yaml
generation_constraints:
  lower_bound: null                 # null for no lower bound
  upper_bound: 150
  guard_type: Monitor               # 'Monitor', 'Oracle', or 'Generator'
  guard_name: TimelyMon 4           # the monitor whose runtime is guarded
```

#### `repeats` (optional)

```yaml
repeats: 3                          # repetitions per experiment (default 1)
```

#### `seeds` (optional — reproducibility)

Fix the generator seeds per synthetic setting. Each key is the stringified setting
tuple `[num_operators, num_fvs, num_setting]` (omit `num_fvs` for generators without
free variables); each value is `[policy_seed, trace_seed]`.

```yaml
seeds:
  '[5, 2, 0]': [314159265, 87006]
  '[5, 2, 1]': [314159265, 53339]
```

### Online experiments

Set `runtime_setting: online` and add a global `OnlineExperimentContractGeneral`
section; per-monitor online behavior goes in `params.OnlineExperimentContractTool`.

```yaml
runtime_setting: online

OnlineExperimentContractGeneral:
  data_source_type: file            # 'file' or 'script'
  mode: real-time                   # 'real-time' or 'accelerated'
  timestamp_units: milliseconds     # 'milliseconds', 'microseconds', or 'seconds'
  accumulative_time: 220            # cumulative-latency budget
  maximum_latency: 50000            # per-step latency budget
  # batch_delimiter: ...            # optional

monitors:
  - identifier: TimelyMon
    name: TimelyMon
    commit: 3ff38d25fba09eb7810793faf6eddfcbe5648b99
    params:
      worker: 1
      output_mode: 1
      OnlineExperimentContractTool:
        format: csv                       # 'csv' or 'log'
        response_mode: event-count        # 'event-count' or 'current-timepoint'
        output_collection_mode: before-delimiter   # required
        input_aggregation_number: 1       # optional
        input_aggregation_pattern: ">W"   # optional
        # latency_marker: ...             # optional
        # warm_up_input: ...              # optional

data_setup:
  type: CaseStudy
  name: NokiaCsvOnline
```

### Experiment suite

A suite references several experiment configs (paths relative to `Archive/Experiments/`);
disabled entries are skipped.

```yaml
experiments:
  - path: examples/example_synthetic_experiment.yaml
    enabled: true
    description: "Basic synthetic experiment with Signature data generator"
  - path: examples/example_patterns.yaml
    enabled: true
    description: "Patterns data generator experiment"
  - path: examples/example_case_study.yaml
    enabled: false                  # kept in the suite but not run
    description: "Nokia case study"
```

---

## Contract reference

Contracts are Python dataclasses; their fields are the options you may set in the
nested block under `data_setup`/`policy_setup`. Unset fields fall back to defaults.
Source: `Archive/Implementations/Builders/ProcessorBuilder/{DataGenerators,PolicyGenerators}/`.

### Data-generator contracts

**`SignatureContract`** → `SignatureGenerator` (signature-driven random traces)

| Field | Default | Notes |
|-------|---------|-------|
| `trace_length` | `null` | number of time points |
| `event_rate` | `1000` | events per time point |
| `seed` | `null` | trace seed |
| `index_rate` | `null` | |
| `time_stamp` | `null` | timestamp increment |
| `signature` | `""` | inline signature |
| `sample_queue` | `null` | |
| `fresh_value_rate` | `null` | rate of fresh values |
| `domain` | `null` | value-domain size |
| `string_length` | `null` | |
| `watermarks` | `null` | emit watermarks (out-of-order traces) |

**`PatternDataContract`** → `PatternDataGenerator` (pattern-shaped traces)

| Field | Default | Notes |
|-------|---------|-------|
| `trace_length` | `1000` | |
| `event_rate` | `1000` | |
| `seed` / `index_rate` / `time_stamp` / `watermarks` | `null` | as above |
| `linear` / `star` / `triangle` | `linear=1` | pattern shape selector (set one) |
| `pattern` | `null` | explicit pattern string (alternative to the above) |
| `violations` | `1.0` | violation rate |
| `interval` | `null` | |
| `zipf` | `"x=1.5+3,z=2"` | Zipf distribution spec |
| `prob_a` / `prob_b` / `prob_c` | `0.2` / `0.3` / `0.5` | event probabilities |

**`DataGolfContract`** → `DataGolfGenerator` (policy-aware "Data Golf" traces; can act as an oracle)

| Field | Default | Notes |
|-------|---------|-------|
| `sig_file` / `formula` / `path` | `""` | inputs the generator builds traces from |
| `trace_length` | `10` | |
| `seed` | `null` | |
| `oracle` | `false` | also emit ground truth |
| `no_rewrite` | `null` | |
| `tup_ts` | `[0..4]` | time points to populate |
| `tup_amt` | `10` | tuples per time point |
| `tup_val` | `0` | tuple value strategy |

### Policy-generator contracts

**`MfotlPolicyContract`** → `MfotlPolicyGenerator` (random MFOTL formulas)

| Field | Default | Notes |
|-------|---------|-------|
| `num_preds` | `4` | number of predicates |
| `max_arity` | `4` | maximum predicate arity |
| `size` | `null` | formula size |
| `seed` | `null` | policy seed |
| `non_zero` | `false` | forbid zero-length intervals |
| `aggregation` | `false` | allow aggregations |
| `lb` / `ub` / `delta` | `0` / `5` / `30` | interval bounds and delta |
| `unbounded` | `false` | allow unbounded future |
| `regex` | `false` | allow regex / match operators |
| `prob_*` | `null` | relative operator frequencies (see below) |

Operator frequency fields (`prob_*`, unset = generator default): `prob_and`, `prob_or`,
`prob_eand`, `prob_nand`, `prob_rand`, `prob_prev`, `prob_once`, `prob_next`,
`prob_eventually`, `prob_since`, `prob_until`, `prob_exists`, `prob_let`, `prob_aggreg`,
`prob_matchP`, `prob_matchF`. Set an operator's probability to `0` to exclude it
(e.g. `prob_let: 0` to forbid let-bindings).

Other policy generators packaged in the Archive include `GenFmaContract`
(→ `GenFmaGenerator`), `PatternPolicyContract` (→ `PatternPolicyGenerator`), and
`ImmediatePolicyContract` (→ `ImmediatePolicyGenerator`). Consult their contract files
for fields.

---

## Worked examples

The complete, runnable versions of these live under `Archive/Experiments/`:

| Config | Demonstrates |
|--------|--------------|
| [`examples/example_synthetic_experiment.yaml`](../../../Archive/Experiments/examples/example_synthetic_experiment.yaml) | Synthetic experiment with the Signature generator, MFOTL policies, and a VeriMon oracle. |
| [`examples/example_patterns.yaml`](../../../Archive/Experiments/examples/example_patterns.yaml) | Patterns generator + time-guarded generation. |
| [`examples/example_case_study.yaml`](../../../Archive/Experiments/examples/example_case_study.yaml) | A fixed case-study (Nokia) benchmark. |
| [`examples/experiments_suite.yaml`](../../../Archive/Experiments/examples/experiments_suite.yaml) | Grouping several experiments into a suite. |
| [`benchmark_paper/timely_regression_testing.yaml`](../../../Archive/Experiments/benchmark_paper/timely_regression_testing.yaml) | Comparing two pinned commits of one tool (`repeats`, `seeds`). |
| [`benchmark_paper/timelymon_online_nokia.yaml`](../../../Archive/Experiments/benchmark_paper/timelymon_online_nokia.yaml) | An online experiment on a real-world trace. |

### Parameter sweeps

Lists in `synthetic_config.experiment` expand into a family of experiments over all
combinations:

```yaml
synthetic_config:
  experiment:
    num_operators: [3, 5, 7, 10]    # four formula sizes
    num_fvs: [1, 2, 3]              # three free-variable counts
    num_data_set_sizes: [50, 100, 500]
```

Pin `seeds` per setting tuple to keep the family reproducible across runs.

## Creating a new experiment

1. Copy an existing config from `Archive/Experiments/examples/` and edit it.
2. Validate it: `python -m Infrastructure.main my_experiment.yaml --dry-run`.
3. Run it (optionally verbose): `python -m Infrastructure.main my_experiment.yaml -v`.
4. Inspect results under `Infrastructure/results/<experiment>_<timestamp>/`; add
   `--analyze` to produce summary CSVs under `Infrastructure/analysis_results/`.

## Where to look in the code

- [`cli.py`](cli.py) / [`cli_args.py`](cli_args.py) — CLI parsing and options.
- [`../Parser/YamlParser.py`](../Parser/YamlParser.py) — the authoritative YAML schema.
- `Infrastructure/DataTypes/Contracts/` and
  `Archive/Implementations/Builders/ProcessorBuilder/**/...Contract.py` — contract fields.
- [Top-level README](../../../README.md) and [Infrastructure README](../../README.md) —
  architecture and how to add new components.
