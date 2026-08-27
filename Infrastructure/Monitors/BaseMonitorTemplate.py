import os
import sys
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, AnyStr, Any, Tuple, List, Optional, Union

from Infrastructure.AutoConversion.AutoPolicyConverter import AutoPolicyConverter
from Infrastructure.AutoConversion.AutoTraceConverter import AutoTraceConverter
from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.Builders.BuilderUtilities import run_online_image
from Infrastructure.Builders.OnlineExperiementPipeline import build_pipeline
from Infrastructure.Builders.ToolBuilder.ToolImageManager import AbstractToolImageManager
from Infrastructure.DataTypes.Contracts.OnlineExperimentContract import OnlineExperimentContractGeneral
from Infrastructure.DataTypes.Types.StratificationIndex import StratificationIndex
from Infrastructure.Frontend.CLI.cli_args import CLIArgs
from Infrastructure.DataTypes.PathManager.PathManager import PathManager
from Infrastructure.DataTypes.Verification.OutputStructures.AbstractOutputStrucutre import AbstractOutputStructure
from Infrastructure.AutoConversion.InputOutputTraceFormats import InputOutputTraceFormats
from Infrastructure.Monitors.MonitorExceptions import ToolException, ResultErrorException, TimedOut
from Infrastructure.Oracles.AbstractOracleTemplate import AbstractOracleTemplate
from Infrastructure.Provenance.Provenance import ConversionRecord, PreprocessingResult, ProvenanceSession
from Infrastructure.constants import SIGNATURE_KEY, FOLDER_KEY, TRACE_KEY, POLICY_KEY, PATH_TO_BUILD, PATH_TO_ARCHIVE, \
    PATH_TO_TRACE_INPUT, PATH_TO_TRACE_OUTPUT, PATH_TO_INTERMEDIATE_WORKSPACE, IMAGE_POSTFIX, Policy_File, \
    Signature_File, NOMEASURE, STRATIFIED, STRATIFIED_MAP, TRACE_TARGET_FORMAT
from Infrastructure.printing import print_headline, print_footline


class AutoConvertable(ABC):
    @staticmethod
    @abstractmethod
    def supported_policy_formats() -> List[InputOutputPolicyFormats]:
        pass

    @staticmethod
    @abstractmethod
    def supported_trace_formats() -> List[InputOutputTraceFormats]:
        pass


class OfflineRunnable(ABC):
    @abstractmethod
    def construct_offline_command(self) -> Tuple[List[str], Optional[str]]:
        pass

    def offline_compile(self):
        pass

    @abstractmethod
    def post_processing_offline(self, stdout_input: AnyStr) -> AbstractOutputStructure:
        pass


class OnlineRunnable(ABC):
    @abstractmethod
    def construct_online_command(self) -> Tuple[List[str], Optional[str]]:
        pass

    @staticmethod
    @abstractmethod
    def latency_marker() -> Optional[str]:
        pass

    def online_compile(self) -> Optional[Dict[str, str]]:
        return None

    @abstractmethod
    def post_processing_online(self, stdout_input: AnyStr) -> AbstractOutputStructure:
        pass


