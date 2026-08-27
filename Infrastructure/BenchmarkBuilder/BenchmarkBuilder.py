import json
import os.path
from enum import Enum
from typing import AnyStr, List, Optional

from Infrastructure.Analysis.Aggregators.AbstractAggregator import dispatch_aggregator, AbstractAggregator
from Infrastructure.Analysis.Aggregators.ResultAggregatorOffline import ResultAggregatorOffline
from Infrastructure.Analysis.Aggregators.ResultAggregatorOnline import ResultAggregatorOnline
from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.AutoConversion.InputOutputTraceFormats import InputOutputTraceFormats
from Infrastructure.BenchmarkBuilder.BenchmarkBuilderException import BenchmarkCreationFailed
from Infrastructure.BenchmarkBuilder.Coordinator.Coordinator import Coordinator
from Infrastructure.DataTypes.Contracts.OnlineExperimentContract import OnlineExperimentContractGeneral
from Infrastructure.DataTypes.Types.custome_type import OnlineOffline
from Infrastructure.Frontend.CLI.cli_args import CLIArgs
from Infrastructure.DataTypes.FileRepresenters.FingerPrintHandler import FingerPrintHandler
from Infrastructure.DataTypes.FileRepresenters.ScratchFolderHandler import ScratchFolderHandler
from Infrastructure.DataTypes.FileRepresenters.StatsHandler import StatsHandler

from Infrastructure.Monitors.BaseMonitorTemplate import run_monitor_offline, run_monitor_online
from Infrastructure.Monitors.MonitorExceptions import TimedOut, ToolException, ResultErrorException
from Infrastructure.Monitors.MonitorManager import InvalidReturnType, GetMonitorsReturnType, ValidReturnType
from Infrastructure.Provenance.Provenance import ProvenanceFactory, ProvenanceSession, framework_commit, read_fingerprint
from Infrastructure.constants import LENGTH, PATH_TO_NAMED_EXPERIMENT, PATH_TO_INFRA, PATH_TO_EXPERIMENTS, PATH_TO_DEBUG, PATH_TO_PROJECT
from Infrastructure.printing import print_headline, print_footline, normal_line


class RunToolResult(Enum):
    OK = 1
    TIMEOUT = 2
    TOOL_ERROR = 3
    VALIDATION_ERROR = 4


