"""Tests for threading a translated policy's constants into DejaVu's trace.

DejaVu quantifies over the values it has seen, so a constant that occurs only in
the policy is out of range. The MFOTL -> QTL translator extracts those constants
into <dom predicate>.dom, the replayer prepends them to the trace's first time
point (-init), and DejaVu's event numbers shift by one per registered constant.
These tests cover the three places that carry that information.

Plain asserts, no pytest dependency: run with

    python -m Infrastructure.tests.test_dejavu_constants

The end-to-end test shells out to Docker; it is skipped unless both converter
images and a DejaVu image are present (override with QTL_IMAGE, REPLAYER_IMAGE,
DEJAVU_IMAGE).  Because it bind-mounts its work directory, that directory has to
lie inside a path Docker Desktop shares: it is created under the project root,
not in /tmp.
"""

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile

from Archive.Implementations.Builders.ProcessorBuilder.DataConverters.ReplayerConverter.ReplayerConverter import (
    ReplayerConverter,
)
from Archive.Implementations.Builders.ProcessorBuilder.PolicyConverters.QTLConverter.QTLConverter import (
    QTLConverter,
    count_registration_events,
    dom_file_name,
)
from Archive.Implementations.Monitors.DejaVu.DejaVu import DejaVu
from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.AutoConversion.InputOutputTraceFormats import InputOutputTraceFormats
from Infrastructure.Builders.BuilderUtilities import run_offline_image
from Infrastructure.Builders.ProcessorBuilder.ImageManager import ImageManager
from Infrastructure.DataTypes.PathManager.PathManager import PathManager
from Infrastructure.DataTypes.Types.StratificationIndex import StratificationIndex
from Infrastructure.DataTypes.Types.custome_type import processor_to_identifier
from Infrastructure.Monitors.MonitorExceptions import ReplayerException, ToolException
from Infrastructure.constants import (
    COMMAND_KEY,
    IMAGE_POSTFIX,
    PATH_TO_ARCHIVE,
    PATH_TO_PROJECT,
    POLICY_CONSTANTS_APPLIED,
    POLICY_CONSTANTS_COUNT,
    POLICY_CONSTANTS_FILE,
    TRACE_KEY,
    STRATIFIED_MAP,
    VOLUMES_KEY,
    WORKDIR_KEY,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QTL_IMAGE = os.environ.get("QTL_IMAGE", "qtlconverter_policyconverters_mf_image")
REPLAYER_IMAGE = os.environ.get("REPLAYER_IMAGE", "replayerconverter_dataconverters_mf_image")
DEJAVU_IMAGE = os.environ.get("DEJAVU_IMAGE", "")


class _StubImage:
    def __init__(self, image_name):
        self.image_name = image_name


def _converter(cls, image_name):
    """A converter bound to an image name, without ImageManager's build/network."""
    converter = cls.__new__(cls)
    converter.image = _StubImage(image_name)
    return converter


def _dejavu(params):
    return DejaVu(image=None, name="DejaVu", params=params)


def _violations(out):
    return sorted(_dejavu({}).post_processing_offline(out).prop_list)


# -- the constants file the translator writes --------------------------------

def test_dom_file_name():
    assert dom_file_name(["-n", "-e", "e"]) == "_dom.dom"
    assert dom_file_name(["-n", "-e", "e", "-d", "dom"]) == "dom.dom"
    assert dom_file_name(["--dom", "constants", "-n"]) == "constants.dom"
    # a trailing -d has no value: the translator would reject the arguments,
    # and the default name is the only thing we can honestly report
    assert dom_file_name(["-n", "-d"]) == "_dom.dom"
    print("ok: dom_file_name")


def test_count_registration_events():
    with tempfile.TemporaryDirectory() as tmp:
        def count(contents):
            path = os.path.join(tmp, "constants.dom")
            with open(path, "w") as f:
                f.write(contents)
            return count_registration_events(path)

        assert count("_dom(30)\n") == 1
        assert count("_dom(4)(10)\n") == 2
        assert count("a(1)(2)(5)\nb(1,5)(2,3)\n") == 5
        assert count("_dom()\n") == 1
        assert count("") == 0
        # string constants are double quoted and may contain parentheses
        assert count('_dom("foo)bar")(2)\n') == 2
        assert count('_dom("a,b")\n') == 1
    print("ok: count_registration_events")


# -- DejaVu's event numbers shift by one per registered constant -------------

def test_post_processing_without_constants_is_unchanged():
    out = ("*** Property fma violated on event number 3:\n"
           "*** Property fma violated on event number 7:\n")
    assert _violations(out) == [3, 7]
    print("ok: post_processing without constants")


def test_post_processing_subtracts_registered_constants():
    out = ("*** Property fma violated on event number 3:\n"
           "*** Property fma violated on event number 7:\n")
    monitor = _dejavu({POLICY_CONSTANTS_COUNT: 2})
    assert sorted(monitor.post_processing_offline(out).prop_list) == [1, 5]
    print("ok: post_processing subtracts registered constants")


def test_post_processing_ignores_verdicts_on_registration_events():
    # cannot arise from a translated policy (it holds only at boundary events),
    # but a verdict inside the registration block is not a time point either
    monitor = _dejavu({POLICY_CONSTANTS_COUNT: 3})
    out = ("*** Property fma violated on event number 2:\n"
           "*** Property fma violated on event number 5:\n")
    assert sorted(monitor.post_processing_offline(out).prop_list) == [2]
    print("ok: post_processing ignores verdicts on registration events")


def test_post_processing_maps_shifted_events_through_stratification():
    # two time points of one event each, plus the boundary event per time point
    monitor = _dejavu({
        POLICY_CONSTANTS_COUNT: 1,
        STRATIFIED_MAP: StratificationIndex({0: 2, 1: 2}),
    })
    # event 3 with one registered constant is the boundary of time point 0
    result = monitor.post_processing_offline("*** Property fma violated on event number 3:\n")
    assert sorted(result.prop_list) == [0]
    result = monitor.post_processing_offline("*** Property fma violated on event number 5:\n")
    assert sorted(result.prop_list) == [1]
    print("ok: post_processing maps shifted events through stratification")


# -- the replayer refuses a format that cannot hold the registration events ---

def test_replayer_rejects_dejavu_target_with_constants():
    converter = _converter(ReplayerConverter, REPLAYER_IMAGE)
    params = {POLICY_CONSTANTS_FILE: "_dom.dom"}
    try:
        converter.auto_convert(
            ".", "trace.log", ".", "trace.dejavu",
            InputOutputTraceFormats.MONPOLY, InputOutputTraceFormats.DEJAVU, params
        )
    except ReplayerException as e:
        assert "single event per time point" in str(e), str(e)
        assert POLICY_CONSTANTS_APPLIED not in params
        print("ok: replayer rejects dejavu target with constants")
        return
    raise AssertionError("expected a ReplayerException for the dejavu target")


# -- policy conversion -> trace conversion -> DejaVu --------------------------

POLICY = "(x = 4) AND (NOT P0(x))"
TRACE = "@1 P0(7)\n@2 P0(4)\n"
# VeriMon reports the policy satisfied at time point 0 only: at time point 1 the
# trace has P0(4).  DejaVu sees 4 only because the constant is registered, and
# reports the boundary event of time point 0 -- line 3 of the registered trace,
# line 2 once the registration event is discounted.
EXPECTED_EVENT = 2


def _image_exists(image):
    if not image:
        return False
    result = subprocess.run(["docker", "image", "inspect", image],
                            capture_output=True, text=True)
    return result.returncode == 0


def test_end_to_end_conversion():
    if not (_image_exists(QTL_IMAGE) and _image_exists(REPLAYER_IMAGE)):
        print(f"skip: end-to-end (needs images {QTL_IMAGE} and {REPLAYER_IMAGE})")
        return

    # Docker Desktop shares the project directory, not the system temp directory
    work = tempfile.mkdtemp(prefix=".dejavu-constants-", dir=PROJECT_ROOT)
    try:
        with open(os.path.join(work, "policy.policy"), "w") as f:
            f.write(POLICY)
        with open(os.path.join(work, "trace.log"), "w") as f:
            f.write(TRACE)

        params = {}
        _converter(QTLConverter, QTL_IMAGE).auto_convert(
            work, "policy.policy", work, "policy.qtl",
            InputOutputPolicyFormats.MFOTL, InputOutputPolicyFormats.QTL, params
        )
        assert params[POLICY_CONSTANTS_FILE] == "_dom.dom", params
        assert params[POLICY_CONSTANTS_COUNT] == 1, params
        with open(os.path.join(work, "_dom.dom")) as f:
            assert f.read().strip() == "_dom(4)", "translator wrote unexpected constants"
        with open(os.path.join(work, "policy.qtl")) as f:
            assert "_dom(x)" in f.read(), "translation does not mention the constants predicate"

        _converter(ReplayerConverter, REPLAYER_IMAGE).auto_convert(
            work, "trace.log", work, "trace.csv",
            InputOutputTraceFormats.MONPOLY, InputOutputTraceFormats.DEJAVU_ENCODED, params
        )
        assert params[POLICY_CONSTANTS_APPLIED] is True, params
        with open(os.path.join(work, "trace.csv")) as f:
            lines = f.read().splitlines()
        assert lines == ["_dom,4", "P0,7", "e", "P0,4", "e"], lines

        # a second conversion of a constant-free policy must not inherit them
        with open(os.path.join(work, "plain.policy"), "w") as f:
            f.write("P0(x)")
        _converter(QTLConverter, QTL_IMAGE).auto_convert(
            work, "plain.policy", work, "plain.qtl",
            InputOutputPolicyFormats.MFOTL, InputOutputPolicyFormats.QTL, params
        )
        assert POLICY_CONSTANTS_FILE not in params, params
        assert POLICY_CONSTANTS_COUNT not in params, params
        assert not os.path.exists(os.path.join(work, "_dom.dom"))
        print("ok: end-to-end conversion")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# -- the whole preprocessing stage -------------------------------------------

def _stub_image_manager_init(self, name, proc, path_to_project_inner):
    """ImageManager's constructor resolves and builds the image; the images this
    test needs are already there, and only their names matter here."""
    identifier = processor_to_identifier(proc)
    self.name = name
    self.proc = proc
    self.identifier = identifier
    self.image_name = f"{name.lower()}_{identifier.lower()}{IMAGE_POSTFIX}"


@contextlib.contextmanager
def _prepared_setting(policy, trace=TRACE):
    """A setting folder with a policy, a trace and an empty scratch folder, plus a
    path manager pointing at it, with image resolution stubbed out."""
    work = tempfile.mkdtemp(prefix=".dejavu-preprocessing-", dir=PROJECT_ROOT)
    original_init = ImageManager.__init__
    ImageManager.__init__ = _stub_image_manager_init
    try:
        os.makedirs(os.path.join(work, "scratch"))
        for name, contents in (("policy.policy", policy), ("trace.log", trace),
                               ("signature.sig", "P0(int)\n")):
            with open(os.path.join(work, name), "w") as f:
                f.write(contents)
        path_manager = PathManager()
        path_manager.add_path(PATH_TO_PROJECT, PROJECT_ROOT)
        path_manager.add_path(PATH_TO_ARCHIVE, os.path.join(PROJECT_ROOT, "Archive"))
        yield work, path_manager
    finally:
        ImageManager.__init__ = original_init
        shutil.rmtree(work, ignore_errors=True)


def _preprocess(monitor, work, path_manager, trace_format=InputOutputTraceFormats.MONPOLY):
    return monitor.preprocessing(
        path_to_folder=work, trace_source_format=trace_format,
        policy_source_format=InputOutputPolicyFormats.MFOTL,
        data_file="trace.log", signature_file="signature.sig", policy_file="policy.policy",
        path_manager=path_manager, verbose=False
    )


def test_preprocessing_registers_the_policys_constants():
    if not (_image_exists(QTL_IMAGE) and _image_exists(REPLAYER_IMAGE)):
        print(f"skip: preprocessing (needs images {QTL_IMAGE} and {REPLAYER_IMAGE})")
        return
    with _prepared_setting(POLICY) as (work, path_manager):
        monitor = _dejavu({})
        result = _preprocess(monitor, work, path_manager)

        assert monitor.params[POLICY_CONSTANTS_FILE] == "_dom.dom", monitor.params
        assert monitor.params[POLICY_CONSTANTS_COUNT] == 1, monitor.params
        assert monitor.params[POLICY_CONSTANTS_APPLIED] is True, monitor.params
        assert [record.kind for record in result.records] == ["trace", "policy", "signature"]
        with open(os.path.join(work, monitor.params[TRACE_KEY])) as f:
            assert f.read().splitlines() == ["_dom,4", "P0,7", "e", "P0,4", "e"]

        # the same monitor object serves the next setting: a constant-free policy
        # must not inherit these constants
        with open(os.path.join(work, "policy.policy"), "w") as f:
            f.write("P0(x)")
        for stale in os.listdir(os.path.join(work, "scratch")):
            os.remove(os.path.join(work, "scratch", stale))
        _preprocess(monitor, work, path_manager)
        assert POLICY_CONSTANTS_FILE not in monitor.params, monitor.params
        assert POLICY_CONSTANTS_COUNT not in monitor.params, monitor.params
        assert POLICY_CONSTANTS_APPLIED not in monitor.params, monitor.params
        with open(os.path.join(work, monitor.params[TRACE_KEY])) as f:
            assert f.read().splitlines() == ["P0,7", "e", "P0,4", "e"]
    print("ok: preprocessing registers the policy's constants")


def test_preprocessing_refuses_constants_the_trace_never_receives():
    if not _image_exists(QTL_IMAGE):
        print(f"skip: preprocessing guard (needs image {QTL_IMAGE})")
        return
    # a trace already in a format DejaVu accepts is not converted, so nothing
    # can register the constants in it
    with _prepared_setting(POLICY, trace="P0,7\ne\nP0,4\ne\n") as (work, path_manager):
        try:
            _preprocess(_dejavu({}), work, path_manager, InputOutputTraceFormats.DEJAVU)
        except ToolException as e:
            assert "never entered the trace" in str(e), str(e)
            print("ok: preprocessing refuses constants the trace never receives")
            return
    raise AssertionError("expected a ToolException for unregistered constants")


class _StubToolImage:
    """Runs a tool image the way ToolImageManager.run_offline does, without its
    resolution and build steps (measurement off: the wrapper needs GNU time)."""

    def __init__(self, image_name):
        self.image_name = image_name
        self.binary_name = ""

    def run_offline(self, path_to_data, parameters, time_on=None, time_out=None, measure=True, name=None):
        contract = {
            VOLUMES_KEY: {path_to_data: {"bind": "/data", "mode": "rw"}},
            COMMAND_KEY: [name if name is not None else self.binary_name] + parameters,
            WORKDIR_KEY: "/data",
        }
        return run_offline_image(self.image_name, contract, verbose=False,
                                 time_on=time_on, time_out=time_out, is_tool_image=True)


def test_offline_run_reports_the_registered_time_point():
    if not (_image_exists(QTL_IMAGE) and _image_exists(REPLAYER_IMAGE) and _image_exists(DEJAVU_IMAGE)):
        print(f"skip: offline run (needs {QTL_IMAGE}, {REPLAYER_IMAGE} and DEJAVU_IMAGE)")
        return
    with _prepared_setting(POLICY) as (work, path_manager):
        monitor = DejaVu(image=_StubToolImage(DEJAVU_IMAGE), name="DejaVu", params={})
        _preprocess(monitor, work, path_manager)
        monitor.offline_compile()
        cmd, name = monitor.construct_offline_command()
        out, code = monitor.image.run_offline(path_to_data=work, parameters=cmd, name=name, measure=False)
        assert code == 0, out
        assert sorted(monitor.post_processing_offline(out).prop_list) == [EXPECTED_EVENT], out

        # negative control: the same policy on the same trace without the
        # registration event. DejaVu never sees 4, so it reports nothing at all —
        # which is the silent under-reporting this whole mechanism removes.
        unregistered = dict(monitor.params)
        unregistered.pop(POLICY_CONSTANTS_FILE)
        unregistered.pop(POLICY_CONSTANTS_APPLIED)
        _converter(ReplayerConverter, REPLAYER_IMAGE).auto_convert(
            work, "trace.log", os.path.join(work, "scratch"), "bare.csv",
            InputOutputTraceFormats.MONPOLY, InputOutputTraceFormats.DEJAVU_ENCODED, unregistered
        )
        bare = DejaVu(image=_StubToolImage(DEJAVU_IMAGE), name="DejaVu", params=dict(monitor.params))
        bare.params[TRACE_KEY] = "scratch/bare.csv"
        cmd, name = bare.construct_offline_command()
        out, code = bare.image.run_offline(path_to_data=work, parameters=cmd, name=name, measure=False)
        assert code == 0, out
        assert "violated on event number" not in out, out
    print("ok: offline run reports the registered time point")


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"\n{len(TESTS)} test functions passed")
    sys.exit(0)