class BaseMonitorTemplate(AutoConvertable):
    def __init__(self, image: AbstractToolImageManager, name, params: Dict[AnyStr, Any]):
        self.image = image
        self.params = params
        self.name = name

    def preprocessing(
            self, path_to_folder: str, trace_source_format: InputOutputTraceFormats,
            policy_source_format: InputOutputPolicyFormats, data_file: str, signature_file: str, policy_file: str,
            path_manager: PathManager, verbose=False
    ) -> PreprocessingResult:
        path_manager.add_path(PATH_TO_TRACE_INPUT, f"{path_to_folder}")
        path_manager.add_path(PATH_TO_INTERMEDIATE_WORKSPACE, f"{path_to_folder}/scratch")
        path_manager.add_path(PATH_TO_TRACE_OUTPUT, f"{path_to_folder}/scratch")

        trace_target_format, trace_conversion_distance = find_trace_path(self, path_manager, trace_source_format)
        policy_target_format, policy_conversion_distance = find_policy_path(self, path_manager, policy_source_format)

        trace_auto_convertible = True if trace_target_format is not None else False
        policy_auto_convertible = True if policy_target_format is not None else False

        records: List[ConversionRecord] = []
        start = time.perf_counter()
        if trace_auto_convertible:
            if verbose:
                print("Automatic Trace conversion from {} to {}".format(trace_source_format, trace_target_format))

            self.params[TRACE_TARGET_FORMAT] = trace_target_format
            if trace_conversion_distance == 0:
                self.params[TRACE_KEY] = data_file
                records.append(ConversionRecord(
                    kind="trace", source_file=data_file, source_format=trace_source_format.value,
                    steps=[], as_seen_by_tool=data_file
                ))
            else:
                self.params[TRACE_KEY], trace_steps = AutoTraceConverter(path_manager, trace_source_format, trace_target_format).convert(
                    input_file=data_file, output_file=data_file, params=self.params
                )
                records.append(ConversionRecord(
                    kind="trace", source_file=data_file, source_format=trace_source_format.value,
                    steps=trace_steps, as_seen_by_tool=self.params[TRACE_KEY]
                ))
        else:
            if verbose:
                print("Costume Trace preprocessing for format {}".format(trace_source_format))
            self.preprocessing_data(path_to_folder, data_file, trace_source_format, path_manager)
            records.append(ConversionRecord(
                kind="trace", source_file=data_file, source_format=trace_source_format.value,
                steps=[], as_seen_by_tool=self.params.get(TRACE_KEY, data_file), custom=True
            ))

        if policy_auto_convertible:
            if verbose:
                print("Policy conversion from {} to {}".format(policy_source_format, policy_target_format))
            self.params[SIGNATURE_KEY] = signature_file
            self.params[FOLDER_KEY] = path_to_folder

            if policy_conversion_distance == 0:
                self.params[POLICY_KEY] = policy_file
                records.append(ConversionRecord(
                    kind="policy", source_file=policy_file, source_format=policy_source_format.value,
                    steps=[], as_seen_by_tool=policy_file
                ))
            else:
                self.params[POLICY_KEY], policy_steps = AutoPolicyConverter(path_manager, policy_source_format, policy_target_format).convert(
                    input_file=policy_file, output_file=policy_file, params=self.params
                )
                records.append(ConversionRecord(
                    kind="policy", source_file=policy_file, source_format=policy_source_format.value,
                    steps=policy_steps, as_seen_by_tool=self.params[POLICY_KEY]
                ))
        else:
            if verbose:
                print("Costume Policy preprocessing for format {}".format(policy_source_format))
            self.preprocessing_policy(path_to_folder, policy_file, signature_file, policy_source_format, path_manager)
            records.append(ConversionRecord(
                kind="policy", source_file=policy_file, source_format=policy_source_format.value,
                steps=[], as_seen_by_tool=self.params.get(POLICY_KEY, policy_file), custom=True
            ))

        # the signature is always handed over untouched; the identity record
        # pins its hash so the run's exact inputs are fully covered
        if isinstance(signature_file, str) and signature_file:
            records.append(ConversionRecord(
                kind="signature", source_file=signature_file, source_format="sig",
                steps=[], as_seen_by_tool=signature_file
            ))
        end = time.perf_counter()
        return PreprocessingResult(elapsed_s=end - start, records=records)

    @abstractmethod
    def preprocessing_data(
            self, path_to_folder: AnyStr, data_file: AnyStr,
            trace_source: InputOutputTraceFormats, path_manager: PathManager
    ):
        pass

    @abstractmethod
    def preprocessing_policy(
            self, path_to_folder: AnyStr, policy_file: AnyStr, signature_file: AnyStr,
            policy_source: InputOutputPolicyFormats, path_manager: PathManager
    ):
        pass


