import importlib
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from omegaconf import OmegaConf, DictConfig
from hydra import compose, initialize_config_dir
from hydra.core.global_hydra import GlobalHydra

from Infrastructure.BenchmarkBuilder.Coordinator.CaseStudyCoordinator import CaseStudyCoordinator
from Infrastructure.BenchmarkBuilder.Coordinator.Coordinator import Coordinator
from Infrastructure.BenchmarkBuilder.Coordinator.ScriptCoordinator import ScriptCoordinator
from Infrastructure.BenchmarkBuilder.Coordinator.SyntheticDataCoordinator import SyntheticDataCoordinator
from Infrastructure.Builders.ProcessorBuilder.CaseStudiesGenerators.CaseStudyCopyGenerator import CaseStudyCopyGenerator
from Infrastructure.Builders.ProcessorBuilder.CaseStudiesGenerators.CaseStudyImageGenerator import CaseStudyImageGenerator
from Infrastructure.Builders.ProcessorBuilder.DataGenerators.DataGeneratorTemplate import DataGeneratorTemplate
from Infrastructure.Builders.ProcessorBuilder.PolicyGenerators.PolicyGeneratorTemplate import PolicyGeneratorTemplate

from Infrastructure.Builders.ToolBuilder.ToolManager import ToolManager
from Infrastructure.DataTypes.Contracts.SubContracts.ScriptSetupContract import ScriptSetupContract
from Infrastructure.Frontend.CLI.cli_args import CLIArgs
from Infrastructure.DataTypes.Contracts.AbstractContract import AbstractContract
from Infrastructure.DataTypes.Contracts.SubContracts.CaseStudyContract import CaseStudySetupContract
from Infrastructure.DataTypes.Contracts.SubContracts.SyntheticContract import SyntheticExperiment
from Infrastructure.DataTypes.Contracts.SubContracts.TimeBounds import TimeGuardingTool, TimeConstraints, GenerationConstraints, RunTimeConstraints
from Infrastructure.DataTypes.PathManager.PathManager import PathManager
from Infrastructure.DataTypes.Types.custome_type import BranchOrRelease, OnlineOffline, online_offline_from_string, \
    DataSourceType, TimeUnits, FormatType, ResponseMode, InputSpeed
from Infrastructure.Monitors.MonitorManager import MonitorManager
from Infrastructure.Oracles.OracleManager import OracleManager
from Infrastructure.constants import PATH_TO_NAMED_EXPERIMENT
from Infrastructure.DataTypes.Contracts.OnlineExperimentContract import OnlineExperimentContractGeneral, OnlineExperimentContractTool


class YamlParserException(Exception):
    pass


