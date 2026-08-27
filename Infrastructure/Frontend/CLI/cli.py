import argparse
import shutil
import sys
import os
from datetime import datetime
from typing import List, Any, AnyStr

from Infrastructure.Analysis.AutomatedAnalysis import dispatch_analysis
from Infrastructure.Frontend.CLI.cli_args import CLIArgs
from Infrastructure.DataLoader.Resolver import BenchmarkResolver, Location
from Infrastructure.DataTypes.PathManager.PathManager import PathManager
from Infrastructure.Frontend.Parser.YamlParser import YamlParser, ExperimentSuiteParser, YamlParserException
from Infrastructure.BenchmarkBuilder.BenchmarkBuilder import BenchmarkBuilder
from Infrastructure.constants import LENGTH, PATH_TO_PROJECT, PATH_TO_BUILD, PATH_TO_EXPERIMENTS, PATH_TO_ARCHIVE, \
    PATH_TO_BENCHMARK, PATH_TO_RESULTS, PATH_TO_FOLDER, PATH_TO_INFRA


class CLI:
    def __init__(self, path_to_module: AnyStr):
        self.parser = self._create_parser()

        self.path_manager = PathManager()
        self.path_to_module = path_to_module
        self.infra_folder = f"{self.path_to_module}/Infrastructure"
        self.build_folder = f"{self.infra_folder}/build"
        self.experiment_folder = f"{self.infra_folder}/experiments"

        self.archive_folder = f"{self.path_to_module}/Archive"
        self.benchmark_settings_folder = f"{self.archive_folder}/Experiments"

        self.result_base_folder = f"{self.infra_folder}/results"
        self.result_analysis_folder = f"{self.infra_folder}/analysis_results"

        self.path_manager.add_path(PATH_TO_PROJECT, self.path_to_module)
        self.path_manager.add_path(PATH_TO_BUILD, self.build_folder)
        self.path_manager.add_path(PATH_TO_EXPERIMENTS, self.experiment_folder)
        self.path_manager.add_path(PATH_TO_ARCHIVE, self.archive_folder)
        self.path_manager.add_path(PATH_TO_BENCHMARK, self.benchmark_settings_folder)
        self.path_manager.add_path(PATH_TO_RESULTS, self.result_base_folder)
        self.path_manager.add_path(PATH_TO_INFRA, self.infra_folder)

        os.makedirs(self.result_base_folder, exist_ok=True)
        os.makedirs(self.result_analysis_folder, exist_ok=True)

        os.makedirs(self.build_folder, exist_ok=True)
        os.makedirs(self.experiment_folder, exist_ok=True)
    
    def _create_timestamped_result_folder(self, experiment_name: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_folder = os.path.join(self.result_base_folder, f"{experiment_name}_{timestamp}")
        os.makedirs(result_folder, exist_ok=True)
        return result_folder

    def _clean_all(self):
        shutil.rmtree(self.result_base_folder, ignore_errors=True)
        os.makedirs(self.result_base_folder, exist_ok=True)

        shutil.rmtree(self.result_analysis_folder, ignore_errors=True)
        os.makedirs(self.result_analysis_folder, exist_ok=True)

    @staticmethod
    def _create_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog='MonitoringFace',
            description='MonitoringFace Benchmark Framework - Run monitoring experiments from YAML configurations',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Run a single experiment
  python -m Infrastructure.main experiments/my_experiment.yaml
  
  # Run a suite of experiments
  python -m Infrastructure.main experiments/experiments_suite.yaml
  
  # Dry run to validate configuration without execution
  python -m Infrastructure.main experiments/my_experiment.yaml --dry-run
  
  # Enable verbose output for more details
  python -m Infrastructure.main experiments/my_experiment.yaml --verbose
  
  # Save transient and temporary data for debugging purposes
  python -m Infrastructure.main experiments/my_experiment.yaml --debug
  
  # Keep only the latest result and analysis of an experiment (clean previous results)
  python -m Infrastructure.main experiments/my_experiment.yaml --clean
  
  # Clean all results and analysis before running
  python -m Infrastructure.main experiments/my_experiment.yaml --clean-all
  
  # Analyze results after running (saves analysis output to a timestamped folder in the analysis directory)
  python -m Infrastructure.main experiments/my_experiment.yaml --analyze
            """
        )
        
        parser.add_argument(
            'config',
            type=str,
            help='Name of a YAML configuration file (single experiment or experiment suite)'
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate configuration without running experiments'
        )
        
        parser.add_argument(
            '--verbose',
            '-v',
            action='store_true',
            help='Enable verbose output'
        )
        
        parser.add_argument(
            '--suite',
            action='store_true',
            help='Force treat config as experiment suite (auto-detected by default)'
        )
        
        parser.add_argument(
            '--debug',
            action='store_true',
            help='Enable debug mode - preserves scratch folder data for each tool execution'
        )

        parser.add_argument(
            '--no-measure',
            action='store_true',
            help='Disable the use of usr/bin/time measurement inside containers'
        )

        parser.add_argument(
            '--provenance',
            action=argparse.BooleanOptionalAction,
            default=True,
            help='Store each tool\'s exact final inputs (converted trace/policy) plus a '
                 'conversion manifest under results/<run>/provenance/ (default: on; '
                 'disable with --no-provenance; --debug implies --provenance)'
        )

        parser.add_argument(
            '--clean',
            action='store_true',
            help='Only retain the lastest result of an experiment'
        )

        parser.add_argument(
            '--clean-all',
            action='store_true',
            help='Force the clean-up of the entire results folder'
        )

        parser.add_argument(
            '--analyze',
            action='store_true',
            help='Run automated analysis on the results after execution'
        )

        return parser

    def run(self, argv: List[str] = None):
        args = self.parser.parse_args(argv)

        cli_args = CLIArgs(
            debug=args.debug,
            verbose=args.verbose,
            measure=(False if args.no_measure else True),
            clean=args.clean,
            clean_all=args.clean_all,
            analyze=args.analyze,
            provenance=(args.provenance or args.debug),  # --debug implies --provenance
        )

        config_name = args.config
        if os.path.isabs(config_name):
            config_name = os.path.relpath(config_name, self.benchmark_settings_folder)
        elif config_name.startswith(self.benchmark_settings_folder):
            config_name = config_name.removeprefix(self.benchmark_settings_folder)
        config_name = config_name.lstrip("/\\")

        br = BenchmarkResolver(name=config_name, path_to_infra=self.infra_folder, path_to_archive=self.archive_folder)
        location = br.resolve()
        if location == Location.Unavailable:
            raise ValueError(f"The configuration File {config_name} is unavailable local and remote")
        elif location == Location.Remote:
            br.get_remote_config(path_to_archive_benchmark=self.benchmark_settings_folder, name=config_name)

        config_path = os.path.join(self.benchmark_settings_folder, config_name)
        is_suite = args.suite or self._is_suite_config(config_path)
        os.makedirs(self.result_base_folder, exist_ok=True)

        if is_suite:
            if args.verbose:
                print("Detected experiment suite configuration")
            self.run_experiment_suite(
                suite_name=config_name,
                cli_args=cli_args,
                dry_run=args.dry_run
            )
        else:
            if args.verbose:
                print("Detected single experiment configuration")
            self.run_single_experiment(
                config_name=config_name,
                dry_run=args.dry_run,
                cli_args=cli_args
            )

    @staticmethod
    def _is_suite_config(config_path: str) -> bool:
        try:
            import yaml
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            return 'experiments' in config
        except Exception:
            return False
    
    def run_single_experiment(self, config_name: AnyStr, cli_args: CLIArgs, dry_run: bool = False, result_folder: str = None, is_suite: bool = False) -> Any:
        yaml_file = os.path.join(self.benchmark_settings_folder, config_name)

        if cli_args.verbose:
            print(f"Loading experiment configuration from: {yaml_file}")
        
        if cli_args.debug:
            print(f"Debug mode enabled - scratch folder data will be preserved")

        try:
            experiment_name = os.path.splitext(os.path.basename(yaml_file))[0]
            self.path_manager.add_path(PATH_TO_FOLDER, self.path_manager.get_path(PATH_TO_EXPERIMENTS) + "/" + experiment_name)
            parser = YamlParser(
                yaml_path=yaml_file, path_to_build=self.build_folder,
                path_to_experiments=self.experiment_folder, path_manager=self.path_manager
            )
            (coordinator, monitor_manager, tools_to_build, num_repeats) = parser.parse_experiment(cli_args=cli_args, experiment_name=experiment_name)

            if cli_args.verbose:
                print(f"Experiment name: {experiment_name}")
                print(f"Tools to build: {', '.join(tools_to_build)}")
            
            if dry_run:
                print(f"✓ Configuration validated successfully: {yaml_file}")
                return None

            # the results folder must exist BEFORE the run: provenance is
            # written into it while the tools execute, not at save time
            if result_folder is None:
                result_folder = self._create_timestamped_result_folder(experiment_name)

            benchmark = BenchmarkBuilder(
                experiment_name=experiment_name,
                coordinator=coordinator,
                tools_to_build=tools_to_build,
                repeat_runs=num_repeats,
                cli_args=cli_args,
                result_folder=result_folder,
            )

            monitors = monitor_manager.get_monitors(tools_to_build)
            
            if cli_args.verbose:
                print(f"Running experiment with {len(monitors)} monitor(s)...")

            results = benchmark.run(monitors)
            analysis_run_folder = None
            if getattr(cli_args, "analyze", False):
                print(f"Running automated analysis on results...")
                analysis_base = os.path.join(self.path_manager.get_path(PATH_TO_INFRA), "analysis_results")
                print(analysis_base)
                os.makedirs(analysis_base, exist_ok=True)

                run_name = experiment_name if not is_suite else f"suite_{experiment_name}"
                analysis_run_folder = os.path.join(
                    analysis_base,
                    f"{run_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                os.makedirs(analysis_run_folder, exist_ok=True)

                analysis = dispatch_analysis(results)
                analysis_results = analysis.run(results)
                for analysis_name, analysis_df in analysis_results.items():
                    analysis_df.to_csv(os.path.join(analysis_run_folder, f"{analysis_name}.csv"), index=False)

            # cleaning stays post-success (a failed run must not destroy
            # earlier results) but must skip this run's own folders, which
            # already hold results AND provenance
            if not is_suite:
                keep = os.path.basename(result_folder)
                keep_analysis = os.path.basename(analysis_run_folder) if analysis_run_folder else None
                if cli_args.clean_all:
                    for folder in os.listdir(self.result_base_folder):
                        if folder != keep:
                            shutil.rmtree(os.path.join(self.result_base_folder, folder), ignore_errors=True)
                    for folder in os.listdir(self.result_analysis_folder):
                        if folder != keep_analysis:
                            shutil.rmtree(os.path.join(self.result_analysis_folder, folder), ignore_errors=True)
                elif cli_args.clean:
                    for folder in os.listdir(self.result_base_folder):
                        if folder.startswith(experiment_name) and folder != keep:
                            shutil.rmtree(os.path.join(self.result_base_folder, folder), ignore_errors=True)
                    for folder in os.listdir(self.result_analysis_folder):
                        if folder.startswith(experiment_name) and folder != keep_analysis:
                            shutil.rmtree(os.path.join(self.result_analysis_folder, folder), ignore_errors=True)

            results.to_csv(result_folder, experiment_name)

            print(f"✓ Experiment completed: {experiment_name}")
            print(f"  Results saved to: {result_folder}")
            if cli_args.verbose:
                print(f"Results: {results}")
            
            return results
            
        except YamlParserException as e:
            print(f"✗ Configuration error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"✗ Error running experiment: {e}", file=sys.stderr)
            if cli_args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)
    
    def run_experiment_suite(self, suite_name: str, cli_args: CLIArgs, dry_run: bool = False) -> List[Any]:
        if cli_args.verbose:
            print(f"Loading experiment suite from: {suite_name}")
        
        if cli_args.debug:
            print(f"Debug mode enabled - scratch folder data will be preserved")

        try:
            suite_parser = ExperimentSuiteParser(self.path_to_module, suite_name)
            experiment_paths = suite_parser.get_experiment_paths()
            
            print(f"Found {len(experiment_paths)} enabled experiment(s) in suite")
            
            if dry_run:
                for i, exp_path in enumerate(experiment_paths, 1):
                    if cli_args.verbose:
                        print(f"\nValidating experiment {i}/{len(experiment_paths)}: {exp_path}")
                    self.run_single_experiment(exp_path, dry_run=True, cli_args=cli_args)
                print(f"\n✓ All {len(experiment_paths)} experiment(s) validated successfully")
                return []

            suite_name_clean = os.path.splitext(os.path.basename(suite_name))[0]
            suite_result_folder = self._create_timestamped_result_folder(suite_name_clean)
            print(f"Suite results will be saved to: {suite_result_folder}")

            if cli_args.clean_all:
                self._clean_all()
            elif cli_args.clean:
                for folder in os.listdir(self.result_base_folder):
                    if folder.startswith(suite_name_clean):
                        shutil.rmtree(os.path.join(self.result_base_folder, folder), ignore_errors=True)

            # Run all experiments
            results = []
            for i, exp_path in enumerate(experiment_paths, 1):
                print(f"\n{'='*LENGTH}")
                print(f"Running experiment {i}/{len(experiment_paths)}: {os.path.basename(exp_path)}")
                print(f"{'='*LENGTH}")
                
                # Create a subfolder for each experiment within the suite folder
                exp_name = os.path.splitext(os.path.basename(exp_path))[0]
                exp_result_folder = os.path.join(suite_result_folder, exp_name)
                os.makedirs(exp_result_folder, exist_ok=True)

                result = self.run_single_experiment(
                    exp_path, cli_args=cli_args, dry_run=False,
                    is_suite=True, result_folder=exp_result_folder
                )
                results.append(result)

            print(f"\n{'='*LENGTH}")
            print(f"✓ All {len(experiment_paths)} experiment(s) completed successfully")
            print(f"{'='*LENGTH}")
            
            return results
            
        except YamlParserException as e:
            print(f"✗ Suite configuration error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"✗ Error running experiment suite: {e}", file=sys.stderr)
            if cli_args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)


def main(argv: List[str] = None, path_to_module: AnyStr = None):
    cli = CLI(path_to_module=path_to_module)
    cli.run(argv)