def run_monitor_online(
        mon: Union[OnlineRunnable, BaseMonitorTemplate],
        path_to_folder: AnyStr, data_file: AnyStr, signature_file: AnyStr, policy_file: AnyStr,
        path_manager: PathManager, trace_source_format: InputOutputTraceFormats,
        policy_source_format: InputOutputPolicyFormats, cli_args: CLIArgs,
        online_experiment_contract: OnlineExperimentContractGeneral, script_name: Optional[str] = None,
        provenance: Optional[ProvenanceSession] = None
):
    print_headline(f"Run (Online) {mon.name}")

    pre = None
    if script_name is not None:
        preprocessing_elapsed = 0
        data_source = script_name
        policy_file = Policy_File()  # todo where to scripts get policies from, probably hardcoded
        signature_file = Signature_File()
        if provenance is not None:
            # script runs have no conversion, but their input is still an
            # input: record the script itself, or say loudly that we cannot
            script_path = os.path.join(path_to_folder, script_name)
            if os.path.isfile(script_path):
                pre = PreprocessingResult(elapsed_s=0.0, records=[ConversionRecord(
                    kind="trace", source_file=script_name, source_format="script",
                    steps=[], as_seen_by_tool=script_name)])
                provenance.capture(pre.records)
            else:
                print(f"provenance WARNING: script-mode run of {mon.name} has no "
                      f"capturable input ({script_name} not found in the setting "
                      f"folder); no provenance entry stored")
    else:
        pre = mon.preprocessing(
            path_to_folder, trace_source_format, policy_source_format,
            data_file, signature_file, policy_file, path_manager, verbose=cli_args.verbose
        )
        preprocessing_elapsed = pre.elapsed_s
        # store the exact final inputs BEFORE the tool runs: a crashed or
        # timed-out run must still leave its provenance behind
        if provenance is not None:
            provenance.capture(pre.records)

        data_source = mon.params[TRACE_KEY]
        policy_file = mon.params[POLICY_KEY]
        signature_file = mon.params[SIGNATURE_KEY]

    target_name = f"online_experiment_{mon.name.lower()}{IMAGE_POSTFIX}"
    additional_compilation_data = mon.online_compile()
    start_build_comp = time.perf_counter()

    build_pipeline(
        tool_image_manager=mon.image, path_to_build=path_manager.get_path(PATH_TO_BUILD),
        path_to_archive=path_manager.get_path(PATH_TO_ARCHIVE), path_to_folder=path_to_folder,
        data_source=data_source, policy_file=policy_file, signature_file=signature_file,
        target_image_name=target_name, compilation_details=additional_compilation_data
    )
    end_build_comp = time.perf_counter()
    build_comp_elapsed = end_build_comp - start_build_comp

    tool_online_experiment_contract = mon.params.get("OnlineExperimentContractTool")
    if tool_online_experiment_contract is None:
        print("OnlineExperimentContractTool not defined")
        raise ValueError(f"Monitor {mon.name} has no online experiment contract")

    tool_command, name = mon.construct_online_command()
    if provenance is not None and pre is not None:
        provenance.record_invocation(tool_command)
    output, total_elapsed_s, total_count, latency_err_msg, code = run_online_image(
        image_name=target_name, tool_command=tool_command,
        online_experiment_contract=online_experiment_contract,
        tool_online_experiment_contract=tool_online_experiment_contract,
        verbose=cli_args.verbose
    )
    if provenance is not None and pre is not None:
        provenance.verify_after_run(pre.records)

    print(f"Prep:        {preprocessing_elapsed}\nBuilding: {build_comp_elapsed}")
    print(f"Runtime:     {total_elapsed_s}\nTotal Count: {total_count}")
    if latency_err_msg is not None:
        print(f"Latency Extraction Error: {latency_err_msg}")

    # todo post processing of results and latency extraction (future work)

    # todo verify results with oracle (future work)

    return preprocessing_elapsed, build_comp_elapsed, total_elapsed_s, total_count, output, code


