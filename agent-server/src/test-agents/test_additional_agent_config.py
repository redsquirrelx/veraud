"""Legacy-protocol agents consume local developer policy and shared model settings."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from config.agents import ModelSettings, ProviderRateLimits, ProviderRetryConfig
from config.agents.catalog import describe_agent_config, validate_agent_config
from server.agents.functional_adequacy.config import FunctionalAdequacyConfig
from server.agents.security.config import SecurityConfig
from server.agents.security.schemas import Finding
from server.agents.security.security_component import SecurityComponentAgent
from server.runtimes.investigation.provider import ProviderPacer
from server.runtimes.repository.model_runtime import ModelGateway


def test_provider_protocols_resolve_default_retry_policy_from_the_same_config():
    policy = ProviderRetryConfig(max_provider_retries=3,
        provider_request_interval_seconds=0.5, provider_retry_backoff_seconds=4)
    gateway = ModelGateway(object(), provider_config=policy)
    pacer = ProviderPacer(rate_limits=ProviderRateLimits(), provider_config=policy)
    assert gateway.pacer.max_retries == pacer.max_retries == policy.max_provider_retries
    assert gateway.pacer.interval == pacer.interval == policy.provider_request_interval_seconds
    assert gateway.pacer.backoff == pacer.backoff == policy.provider_retry_backoff_seconds
    explicit = ModelGateway(object(), provider_config=policy, max_retries=0, interval=0, backoff=0)
    assert explicit.pacer.max_retries == explicit.pacer.interval == explicit.pacer.backoff == 0


def test_security_components_share_one_config_and_remediation_uses_its_model_and_prompt(monkeypatch, tmp_path):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"patch_code": "safe"})))])

    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))))
    config = SecurityConfig(knowledge_database_path=str(tmp_path / "patterns.db"),
        remediation_model=ModelSettings(provider="openai", name="offline-model", temperature=0, max_tokens=512),
        remediation_system_prompt="Developer security instructions", dast_dispatch_delay_seconds=0)
    component = SecurityComponentAgent(config=config)
    assert component.enrichment_agent.config is component.dast_agent.config is component.remediation_agent.config is config
    assert component.enrichment_agent.db_path == tmp_path / "patterns.db"
    finding = Finding(finding_id="f", file_path="source.py", line_number=1, rule_id="SEC-001",
        rule_name="Secret", severity="HIGH", category="Secret", owasp_category="A07", snippet="secret", matched_text="secret")
    assert component.remediation_agent._call_llm(finding)["patch_code"] == "safe"
    assert requests[0]["model"] == "offline-model" and requests[0]["temperature"] == 0
    assert requests[0]["max_tokens"] == 512
    assert requests[0]["messages"][0]["content"] == config.remediation_system_prompt


def test_retrieval_and_security_controls_remain_developer_only():
    assert FunctionalAdequacyConfig().retrieval_top_k == 5
    assert FunctionalAdequacyConfig().embedding_model == "all-MiniLM-L6-v2"
    for agent_id in ("functional_adequacy", "security"):
        assert describe_agent_config(agent_id)["config_schema"]["properties"] == {}
        assert validate_agent_config(agent_id, {})
        assert describe_agent_config(agent_id, level="developer")["specific_fields"]


def test_functional_retrieval_consumes_configured_embedding_model_and_candidate_count():
    # Isolate the lightweight embedding fake from optional real-provider tests.
    import config.agents as config_package

    script = '''
import asyncio
import sys
from types import ModuleType, SimpleNamespace

loaded = []
class Embedding:
    def __init__(self, name):
        loaded.append(name)
    def encode(self, texts, **kwargs):
        return texts
class Scores(list):
    def argsort(self, **kwargs):
        return sorted(range(len(self)), key=self.__getitem__, reverse=True)
fake = ModuleType("sentence_transformers")
fake.SentenceTransformer = Embedding
fake.util = SimpleNamespace(cos_sim=lambda *_: [Scores([0.2, 0.9, 0.4])])
sys.modules["sentence_transformers"] = fake

from config.agents import AgentSettings
from server.agents.functional_adequacy.agent import FunctionalAdequacyAgent
from server.agents.functional_adequacy.config import FunctionalAdequacyConfig
from server.agents.functional_adequacy.schemas import FunctionalAdequacyInput

agent = FunctionalAdequacyAgent(AgentSettings(agent_id="functional_adequacy", timeout_seconds=10), object(),
    config=FunctionalAdequacyConfig(embedding_model="configured-embedding", retrieval_top_k=2))
data = FunctionalAdequacyInput(requirements=[{"requirement_id": "req", "description": "behavior"}],
    code_fragments=[{"fragment_id": f"f{i}", "file_path": f"{i}.py", "code": "behavior"} for i in range(3)])
result = asyncio.run(agent._code_mapping({"input_data": data}))
assert loaded == ["configured-embedding"]
assert [e.fragment_id for e in result["candidates"]["req"]] == ["f1", "f2"]
'''
    root = Path(config_package.__file__).parents[2]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(root), str(root / "src")))}
    result = subprocess.run([sys.executable, "-c", script], check=False,
        env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
