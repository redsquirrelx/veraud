"""Developer-only bounds for the TestabilityProbeAgent loop.

Every field declared here is consumed by the graph; nothing here is decorative.
Provider pacing is inherited from the shared `AgentExecutionConfig` and becomes
effective the moment the LLM makes a real model call.
"""

from typing import ClassVar

from pydantic import Field

from config.agents import AgentExecutionConfig


class TestabilityProbeConfig(AgentExecutionConfig):
    auto_install_node_dependencies: bool = Field(default=True,
        description="Install Node dependencies with lifecycle scripts disabled, in disposable copies only.")
    install_timeout_seconds: float = Field(default=240, gt=0,
        description="Timeout per Node dependency installation in the disposable workspace.")
    defaults: ClassVar = {
        "tools": [],  # This agent has its own bounded read-only tool layer; the shared repository tools are unused.
        "max_model_calls": 160,
        "max_total_tokens": 1_500_000,
        "timeout_seconds": 3600,
        # Developer-level exclusive preset: Google's free tier allows ~15 RPM; ~11 RPM keeps bursts safe.
        "provider_request_interval_seconds": 5.5,
    }
    max_repairs_per_verification: int = Field(
        default=3, ge=0, le=3,
        description="Maximum technical/oracle test-code repairs per verification; never repairs the repository.")
    max_investigation_iterations: int = Field(
        default=3, ge=1, le=16,
        description="Maximum LLM<->tool rounds of the read-only investigation loop per finding.")
    max_tool_calls_per_verification: int = Field(
        default=30, ge=1, le=100,
        description="Bounded read/search/write/run calls per verification.")
    max_files_read: int = Field(
        default=200, ge=1, le=2000,
        description="Distinct files read per run.")
    max_read_bytes_per_file: int = Field(
        default=64_000, ge=256, le=1_000_000,
        description="Bytes returned by a single read_file call.")
    max_test_file_bytes: int = Field(
        default=64_000, ge=256, le=500_000,
        description="Maximum size of a generated test file.")
    max_written_bytes: int = Field(
        default=256_000, ge=256, le=5_000_000,
        description="Maximum total bytes written into the disposable workspace per run.")
    max_test_run_seconds: float = Field(
        default=120, gt=0, allow_inf_nan=False,
        description="Wall-clock timeout for one pytest execution.")
    max_captured_output_bytes: int = Field(
        default=64_000, ge=256, le=1_000_000,
        description="Stdout/stderr retained for triage (extras are discarded, never persisted).")
    max_repo_copy_files: int = Field(
        default=10_000, ge=10,
        description="Maximum files in the disposable audited-repo copy; larger repos are blocked.")
    max_repo_copy_bytes: int = Field(
        default=256_000_000, ge=1_000_000,
        description="Maximum total bytes of the disposable audited-repo copy; larger repos are blocked.")
    allow_local_unsafe_execution: bool = Field(
        default=False,
        description=(
            "Development escape hatch: run the generated suite in a disposable copy "
            "of the repository on this machine. NOT a security sandbox; enable only "
            "for trusted fixtures."
        ),
    )
    provider_temperature_override: float | None = Field(
        default=None, ge=0.0, le=2.0,
        description="Override dev-agents.yaml temperature for this run; null keeps provider default.")
    green_control_dir: str | None = Field(
        default=None,
        description=(
            "Path to a checkout with the denounced condition removed (counter-example). "
            "When provided, verifications must FAIL at the audited baseline and PASS here; "
            "failed validation is retained as diagnosis, never reported as a verified fix."
        ),
    )
