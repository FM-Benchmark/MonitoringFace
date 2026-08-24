import os
from typing import Any, Dict, List, Tuple

from Infrastructure.AutoConversion.InputOutputPolicyFormats import InputOutputPolicyFormats
from Infrastructure.Builders.ProcessorBuilder.PolicyConverters.PolicyConverterTemplate import (
    PolicyConverterTemplate,
    PolicyTransformationException,
)
from Infrastructure.constants import FOLDER_KEY, SIGNATURE_KEY
from Archive.Implementations.Builders.ProcessorBuilder.PolicyConverters.TeSSLaPolicyConverter.mfotl2tessla import (
    PolicyParseError,
    UnsupportedFragmentError,
    compile_policy,
)


class TeSSLaPolicyConverter(PolicyConverterTemplate):
    """In-process MFOTL -> TeSSLa (srv-policy) compiler, phase 0.

    Supports closed past-only formulas over [0,*) intervals; anything outside
    the fragment raises, so the run is recorded as a tool error rather than
    producing a silently wrong specification.  The companion trace edge is
    TeSSLaTraceConverter (CSV -> srv-trace); the stream naming contract
    (mf_ts, mf_p_<Pred>, verdict mf_v) is shared between the two and with
    TeSSLa.post_processing_offline.
    """

    def __init__(self, name, path_to_project):
        pass

    def auto_convert(self, path_to_folder: str, input_file: str, path_to_output_folder: str, output_file: str,
                     source: InputOutputPolicyFormats, target: InputOutputPolicyFormats, params: Dict[str, Any]):
        if (source, target) not in self.conversion_scheme():
            raise PolicyTransformationException(
                f"Incompatible conversion from {source} to {target}"
            )

        with open(f"{path_to_folder}/{input_file}", "r") as policy_file:
            policy_text = policy_file.read()

        signature_path = self._resolve_signature(params)
        with open(signature_path, "r") as signature_file:
            signature_text = signature_file.read()

        try:
            spec = compile_policy(
                policy_text,
                signature_text,
                source_negated=(source == InputOutputPolicyFormats.NEGATED_MFOTL),
            )
        except (UnsupportedFragmentError, PolicyParseError) as e:
            raise PolicyTransformationException(
                f"TeSSLaPolicyConverter: {e}"
            ) from e

        with open(f"{path_to_output_folder}/{output_file}", "w") as out:
            out.write(spec)

    @staticmethod
    def _resolve_signature(params: Dict[str, Any]) -> str:
        """The signature is not copied into the conversion workspace; it is
        reachable via params (set by BaseMonitorTemplate.preprocessing before
        the policy chain runs)."""
        signature = params.get(SIGNATURE_KEY)
        if not signature:
            raise PolicyTransformationException(
                "TeSSLaPolicyConverter needs the signature to emit typed input "
                "streams, but params carry no signature entry"
            )
        folder = params.get(FOLDER_KEY, "")
        # Setting-folder-relative candidates first: a like-named file in the
        # process CWD must never shadow the experiment's signature.
        candidates = [
            os.path.join(folder, signature),
            os.path.join(folder, str(signature).removeprefix("data/")),
            signature,
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        raise PolicyTransformationException(
            f"TeSSLaPolicyConverter: signature file not found (tried {candidates})"
        )

    @staticmethod
    def conversion_scheme() -> List[Tuple[InputOutputPolicyFormats, InputOutputPolicyFormats]]:
        return [
            (InputOutputPolicyFormats.MFOTL, InputOutputPolicyFormats.SRV_POLICY),
            (InputOutputPolicyFormats.NEGATED_MFOTL, InputOutputPolicyFormats.SRV_POLICY),
        ]