class BenchmarkBuilder:
    def __init__(self, experiment_name, coordinator: Coordinator, tools_to_build, repeat_runs, cli_args: CLIArgs,
                 result_folder: Optional[str] = None):
        print_headline("(Starting) Init Benchmark")
        self.coordinator = coordinator

        self.experiment_name = experiment_name
        self.cli_args = cli_args
        self.repeat_runs = repeat_runs
        self.tools_to_build = tools_to_build
        self.result_folder = result_folder

        path_to_project = self.coordinator.get_path(PATH_TO_PROJECT)
        path_to_infrastructure = path_to_project + "/Infrastructure"
        self.coordinator.add_path(PATH_TO_INFRA, path_to_infrastructure)
        named_experiment_path = path_to_infrastructure + "/experiments/" + experiment_name
        self.coordinator.add_path(PATH_TO_EXPERIMENTS, f"{path_to_infrastructure}/experiments")
        self.coordinator.add_path(PATH_TO_NAMED_EXPERIMENT, named_experiment_path)
        self.coordinator.add_path(PATH_TO_DEBUG, named_experiment_path + "/debug")

        os.makedirs(self.coordinator.get_path(PATH_TO_EXPERIMENTS), exist_ok=True)
        os.makedirs(self.coordinator.get_path(PATH_TO_NAMED_EXPERIMENT), exist_ok=True)

        fingerprint_location = self.coordinator.get_path(PATH_TO_NAMED_EXPERIMENT) + "/fingerprint"
        finger_print = self.coordinator.finger_print()

        print_footline("(Finished) Init Benchmark")
        if os.path.exists(fingerprint_location):
            fph = FingerPrintHandler.from_file(fingerprint_location)
            if not FingerPrintHandler.compare(fph, finger_print):
                self._build()
                FingerPrintHandler(finger_print).to_file(fingerprint_location)
        else:
            self._build()
            FingerPrintHandler(finger_print).to_file(fingerprint_location)

    def _build(self):
        print_headline("(Starting) building Benchmark")
        try:
            self.coordinator.build()
            print_footline("(Finished) building Benchmark")
        except Exception as e:
            raise BenchmarkCreationFailed(e)

    def run(self, tools: List[GetMonitorsReturnType]) -> AbstractAggregator:
        print("\n" + "-" * LENGTH)
        normal_line("Run Experiments")
        print("-" * LENGTH)
        result_aggregator = dispatch_aggregator(self.coordinator.get_runtime_settings())

        path_to_debug = self.coordinator.get_path(PATH_TO_DEBUG)
        if os.path.exists(path_to_debug):
            ScratchFolderHandler(path_to_debug).remove_folder()

        provenance_factory = None
        if getattr(self.cli_args, "provenance", False) and self.result_folder is not None:
            named_experiment_path = self.coordinator.get_path(PATH_TO_NAMED_EXPERIMENT)
            provenance_factory = ProvenanceFactory(
                result_folder=self.result_folder,
                experiment_root=named_experiment_path,
                fingerprint=read_fingerprint(f"{named_experiment_path}/fingerprint"),
                commit=framework_commit(self.coordinator.get_path(PATH_TO_PROJECT)),
                project_root=self.coordinator.get_path(PATH_TO_PROJECT),
            )

        for ((identifier, data_set_size), path_to_folder, data_file, data_type, policy_file, policy_type, signature, result) in self.coordinator.iterate_settings():
            sfh = ScratchFolderHandler(path_to_folder)
            # repeats share one provenance entry per tool; the repeat index is
            # dropped from the key and capture verifies repeats hash-identically
            setting_key = f"{identifier}" if data_set_size is None else f"{identifier}_{data_set_size}"

            for i in range(0, self.repeat_runs):
                tmp_setting_id = f"{identifier}_{i}" if data_set_size is None else f"{identifier}_{data_set_size}_{i}"
                for tool in tools:
                    if isinstance(tool, InvalidReturnType):
                        print_headline(f"Missing {tool.name}")
                        result_aggregator.add_missing(tool.name, tmp_setting_id)
                        print_footline()
                    elif isinstance(tool, ValidReturnType):
                        if self.cli_args.short_cut:
                            # todo short cutting must be done by the coordinator
                            """if tool.tool.name in time_out_dict and self.short_cut:
                                  print_headline(f"Short cutting {tool.tool.name}")
                                  result_aggregator.add_timeout(tool.tool.name, tmp_setting_id, self.time_guard.upper_bound)
                                  print_footline()
                               else:
                                  res = run_tools(...)
                                  if res == RunToolResult.TIMEOUT:
                                     time_out_dict.add(tool.tool.name)"""
                            pass

                        # each tool starts from an empty scratch: its stored
                        # provenance (and its debug copy) then contain exactly
                        # its own inputs, never another tool's leftovers
                        sfh.clean_up_folder()
                        provenance = provenance_factory.session(setting_key, path_to_folder, tool.tool) \
                            if provenance_factory is not None else None

                        if self.coordinator.get_runtime_settings() == OnlineOffline.Online:
                            run_tools_online(
                                result_aggregator=result_aggregator, path_to_folder=path_to_folder, tool=tool.tool,
                                _result_file=result, setting_id=tmp_setting_id, data_file=data_file,
                                signature_file=signature, policy_file=policy_file, sfh=sfh, cli_args=self.cli_args,
                                coordinator=self.coordinator, policy_type=policy_type, data_type=data_type,
                                online_experiment_contract=self.coordinator.get_online_settings(),
                                provenance=provenance
                            )
                        else:
                            run_tools_offline(
                                result_aggregator=result_aggregator, path_to_folder=path_to_folder, tool=tool.tool,
                                result_file=result, setting_id=tmp_setting_id, data_file=data_file, signature_file=signature,
                                policy_file=policy_file, sfh=sfh, cli_args=self.cli_args,
                                coordinator=self.coordinator, policy_type=policy_type, data_type=data_type,
                                provenance=provenance
                            )
                    else:
                        raise NotImplemented(f"Not implemented for object {tool}")

            sfh.remove_folder()
        return result_aggregator

    def seed_retriever(self):
        operator_prefix = "operators_"
        free_vars_prefix = "free_vars_"
        num_prefix = "num_"

        def _read_file(path_) -> int:
            with open(path_, "r") as f:
                return int(f.read())

        def _apply_decoders(string: AnyStr) -> Optional[int]:
            if string.startswith(operator_prefix):
                return int(string.removeprefix(operator_prefix))
            elif string.startswith(free_vars_prefix):
                return int(string.removeprefix(free_vars_prefix))
            elif string.startswith(num_prefix):
                return int(string.removeprefix(num_prefix))
            else:
                return None

        seed_dict = dict()
        path_to_named_experiment = self.path_manager.get_path(PATH_TO_NAMED_EXPERIMENT)
        for (_, path_to_data, _, _, _, _, _, _) in self.coordinator.iterate_settings():
            gen_seed_path = f"{path_to_data}/Seeds/generator.seed"
            policy_seed_path = f"{path_to_data}/Seeds/policy.seed"
            gen_seed = _read_file(gen_seed_path) if os.path.exists(gen_seed_path) else None
            policy_seed = _read_file(policy_seed_path) if os.path.exists(policy_seed_path) else None

            if gen_seed is None and policy_seed is None:
                continue

            clean_path = path_to_data.removeprefix(path_to_named_experiment)
            clean_list = list(filter(None, clean_path.split("/")))
            setting_raw = list(filter(lambda x: x is not None, map(lambda x: _apply_decoders(x), clean_list)))
            setting_key = str(setting_raw)
            seed_dict[setting_key] = (gen_seed, policy_seed)


