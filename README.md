# MonitoringFace

**A Portable Platform for Runtime Monitoring.**

MonitoringFace is an extensible, Docker-container-based platform that lets runtime
verification (RV) tool authors provide a *unified interface* to their monitors,
(randomized) input generators, oracles, and benchmarks. The runtime verification
community has produced a wide variety of tools that differ in policy languages,
monitoring settings, input/output formats, and implementation languages. Rather
than forcing a common standard, MonitoringFace embraces this diversity and focuses
on **portability**, **reproducibility**, and **extensibility**: it abstracts away
installation and versioning via Docker, imposes no restriction on a monitor's input
or output format, and makes performance measurements and correctness checks
reproducible across machines.

## Architecture

MonitoringFace is structured around **two modules**:

- **[Archive](Archive/README.md)** — the *community-contributed* layer. It holds the
  Dockerfiles that package individual monitoring tools, oracles, generators, and
  converters; the Python wrapper classes that bind each of these to the
  infrastructure's abstract base classes; and the YAML configuration files (plus
  static case-study data) describing experiments.
- **[Infrastructure](Infrastructure/README.md)** — the *platform core*. It supplies
  the abstract base classes for the six component types below and the platform-level
  services shared by every experiment: the command-line interface (CLI/frontend),
  the orchestrator that resolves dependencies and drives execution, the format
  converters, and the evaluation logic for timing, memory, and correctness.

Users interact with the platform by writing an experiment YAML file and invoking the
CLI; the infrastructure then orchestrates the components registered in the archive.

### Component types

The Infrastructure defines abstract base classes for six kinds of components:

| Component | Role |
|-----------|------|
| **Monitor** | Wraps a monitoring tool; manages input pre-processing, compilation, execution, and output post-processing. |
| **Data Generator** | Produces input traces subject to parameters; typically randomized, with seeds for determinism. |
| **Policy Generator** | Produces input policies (e.g. MFOTL formulas) subject to parameters. |
| **Oracle** | Checks a monitor's output for correctness, possibly by invoking another trustworthy monitor. |
| **Case Study** | A workload of fixed (non-generated) traces and policies plus execution instructions. |
| **Converter** | Translates traces, policies, or verdicts between tool-specific formats during pre-/post-processing. |
| **Experiment** | Describes a set of tasks, selecting the generators, monitors, oracles, case studies, and converters to use. |

Community members instantiate a component by adding a **Dockerfile + Python wrapper
class** (monitors, oracles, generators, converters) or a **YAML configuration + test
data** (case studies, experiments) to the Archive.

## Integrated tools

MonitoringFace currently packages seven monitors. Six use fragments of metric
first-order dynamic/temporal logic (MFODL / MFOTL); the seventh, TeSSLa, belongs to
the stream runtime verification (SRV) family and demonstrates cross-community
extensibility.

| Tool | Notes | Language |
|------|-------|----------|
| **MonPoly** | MFOTL (RANF), aggregations, definitions, interpreted functions | OCaml |
| **VeriMon** | Formally verified MonPoly variant (MFODL); shares MonPoly's binary | OCaml / Isabelle |
| **DejaVu** | Past-only closed MFOTL via BDDs; consumes QTL | Scala |
| **WhyMon** | MFOTL with past + bounded future via PDTs; explainable verdicts | OCaml |
| **EnfGuard** | Enforcer for an MFOTL fragment; used here in monitoring mode (past-only) | OCaml |
| **TimelyMon** | Parallel, event-wise, possibly out-of-order; built on Timely Dataflow | Rust |
| **TeSSLa** | Stream runtime verification (recursive stream equations) | Scala / Rust |

The Archive additionally packages **WhyMyMon**, a visual frontend built on top of
these backends.

## Prerequisites