class YamlParser:
    def __init__(self, yaml_path: str, path_manager: PathManager, path_to_build: str = None,
                 path_to_experiments: str = None):
        self.yaml_path = os.path.abspath(yaml_path)
        self.config_dir = os.path.dirname(self.yaml_path)
        self.config_name = os.path.splitext(os.path.basename(self.yaml_path))[0]
        self.path_manager = path_manager

        your_path_to_mfb = os.getcwd()
        self.path_to_project = your_path_to_mfb
        self.path_to_build = path_to_build or f"{your_path_to_mfb}/Infrastructure/build"
        self.path_to_experiments = path_to_experiments or f"{your_path_to_mfb}/Infrastructure/experiments"

        os.makedirs(self.path_to_build, exist_ok=True)
        os.makedirs(self.path_to_experiments, exist_ok=True)

        self.cfg = self._load_config()

    def _load_config(self) -> DictConfig:
        GlobalHydra.instance().clear()
        try:
            initialize_config_dir(config_dir=self.config_dir, version_base=None)
            cfg = compose(config_name=self.config_name)
            return cfg
        except Exception as e:
            raise YamlParserException(f"Error loading configuration: {e}")
        finally:
            pass

    @staticmethod
    def _parse_branch_or_release(value: str) -> BranchOrRelease:
        value_lower = value.lower()
        if value_lower == "branch":
            return BranchOrRelease.Branch
        elif value_lower == "release":
            return BranchOrRelease.Release
        else:
            raise YamlParserException(f"Invalid branch_or_release value: {value}. Must be 'branch' or 'release'")

    @staticmethod
    def _parse_time_guarding_tool(value: str) -> TimeGuardingTool:
        value_lower = value.lower()
        if value_lower == "monitor":
            return TimeGuardingTool.Monitor
        elif value_lower == "oracle":
            return TimeGuardingTool.Oracle
        elif value_lower == "generator":
            return TimeGuardingTool.Generator
        else:
            raise YamlParserException(f"Invalid guard_type value: {value}")

    def parse_tool_manager(self, cli_args: CLIArgs) -> ToolManager:
        if 'monitors' not in self.cfg:
            raise YamlParserException("Missing 'tools' section in YAML configuration")

        runtime_setting = OnlineOffline.Offline if 'runtime_setting' not in self.cfg else online_offline_from_string(self.cfg['runtime_setting'])

        tools_to_build = []
        for tool in self.cfg.monitors:
            name = tool.get('identifier')
            branch = tool.get('branch')
            release = tool.get('release', 'branch')
            commit = tool.get('commit')

            if not name:
                raise YamlParserException(f"Tool configuration missing 'name': {tool}")
            if not name and not commit:
                raise YamlParserException(f"Tool configuration missing 'branch': {tool}")

            tools_to_build.append((name, branch, commit, self._parse_branch_or_release(release)))

        return ToolManager(tools_to_build=tools_to_build, path_to_project=self.path_to_project, cli_args=cli_args, runtime_setting=runtime_setting)

    def parse_seeds(self) -> Optional[Dict[str, Tuple[int, int]]]:
        if 'seeds' not in self.cfg:
            return None
        return OmegaConf.to_container(self.cfg.seeds, resolve=True)

    @staticmethod
    def _parse_data_generators(path_to_module, name: str) -> DataGeneratorTemplate:
        print(f"-> Attempting to initialize Policy Generator {name}")
        available = _discover_names(f"{path_to_module}/Archive", "DataGenerators")
        if name in available:
            cls = _retrieve_module("DataGenerators", name)
            build_cls = cls(name=name, path_to_build=f"{path_to_module}")
            print("    -> (Success)")
            return build_cls
        else:
            raise YamlParserException(f"Invalid DataGenerator {name} not in {available}")

    @staticmethod
    def _parse_case_study_generator(path_to_module, name: str) -> CaseStudyImageGenerator:
        print(f"-> Attempting to initialize Case Study Generator {name}")
        build_cls = CaseStudyImageGenerator(name=name, path_to_build=path_to_module)
        print("    -> (Success)")
        return build_cls

    def parse_data_setup(self) -> AbstractContract:
        if 'data_setup' not in self.cfg:
            raise YamlParserException("Missing 'data_setup' section in YAML configuration")

        data_setup = self.cfg.data_setup
        data_contract_name = data_setup.get('type')
        if data_contract_name.lower() == "casestudy":
            fixed = bool(data_setup.get('fixed', False))
            return CaseStudySetupContract(name=data_setup.get('name'), fixed=fixed)
        elif data_contract_name.lower() == "script":
            fixed = bool(data_setup.get('fixed', False))
            script_name = data_setup.get('script_name')
            return ScriptSetupContract(name=data_setup.get('name'), fixed=fixed, script_name=script_name)
        else:
            folder_files = _discover_contract_names(self.path_to_project + "/Archive/Implementations", "DataGenerators")
            if _contract_names(folder_files, data_contract_name):
                folder = _folder_name_from_contract(folder_files, data_contract_name)
                config = OmegaConf.to_container(data_setup.get(data_contract_name, {}), resolve=True)
                contract = _retrieve_contract("DataGenerators", folder, data_contract_name)
                return contract(**config)
            else:
                raise YamlParserException(f"Invalid data_setup type: {data_contract_name}")

    @staticmethod
    def _parse_policy_generators(path_to_module, name: str) -> PolicyGeneratorTemplate:
        print(f"-> Attempting to initialize Policy Generator {name}")
        available = _discover_names(f"{path_to_module}/Archive", "PolicyGenerators")
        if name in available:
            cls = _retrieve_module("PolicyGenerators", name)
            build_cls = cls(name=name, path_to_build=f"{path_to_module}")
            print("    -> (Success)")
            return build_cls
        else:
            raise YamlParserException(f"Invalid Policy Generator {name} not in {available}")

    def parse_policy_setup(self):
        if 'policy_setup' not in self.cfg:
            return None

        policy_setup = self.cfg.policy_setup
        data_contract_name = policy_setup.get('type')

        folder_files = _discover_contract_names(self.path_to_project + "/Archive/Implementations", "PolicyGenerators")
        if _contract_names(folder_files, data_contract_name):
            folder = _folder_name_from_contract(folder_files, data_contract_name)
            config = OmegaConf.to_container(policy_setup.get(data_contract_name, {}), resolve=True)
            contract = _retrieve_contract("PolicyGenerators", folder, data_contract_name)
            return contract().instantiate_contract(config)
        else:
            raise YamlParserException(f"Invalid Policy Generator Contract: {data_contract_name}")

    def parse_monitor_manager(self, tool_manager: ToolManager) -> MonitorManager:
        if 'monitors' not in self.cfg:
            raise YamlParserException("Missing 'monitors' section in YAML configuration")

        monitors_to_build = []
        for monitor in self.cfg.monitors:
            monitor_dict = OmegaConf.to_container(monitor, resolve=True)
            identifier = monitor_dict.get('identifier')
            name = monitor_dict.get('name')
            branch = monitor_dict.get('branch')
            commit = monitor_dict.get('commit')
            params = self.parse_tool_params(monitor_dict)

            if not identifier or not name or (not branch and not commit):
                raise YamlParserException(f"Monitor configuration missing required fields: {monitor_dict}")

            if 'path_to_project' not in params:
                params['path_to_project'] = self.path_to_project
            monitors_to_build.append((identifier, name, branch, commit, params))

        return MonitorManager(tool_manager=tool_manager, monitors_to_build=monitors_to_build, path_to_archive=f"{self.path_to_project}/Archive")

    def parse_tool_params(self, monitor_dict):
        params = monitor_dict.get('params', {})
        params = dict(params) if params is not None else {}

        raw_tool_contract = params.get("OnlineExperimentContractTool")
        if raw_tool_contract is None:
            return params

        raw = OmegaConf.to_container(raw_tool_contract, resolve=True) if not isinstance(raw_tool_contract, dict) else raw_tool_contract

        fmt_raw = raw.pop("format", None)
        if fmt_raw is None:
            raise YamlParserException("Missing 'format' in OnlineExperimentContractTool configuration")
        fmt = FormatType.CSV if str(fmt_raw).lower() == "csv" else FormatType.LOG

        resp_raw = raw.pop("response_mode", None)
        resp_l = str(resp_raw).lower()
        if resp_l == "current-timepoint":
            response_mode = ResponseMode.CURRENT_TIMEPOINT
        else:
            response_mode = ResponseMode.EVENT_COUNT

        output_collection = raw.pop("output_collection_mode", None)
        if output_collection is None:
            raise YamlParserException("Missing 'output_collection_mode' in OnlineExperimentContractTool configuration")

        input_aggregation_number = raw.pop("input_aggregation_number", None)
        input_aggregation_pattern = raw.pop("input_aggregation_pattern", None)
        latency_marker = raw.pop("latency_marker", None)
        warm_up_input = raw.pop("warm_up_input", None)

        params.pop("OnlineExperimentContractTool", None)
        params["OnlineExperimentContractTool"] = OnlineExperimentContractTool(
            formatting=fmt,
            response_mode=response_mode,
            input_aggregation_number=input_aggregation_number,
            input_aggregation_pattern=input_aggregation_pattern,
            latency_marker=latency_marker,
            output_collection_mode=output_collection,
            warm_up_input=warm_up_input,
        )
        return params

    def parse_oracle_manager(self, monitor_manager: MonitorManager) -> Optional[OracleManager]:
        if 'oracles' not in self.cfg or not self.cfg.oracles:
            return None

        oracles_to_build = []
        for oracle in self.cfg.oracles:
            oracle_dict = OmegaConf.to_container(oracle, resolve=True)
            identifier = oracle_dict.get('identifier')
            name = oracle_dict.get('name')
            monitor_name = oracle_dict.get('monitor_name')
            params = oracle_dict.get('params', {})

            if not identifier or not name:
                raise YamlParserException(f"Oracle configuration missing required fields: {oracle_dict}")

            oracles_to_build.append((name, identifier, monitor_name, params))

        return OracleManager(oracles_to_build=oracles_to_build, monitor_manager=monitor_manager, path_to_archive=f"{self.path_to_project}/Archive")

    def parse_synthetic_experiment(self):
        if 'synthetic_config' not in self.cfg:
            raise YamlParserException("Missing 'synthetic_config' for synthetic benchmark")

        synthetic_config = self.cfg.synthetic_config

        experiment_config = synthetic_config.get('experiment', {})
        experiment_dict = OmegaConf.to_container(experiment_config, resolve=True)
        experiment = SyntheticExperiment(
            num_operators=experiment_dict.get('num_operators', [5]),
            num_fvs=experiment_dict.get('num_fvs', [0]),
            num_setting=experiment_dict.get('num_setting', [0]),
            num_data_set_sizes=experiment_dict.get('num_data_set_sizes', [50])
        )
        return experiment

    def parse_constraints(self, monitor_manager: MonitorManager) -> TimeConstraints:
        generation = self.parse_generation_constraints(monitor_manager)
        runtime = self.parse_runtime_constraints()
        return TimeConstraints(run_time_constraints=runtime, generation_constraints=generation)

    def parse_generation_constraints(self, monitoring_manager: MonitorManager) -> Optional[GenerationConstraints]:
        if 'generation_constraints' not in self.cfg:
            return GenerationConstraints()

        constr_config = self.cfg.get('generation_constraints', {})
        constr_dict = OmegaConf.to_container(constr_config, resolve=True)

        guard_type_str = constr_dict.get('guard_type')
        guard_name = constr_dict.get('guard_name')
        cond = guard_type_str and guard_type_str.lower() == 'monitor' and not guard_name
        guard = monitoring_manager.get_monitor(guard_name) if cond else None
        lower_bound = constr_dict.get('lower_bound')
        upper_bound = constr_dict.get('upper_bound')

        guard_type = self._parse_time_guarding_tool(guard_type_str) if guard_type_str else None
        return GenerationConstraints(
            guarding_tool=guard_type, guard=guard, lower_bound=lower_bound, upper_bound=upper_bound
        )

    def parse_runtime_constraints(self) -> Optional[RunTimeConstraints]:
        if 'runtime_constraints' not in self.cfg:
            return RunTimeConstraints()

        upper_bound = self.cfg.get('runtime_constraints', {}).get('upper_bound')
        return RunTimeConstraints(upper_bound=float(upper_bound))

    def get_tools_to_build(self) -> List[str]:
        tools = self.cfg.get('tools_to_build', [])
        return OmegaConf.to_container(tools, resolve=True) if tools else []

    def get_oracle_config(self) -> Optional[str]:
        oracle_config = self.cfg.get('oracle', {})
        if isinstance(oracle_config, dict):
            oracle_dict = oracle_config
        else:
            oracle_dict = OmegaConf.to_container(oracle_config, resolve=True)

        if not oracle_dict:
            return None

        if oracle_dict.get('enabled', False):
            return oracle_dict.get('name')
        return None

    def get_repeat_experiments(self) -> int:
        if 'repeats' not in self.cfg:
            return 1
        return self.cfg.get('repeats')

    def parse_experiment(self, cli_args: CLIArgs, experiment_name) -> Tuple[Coordinator, MonitorManager, List[str], int]:
        tool_manager = self.parse_tool_manager(cli_args=cli_args)
        monitor_manager = self.parse_monitor_manager(tool_manager)
        oracle_manager = self.parse_oracle_manager(monitor_manager)
        oracle_name = self.get_oracle_config()
        oracle = oracle_manager.get_oracle(oracle_name) if oracle_name else None
        constraints = self.parse_constraints(monitor_manager)
        runtime_settings = self.runtime_setting()

        online_experiments_settings = self.parse_online_experiment_contract()
        data_setup = self.parse_data_setup()
        if isinstance(data_setup, ScriptSetupContract):
            coordinator = ScriptCoordinator(
                path_manager=self.path_manager, script_contract=data_setup,
                online_experiment_settings=online_experiments_settings)
        elif isinstance(data_setup, CaseStudySetupContract):
            self.path_manager.add_path(PATH_TO_NAMED_EXPERIMENT, f"{self.path_to_experiments}/{experiment_name}")
            generator = (CaseStudyCopyGenerator(name=data_setup.name, path_to_project=self.path_to_project)
                         if data_setup.fixed else CaseStudyImageGenerator(data_setup.name, self.path_to_project))
            coordinator = CaseStudyCoordinator(
                generator=generator, data_setup=data_setup,
                path_manager=self.path_manager, constraints=constraints,
                oracle=oracle, runtime_settings=runtime_settings,
                online_settings=online_experiments_settings
            )
        else:
            data_contract_name = data_setup.__class__.__name__.replace('Contract', 'Generator')
            data_generator = self._parse_data_generators(self.path_to_project, data_contract_name)
            policy_setup = self.parse_policy_setup()
            policy_contract_name = policy_setup.__class__.__name__.replace('Contract', 'Generator')
            policy_generator = self._parse_policy_generators(self.path_to_project, policy_contract_name)

            synthetic_experiment = self.parse_synthetic_experiment()
            seeds = self.parse_seeds()
            if seeds:
                # seeds may be keyed per full setting incl. data-set size
                # ([ops, fvs, setting, size]) OR size-independent
                # ([ops, fvs, setting]) - retrieve_setting_seeds resolves both,
                # so either exact count is valid
                base_len = (max(1, len(synthetic_experiment.num_setting))
                            * max(1, len(synthetic_experiment.num_operators))
                            * max(1, len(synthetic_experiment.num_fvs)))
                settings_len = base_len * max(1, len(synthetic_experiment.num_data_set_sizes))
                print("    -> Seeds length: ", len(seeds), " | Experiment settings length: ", settings_len)
                if len(seeds) not in (settings_len, base_len):
                    raise YamlParserException(
                        f"Seeds length {len(seeds)} matches neither the number of experiment "
                        f"settings including data-set sizes ({settings_len}) nor the "
                        f"size-independent setting count ({base_len})")

            coordinator = SyntheticDataCoordinator(
                experiment=synthetic_experiment, data_setup=data_setup,
                data_source=data_generator, policy_setup=policy_setup,
                policy_source=policy_generator, oracle=oracle,
                constraints=constraints, path_manager=self.path_manager,
                seeds=seeds, runtime_settings=runtime_settings,
                online_settings=online_experiments_settings
            )
        return coordinator, monitor_manager, self.get_tools_to_build(), self.get_repeat_experiments()

    def runtime_setting(self) -> OnlineOffline:
        if 'runtime_setting' not in self.cfg:
            return online_offline_from_string("offline")
        return online_offline_from_string(self.cfg['runtime_setting'])

    def parse_online_experiment_contract(self) -> OnlineExperimentContractGeneral:
        if "OnlineExperimentContractGeneral" not in self.cfg:
            return None

        online_raw = self.cfg.get("OnlineExperimentContractGeneral", self.cfg)
        online_dict = OmegaConf.to_container(online_raw, resolve=True)

        dst_type_str = online_dict.get('data_source_type')
        dst_type = DataSourceType.FILE if str(dst_type_str).lower() == 'file' else DataSourceType.SCRIPT

        max_lat = online_dict.get('maximum_latency')
        acc_lat = online_dict.get('accumulative_time')
        max_lat = int(max_lat) if max_lat is not None else None
        acc_lat = int(acc_lat) if acc_lat is not None else None

        ts_units_str = online_dict.get('timestamp_units')
        ts_units_low = str(ts_units_str).lower() if ts_units_str is not None else 'milliseconds'
        if ts_units_low.startswith('milliseconds'):
            ts_units = TimeUnits.MILLISECONDS
        elif ts_units_low.startswith('microseconds'):
            ts_units = TimeUnits.MICROSECONDS
        else:
            ts_units = TimeUnits.SECONDS

        mode_str = online_dict.get('mode', 'accelerated')
        mode = InputSpeed.ACCELERATED if str(mode_str).lower() == 'accelerated' else InputSpeed.REAL_TIME

        batch_delim = online_dict.get('batch_delimiter')
        return OnlineExperimentContractGeneral(
            data_source_type=dst_type,
            maximum_latency=max_lat,
            accumulated_latency=acc_lat,
            timestamp_units=ts_units,
            batch_delimiter=batch_delim,
            mode=mode
        )


