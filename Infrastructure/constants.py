DOWNLOADER_ERR_MSG = "An error occurred while fetching the directory tree"

DATAGOLF_POLICY_CHECK = "[Main] The inputs satisfy all constraints."

IMAGE_POSTFIX = "_mf_image"

BUILD_ARG_GIT_BRANCH = "GIT_BRANCH"
BUILD_ARG_GIT_COMMIT = "GIT_COMMIT"

WORKDIR_KEY = "workdir"
WORKDIR_VAL = "/data"

SYMLINK_KEY = "symbolic_link"

DOCKERFILE_KEY = "Dockerfile"
DOCKERFILE_VALUE = "/Dockerfile"

PROP_FILES_KEY = "tool.properties"
PROP_FILES_VALUE = "/tool.properties"

META_FILE_VALUE = "/meta.properties"

ORACLE_KEY = "oracle"
ENTRYPOINT_KEY = "entrypoint"
VOLUMES_KEY = "volumes"
COMMAND_KEY = "command"

GIT_KEY = "git"
OWNER_KEY = "owner"
REPO_KEY = "repo"
VERSION_KEY = "version"
BRANCH_KEY = "branch"

SIGNATURE_KEY = "signature"
SIGNATURE_FILE_KEY = "signature"
FOLDER_KEY = "folder"
POLICY_KEY = "policy"
TRACE_KEY = "trace"

VALUE_KEY = "value"
TYPE_KEY = "type"
PATH_KEY = "path"

SEEDS_KEY = "seed"
SIZE_KEY = "size"
FREE_VARIABLES_KEY = "free_variables"

TRACE_LENGTH_KEY = "trace_length"

SIGNATURE_FILE = "signature"
SIGNATURE_FILE_ENDING = "sig"

POLICY_FILE = "policy"
POLICY_FILE_ENDING = "policy"

ADDITIONAL_FOLDER = "additional"

FINGERPRINT_DATA = "fingerprint_data"
FINGERPRINT_EXPERIMENT = "fingerprint_experiment"
FINGERPRINT_POLICY = "fingerprint_policy"


PATH_TO_BUILD = "path_to_build"
PATH_TO_ARCHIVE = "path_to_archive"
PATH_TO_INFRA = "path_to_infra"
PATH_TO_PROJECT = "path_to_project"
PATH_TO_EXPERIMENTS = "path_to_experiments"
PATH_TO_BENCHMARK = "path_to_benchmark"
PATH_TO_RESULTS = "path_to_results"
PATH_TO_NAMED_DATA = "path_to_named_data"
PATH_TO_INSTRUCTIONS = "path_to_instructions"
PATH_TO_FOLDER = "path_to_folder"
PATH_TO_NAMED_EXPERIMENT = "path_to_named_experiment"
PATH_TO_DEBUG = "path_to_debug"

PATH_TO_INTERMEDIATE_WORKSPACE = "path_to_intermediate_workspace"
PATH_TO_TRACE_INPUT = "path_to_trace_input"
PATH_TO_TRACE_OUTPUT = "path_to_trace_output"

NOMEASURE = "no_measure"
STRATIFIED = "stratified"
STRATIFIED_MAP = "stratified_map"
TRACE_TARGET_FORMAT = "trace_target_format"


POLICY_CONSTANTS_FILE = "policy_constants_file"      # basename, in the scratch folder
POLICY_CONSTANTS_COUNT = "policy_constants_count"    # registration events prepended
POLICY_CONSTANTS_APPLIED = "policy_constants_applied"  # set by the converter that prepended them




PLACEHOLDER_EVENT = "Placeholder()"

BENCHMARK_BUILDING_OFFSET = (" " * 8)

# Pretty Printing
LENGTH = 80
HEADER_ROW = "=" * LENGTH


def Signature_File():
    return f"{SIGNATURE_FILE}.{SIGNATURE_FILE_ENDING}"


def Policy_File():
    return f"{POLICY_FILE}.{POLICY_FILE_ENDING}"