**Docker** must be installed and running. Download it from
[docker.com](https://www.docker.com/get-started). Recommended Docker resources:

- RAM: 6 GB
- 4 CPU cores
- Swap memory: 1 GB
- Disk space: 64 GB
- Under *Settings → Resources → File Sharing*, allow Docker to access the folder
  where MonitoringFace is located.

**Python 3.9 or higher** must be installed. Download it from
[python.org](https://www.python.org/downloads/).

## Installation

Clone the repository and install the Python dependencies:

```bash
python -m venv .venv
source .venv/bin/activate          # On Windows: .venv\Scripts\activate
pip install -r Infrastructure/requirements.txt
```

### GitHub authentication token (recommended)

To avoid rate limiting when pulling images and metadata from GitHub, add a personal
access token at `Infrastructure/environment/auth_token` (create the
`Infrastructure/environment/` folder if needed and place the raw token in a file
named `auth_token`).

## Running experiments

Make sure Docker is running and you have an internet connection. Experiments are
described by YAML files; configuration names are resolved relative to
`Archive/Experiments/` (and fetched from the remote repository if not found locally).

```bash
# Run a single experiment
python -m Infrastructure.main examples/example_synthetic_experiment.yaml

# Run a suite of experiments
python -m Infrastructure.main examples/experiments_suite.yaml

# Validate a configuration without building or running anything
python -m Infrastructure.main examples/example_synthetic_experiment.yaml --dry-run
```

### Command-line options

| Option | Effect |
|--------|--------|
| `--dry-run` | Validate the configuration without building or running anything. |
| `--verbose`, `-v` | Print detailed progress and the commands being executed. |
| `--debug` | Preserve transient scratch data (converted traces/policies) for each tool execution. |
| `--no-measure` | Disable the in-container `/usr/bin/time` measurement of time and memory. |
| `--suite` | Force the config to be treated as an experiment suite (otherwise auto-detected). |
| `--clean` | Keep only the latest result/analysis of this experiment. |
| `--clean-all` | Remove the entire results and analysis folders before running. |

See the **[CLI Usage Guide](Infrastructure/Frontend/CLI/CLI_USAGE.md)** for the full
YAML configuration reference.

## Execution pipeline

When the CLI runs a workload, it proceeds through five stages:

1. **Preprocessing** — convert generated or case-study inputs into each monitor's
   accepted trace/policy formats, using Converters.
2. **Compilation** — for *compiled* monitors (e.g. DejaVu), synthesize a binary from
   the policy. *Interpreted* monitors (e.g. MonPoly) skip this stage.
3. **Execution** — run the monitor on the prepared inputs.
4. **Post-processing** — convert the tool-specific verdict output into a standard
   output format consumable by oracles.
5. **Evaluation** — measure **performance** (each stage is timed separately; offline
   runs also measure peak memory of the monitor process alone) and, optionally,
   **correctness** by comparing each monitor's output against an oracle's ground truth.

Standardized output formats (after post-processing) are:

- **PropositionList** — a list of Booleans, one per time-point (propositional monitors; also DejaVu).
- **Verdicts** — a list of lists of assignments to the formula's free variables (MonPoly, VeriMon).
- **OOOVerdicts** — like Verdicts, but the outer list may refer to time-points in any order (TimelyMon).
- **PropositionTree** — a list of PDTs storing Boolean verdicts (WhyMon).

### Experiment types

- **Synthetic experiments** are produced by generators; you select and combine
  policy/trace generators and instantiate their parameters. Lists of parameter values
  yield parameterized families of experiments (parameter sweeps).
- **Case studies** are fixed benchmarks with given policies and traces — the format of
  choice for real-world traces.
- **Time-guarded** synthetic experiments regenerate inputs until a selected tool takes
  a target amount of time (e.g. "experiments that take VeriMon 5–10 s"); a running
  monitor can also be timed out.

## Project structure

```
MonitoringFace/
├── Infrastructure/                  # Platform core (abstract base classes + services)
│   ├── main.py                      # CLI entry point
│   ├── Frontend/                    # CLI and YAML parser
│   │   ├── CLI/                     # cli.py, cli_args.py, CLI_USAGE.md
│   │   └── Parser/                  # YamlParser
│   ├── Monitors/                    # BaseMonitorTemplate (monitor base class)
│   ├── Oracles/                     # AbstractOracleTemplate
│   ├── Builders/
│   │   ├── ProcessorBuilder/        # Generator/Converter/CaseStudy base classes
│   │   └── ToolBuilder/             # Docker image management
│   ├── BenchmarkBuilder/            # Orchestration / coordinator
│   ├── DataTypes/                   # Contracts, formats, path & fingerprint management
│   ├── DataLoader/                  # Local/remote benchmark resolution
│   ├── Analysis/                    # Automated result analysis
│   ├── requirements.txt
│   └── results/                     # Timestamped experiment results
├── Archive/                         # Community-contributed layer
│   ├── Docker/                      # Dockerfiles, grouped by category
│   │   ├── Tools/                   # Monitors/enforcers
│   │   ├── DataGenerators/  PolicyGenerators/
│   │   ├── DataConverters/  PolicyConverters/
│   │   ├── CaseStudies/  Utilities/
│   ├── Implementations/             # Python wrapper classes
│   │   ├── Monitors/  Oracles/
│   │   └── Builders/ProcessorBuilder/
│   └── Experiments/                 # YAML experiment & suite configs (+ case-study data)
│       ├── examples/
│       └── benchmark_paper/         # Configs reproducing the paper's use cases
└── README.md
```

## Example: a synthetic experiment

A single-experiment YAML selects monitors, an optional oracle, the data/policy
generators (via *contracts*), and the synthetic parameter ranges:

```yaml
experiment_name: test_synthetic_experiment

monitors:
  - identifier: TimelyMon
    name: TimelyMon 1
    branch: development
    params:
      worker: 1
      output_mode: 1
  - identifier: VeriMon
    name: VeriMon
    branch: master
  - identifier: MonPoly
    name: MonPoly
    branch: master

oracles:
  - identifier: VeriMonOracle
    name: VeriMonOracle
    monitor_name: VeriMon

runtime_constraints:
  upper_bound: 20            # time-guard: seconds per monitor

data_setup:
  type: SignatureContract
  SignatureContract:
    trace_length: 1000
    event_rate: 1000

policy_setup:
  type: MfotlPolicyContract
  MfotlPolicyContract:
    num_preds: 4
    prob_eand: 0

synthetic_config:
  experiment:
    num_operators: [5]       # lists sweep over parameter values
    num_fvs: [2]
    num_setting: [0, 1]
    num_data_set_sizes: [50]

tools_to_build:
  - TimelyMon 1
  - VeriMon
  - MonPoly

seeds:
  '[5, 2, 0]': [314159265, 87006]   # deterministic per-setting seeds
  '[5, 2, 1]': [314159265, 53339]
```

A **case study** instead points `data_setup` at a fixed workload:

```yaml
experiment_name: Nokia_case_study

monitors:
  - identifier: MonPoly
    name: MonPoly
    branch: master
    params:
      replayer: gen_data

data_setup:
  type: CaseStudy
  name: Nokia

tools_to_build:
  - MonPoly
```

An **experiment suite** runs several configurations in sequence:

```yaml
experiments:
  - path: examples/example_synthetic_experiment.yaml
    enabled: true
    description: "Basic synthetic experiment with Signature data generator"
  - path: examples/example_patterns.yaml
    enabled: true
    description: "Experiment using Patterns data generator"
  - path: examples/example_case_study.yaml
    enabled: false            # disabled without removing from the suite
    description: "Nokia case study benchmark"
```

## Reproducibility

Generators are deterministic by design or via seeds, and the platform records an
experiment-specific secure hash of all settings, so an experiment YAML acts as a
reproducible certificate. Components are packaged for both `amd64` and `arm64` and run
on Linux inside Docker regardless of host OS.

## Documentation

- **[CLI Usage Guide](Infrastructure/Frontend/CLI/CLI_USAGE.md)** — full command-line and YAML configuration reference.
- **[Archive README](Archive/README.md)** — how to package a tool (Dockerfile + `tool.properties`) and register it.
- **[Infrastructure README](Infrastructure/README.md)** — how to integrate a new component against the base classes.
- **[Monitors README](Infrastructure/Monitors/README.md)** — the monitor wrapper interface.
- **[Generators README](Infrastructure/Builders/ProcessorBuilder/README.md)** — the data/policy generator wrapper interface.

## Contributing

- **Adding a new tool** (monitor, generator, oracle, converter): provide a Dockerfile
  under `Archive/Docker/` and a wrapper class under `Archive/Implementations/`. See
  [Archive/README.md](Archive/README.md) and [Infrastructure/README.md](Infrastructure/README.md).
- **Adding a configuration option**: update the relevant contract/dataclass, document
  it in [CLI_USAGE.md](Infrastructure/Frontend/CLI/CLI_USAGE.md), and add an example.

## Troubleshooting

**Docker is not running / not available.** Start Docker before running experiments;
the CLI checks `docker info` on startup.

**Network connection is not available.** The CLI requires connectivity to pull images
and resolve configurations; check your connection (and `auth_token` for rate limits).

**Configuration error: …** A required section is missing or malformed. Validate with
`--dry-run`, or check YAML syntax with
`python -c "import yaml, sys; yaml.safe_load(open(sys.argv[1]))" my_experiment.yaml`.

**Module import error (e.g. `omegaconf` not found).** Install dependencies:
`pip install -r Infrastructure/requirements.txt`.

**Configuration file is unavailable.** Names are resolved relative to
`Archive/Experiments/`; check the path is correct (relative or absolute) and that the
file exists locally or in the remote repository.