class ExperimentSuiteParser:
    def __init__(self, path_to_project: str, config_name: str):
        relative_dir = os.path.dirname(config_name)
        if relative_dir:
            self.config_dir = f"{path_to_project}/Archive/Experiments/{relative_dir}"
        else:
            self.config_dir = f"{path_to_project}/Archive/Experiments"
        self.config_name = os.path.basename(config_name)
        self.cfg = self._load_config()

    def _load_config(self) -> DictConfig:
        GlobalHydra.instance().clear()
        try:
            initialize_config_dir(config_dir=self.config_dir, version_base=None)
            cfg = compose(config_name=self.config_name)
            return cfg
        except Exception as e:
            raise YamlParserException(f"Error loading suite configuration: {e}")

    def get_experiment_paths(self) -> List[str]:
        if 'experiments' not in self.cfg:
            raise YamlParserException("Missing 'experiments' section in suite YAML")

        experiment_paths = []
        experiments_list = OmegaConf.to_container(self.cfg.experiments, resolve=True)
        for exp_config in experiments_list:
            if exp_config.get('enabled', True):
                rel_path = exp_config.get('path')
                if not rel_path:
                    raise YamlParserException(f"Missing 'path' in experiment configuration: {exp_config}")
                experiment_paths.append(rel_path)
        return experiment_paths