def run_monitor_offline(mon: Union[OfflineRunnable, BaseMonitorTemplate], timeout_value, path_to_folder: AnyStr, data_file: AnyStr, signature_file: AnyStr, policy_file: AnyStr,
                        path_manager: PathManager, trace_source_format: InputOutputTraceFormats, policy_source_format: InputOutputPolicyFormats,
                        result_file, cli_args: CLIArgs, oracle: Optional[AbstractOracleTemplate] = None,
                        provenance: Optional[ProvenanceSession] = None) -> Tuple[float, float, float, float]:
    print_headline(f"Run (Offline) {mon.name}")

    pre = mon.preprocessing(
        path_to_folder, trace_source_format, policy_source_format,
        data_file, signature_file, policy_file, path_manager, verbose=cli_args.verbose
    )
    preprocessing_elapsed = pre.elapsed_s
    # store the exact final inputs BEFORE compile and run: a crashed or
    # timed-out run must still leave its provenance behind
    if provenance is not None:
        provenance.capture(pre.records)

    if mon.params.get(STRATIFIED):
        stratified_map = init_stratification_map(
            trace_source_format, mon.params[TRACE_TARGET_FORMAT], data_file, path_manager.get_path(PATH_TO_TRACE_INPUT)
        )
        mon.params[STRATIFIED_MAP] = stratified_map

    start_compile = time.perf_counter()
    mon.offline_compile()
    end_compile = time.perf_counter()
    compile_elapsed = end_compile - start_compile

    cmd, name = mon.construct_offline_command()
    if provenance is not None:
        provenance.record_invocation(cmd)
    measure = False if mon.params.get(NOMEASURE) else True
    start = time.perf_counter()
    out, code = mon.image.run_offline(parameters=cmd, path_to_data=path_to_folder, time_out=timeout_value, name=name, measure=measure)
    end = time.perf_counter()
    run_offline_elapsed = end - start
    if provenance is not None:
        provenance.verify_after_run(pre.records)

    if code != 0:
        raise TimedOut(f"Timed out: {mon.name}") if code == 124 else ToolException(out)

    start = time.perf_counter()
    res = mon.post_processing_offline(out)
    end = time.perf_counter()
    postprocessing_elapsed = end - start

    print(f"Prep:        {preprocessing_elapsed}\nCompilation: {compile_elapsed}\nRuntime:     {run_offline_elapsed}\nPost:        {postprocessing_elapsed}")

    if oracle is not None:
        try:
            verified, msg = oracle.verify(path_to_folder, data_file, res, signature_file, f"scratch/{policy_file}", result_file)
        except Exception as e:
            if cli_args.verbose:
                print(f"Oracle verification failed with exception: {e}")
            raise ResultErrorException((preprocessing_elapsed, compile_elapsed, run_offline_elapsed, postprocessing_elapsed), str(e))
        print_headline(f"Verified: {verified}")
        if not verified:
            raise ResultErrorException((preprocessing_elapsed, compile_elapsed, run_offline_elapsed, postprocessing_elapsed), msg)

    print_footline()
    return preprocessing_elapsed, compile_elapsed, run_offline_elapsed, postprocessing_elapsed


def find_trace_path(mon: BaseMonitorTemplate, path_manager: PathManager, trace_source_format: InputOutputTraceFormats) -> Tuple[Optional[InputOutputTraceFormats], Optional[int]]:
    trace_target_format = None
    conversion_distance = None
    supported_formats = mon.supported_trace_formats()
    if trace_source_format in supported_formats:
        return trace_source_format, 0

    for trace_format in supported_formats:
        res = AutoTraceConverter.reachable(path_manager, trace_source_format, trace_format)
        if res is not None:
            _, target, dist = res
            if conversion_distance is None or dist < conversion_distance:
                trace_target_format = target
                conversion_distance = dist
    return trace_target_format, conversion_distance


def find_policy_path(mon: BaseMonitorTemplate, path_manager: PathManager, policy_source_format: InputOutputPolicyFormats) -> Tuple[Optional[InputOutputPolicyFormats], Optional[int]]:
    policy_target_format = None
    conversion_distance = None
    supported_formats = mon.supported_policy_formats()
    if policy_source_format in supported_formats:
        return policy_source_format, 0

    for policy_format in supported_formats:
        res = AutoPolicyConverter.reachable(path_manager, policy_source_format, policy_format)
        if res is not None:
            _, target, dist = res
            if conversion_distance is None or dist < conversion_distance:
                policy_target_format = target
                conversion_distance = dist
    return policy_target_format, conversion_distance


def init_stratification_map(src_format: InputOutputTraceFormats, target_format: InputOutputTraceFormats, data_file, path_to_data) -> StratificationIndex:
    mapping = defaultdict(int)
    with open(f"{path_to_data}/{data_file}", "r") as f:
        for line in f:
            if line.__contains__("tp="):
                tp = int(line.split("tp=")[1].split(",")[0])  # int, not str: lexicographic order breaks for tp >= 10
                mapping[tp] += 1

    # DejaVu's stratified trace emits one breaker event per timepoint to mark the
    # timepoint switch, and that breaker consumes a (1-based) DejaVu event index.
    # Include it in each block's size so the indices DejaVu reports map back correctly.
    mapping = {tp: count + 1 for tp, count in mapping.items()}
    return StratificationIndex(mapping)