def run_tools_online(
        result_aggregator: ResultAggregatorOnline, tool, setting_id: str, path_to_folder: str,
        data_file: str, data_type: InputOutputTraceFormats, policy_file: str, policy_type: InputOutputPolicyFormats,
        signature_file: str, _result_file: str, cli_args: CLIArgs, coordinator: Coordinator,
        online_experiment_contract: OnlineExperimentContractGeneral, sfh=None,
        provenance: Optional[ProvenanceSession] = None
):
    debug_path = coordinator.get_path(PATH_TO_DEBUG)
    try:
        preprocessing_elapsed, build_comp_elapsed, total_elapsed_s, total_count, output, code = run_monitor_online(
            mon=tool, path_to_folder=path_to_folder, data_file=data_file, signature_file=signature_file,
            policy_file=policy_file, cli_args=cli_args, trace_source_format=data_type, policy_source_format=policy_type,
            path_manager=coordinator.get_path_manager(), online_experiment_contract=online_experiment_contract,
            script_name=(coordinator.script_name if hasattr(coordinator, "script_name") and coordinator.script_name is not None else None),
            provenance=provenance
        )

        processed_elapsed_pairs = []
        if isinstance(output, list):
            for block in output:
                if isinstance(block, dict):
                    processed = block.get("processed")
                    elapsed_ns = block.get("elapsed_ns")
                    if processed is not None and elapsed_ns is not None:
                        processed_elapsed_pairs.append([processed, elapsed_ns])

        output_pairs_json = json.dumps(processed_elapsed_pairs)

        if code == 0:
            result_aggregator.add_valid(
                tool.name, setting_id, preprocessing_elapsed, build_comp_elapsed, total_elapsed_s, total_count,
                output_pairs_json
            )
            return RunToolResult.OK
        elif code == 200:
            if cli_args.debug and sfh is not None:
                sfh.copy_to_debug(debug_path, setting_id, tool.name)
            result_aggregator.add_timeout_accumulative_latency(
                tool.name, setting_id, preprocessing_elapsed, build_comp_elapsed, total_elapsed_s, total_count,
                output_pairs_json
            )
            return RunToolResult.TIMEOUT
        else:  # code == 250:
            if cli_args.debug and sfh is not None:
                sfh.copy_to_debug(debug_path, setting_id, tool.name)
            result_aggregator.add_timeout_maximum_latency(
                tool.name, setting_id, preprocessing_elapsed, build_comp_elapsed, total_elapsed_s, total_count,
                output_pairs_json
            )
            return RunToolResult.TIMEOUT
    except ToolException as e:
        print(f"ToolException for monitor {tool.name}: {e}")
        if cli_args.debug and sfh is not None:
            sfh.copy_to_debug(debug_path, setting_id, tool.name)
        result_aggregator.add_tool_error(tool.name, setting_id, str(e))
        return RunToolResult.TOOL_ERROR
    except Exception as e:
        if cli_args.debug and sfh is not None:
            sfh.copy_to_debug(debug_path, setting_id, tool.name)
        result_aggregator.add_tool_error(tool.name, setting_id, str(e))
        return RunToolResult.TOOL_ERROR