def _discover_names(path_to_infra_, category):
    names = []
    for item in Path(f"{path_to_infra_}/Implementations/Builders/ProcessorBuilder/{category}").iterdir():
        if not item.is_dir() or item.name.startswith('_') or item.name == '__pycache__':
            continue
        names.append(item.name)
    return names


def _retrieve_module(category, name):
    return getattr(importlib.import_module(f"Archive.Implementations.Builders.ProcessorBuilder.{category}.{name}.{name}"), name)


def _discover_contract_names(path_to_infra_: str, category: str) -> List[str]:
    contracts = []
    category_path = Path(f"{path_to_infra_}/Builders/ProcessorBuilder/{category}")
    for item in category_path.iterdir():
        if not item.is_dir() or item.name.startswith('_') or item.name == '__pycache__':
            continue
        for file in item.iterdir():
            if file.suffix == '.py' and 'Contract' in file.stem:
                contracts.append((item.name, file.stem))
    return contracts


def _contract_names(folder_file_tuples, name) -> bool:
    return name in map(lambda x: x[1], folder_file_tuples)


def _folder_name_from_contract(folder_file_tuples, contract_name) -> Optional[str]:
    for folder_name, file_name in folder_file_tuples:
        if file_name == contract_name:
            return folder_name
    raise ValueError(f"Contract {contract_name} folder not found")


def _retrieve_contract(category: str, folder_name: str, contract_class_name: str):
    module = importlib.import_module(
        f"Archive.Implementations.Builders.ProcessorBuilder.{category}.{folder_name}.{contract_class_name}")
    return getattr(module, contract_class_name)