def run_tools_offline(
        result_aggregator: ResultAggregatorOffline, tool, setting_id: str, path_to_folder: str,
        data_file: str, data_type: InputOutputTraceFormats, policy_file: str, policy_type: InputOutputPolicyFormats,
        signature_file: str, result_file: str, cli_args: CLIArgs, coordinator: Coordinator, sfh=None,
        provenance: Optional[ProvenanceSession] = None
) -> RunToolResult:
    debug_path = coordinator.get_path(PATH_TO_DEBUG)
    timeout_value = coordinator.time_out()
    try:
        prep, compiled, runtime, prop = run_monitor_offline(
            mon=tool, path_to_folder=path_to_folder, data_file=data_file, signature_file=signature_file,
            policy_file=policy_file, cli_args=cli_args, trace_source_format=data_type, policy_source_format=policy_type,
            result_file=result_file, timeout_value=timeout_value,
            oracle=coordinator.get_oracle(), path_manager=coordinator.get_path_manager(),
            provenance=provenance
        )

        if cli_args.debug and sfh is not None:
            sfh.copy_to_debug(debug_path, setting_id, tool.name)

        stats = StatsHandler(path_to_folder).get_stats()
        if stats is not None:
            wall_time, max_mem, cpu = stats
        else:
            if cli_args.measure:
                wall_time, max_mem, cpu = "", "", ""
            else:
                wall_time, max_mem, cpu = None, None, None

        result_aggregator.add_valid(
            tool.name, setting_id, prep, compiled, runtime, prop, wall_time, max_mem, cpu
        )
        return RunToolResult.OK
    except TimedOut as e:
        print(f"Monitor {tool.name} timed out: {e}")
        if cli_args.debug and sfh is not None:
            sfh.copy_to_debug(debug_path, setting_id, tool.name)
        result_aggregator.add_timeout(tool.name, setting_id, timeout_value)
        return RunToolResult.TIMEOUT
    except ToolException as e:
        print(f"ToolException for monitor {tool.name}: {e}")
        if cli_args.debug and sfh is not None:
            sfh.copy_to_debug(debug_path, setting_id, tool.name)
        result_aggregator.add_tool_error(tool.name, setting_id, str(e))
        return RunToolResult.TOOL_ERROR
    except ResultErrorException as e:
        print(f"ResultErrorException for monitor {tool.name}: {e.args[1]}")
        if cli_args.debug and sfh is not None:
            sfh.copy_to_debug(debug_path, setting_id, tool.name)
        stats = StatsHandler(path_to_folder).get_stats()
        if stats is not None:
            wall_time, max_mem, cpu = stats
        else:
            if cli_args.measure:
                wall_time, max_mem, cpu = "", "", ""
            else:
                wall_time, max_mem, cpu = None, None, None
        (prep, compiled, runtime, prop) = e.args[0]
        result_aggregator.add_result_error(
            tool.name, setting_id, prep, compiled, runtime, prop,
            wall_time, max_mem, cpu, str(e.args[1])
        )
        return RunToolResult.VALIDATION_ERROR
    except Exception as e:
        if cli_args.debug and sfh is not None:
            sfh.copy_to_debug(debug_path, setting_id, tool.name)
        result_aggregator.add_tool_error(tool.name, setting_id, str(e))
        return RunToolResult.TOOL_ERROR
