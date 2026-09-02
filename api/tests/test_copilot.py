"""The copilot's tool-calling loop and its tool implementations."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from api import ats
from api.copilot import CopilotTools, ToolExecutionError, run_copilot
from api.llm import LLMNotConfigured, LLMResponse
from api.models import CandidateModel, JobModel, ProfileModel


@pytest.fixture
def ats_data(db_session):
    job_profile = ProfileModel(
        type="job",
        raw_text="Vaga SRE",
        redacted_text="Vaga SRE",
        redaction_map={},
        extracted_profile={
            "skills_raw": ["Kubernetes"],
            "skills_normalized": [{"preferred_label": "Kubernetes", "concept_uri": "u/k8s"}],
            "narrative_experience": "Plataforma.",
            "seniority": "Pleno",
            "experience_years": 4.0,
        },
    )
    candidate_profile = ProfileModel(
        type="candidate",
        raw_text="Tatiana opera Kubernetes há 6 anos.",
        redacted_text="[NOME_REDACT_1] opera Kubernetes há 6 anos.",
        redaction_map={"[NOME_REDACT_1]": "Tatiana Reis"},
        extracted_profile={
            "skills_raw": ["Kubernetes"],
            "skills_normalized": [{"preferred_label": "Kubernetes", "concept_uri": "u/k8s"}],
            "narrative_experience": "SRE.",
            "seniority": "Pleno",
            "experience_years": 6.0,
        },
    )
    db_session.add_all([job_profile, candidate_profile])
    db_session.commit()

    job = JobModel(profile_id=job_profile.id, title="SRE Pleno", status="open", seniority="Pleno")
    candidate = CandidateModel(
        profile_id=candidate_profile.id, display_name="Tatiana Reis", headline="SRE"
    )
    db_session.add_all([job, candidate])
    db_session.commit()
    return {"db": db_session, "job": job, "candidate": candidate}


def _tool_call(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _response(content: str = "", tool_calls=None) -> LLMResponse:
    return LLMResponse(content=content, model="test/model", tool_calls=tool_calls or [])


# ── Tools ───────────────────────────────────────────────────────────────────
def test_listar_vagas_returns_a_digest_and_a_card(ats_data):
    result = CopilotTools(ats_data["db"]).listar_vagas()
    assert result["digest"][0]["title"] == "SRE Pleno"
    assert result["card"]["type"] == "jobs"


def test_listar_vagas_honours_the_status_filter(ats_data):
    assert CopilotTools(ats_data["db"]).listar_vagas(status="closed")["digest"] == []


def test_detalhar_candidato_returns_the_profile(ats_data):
    result = CopilotTools(ats_data["db"]).detalhar_candidato(ats_data["candidate"].id)
    assert result["digest"]["nome"] == "Tatiana Reis"
    assert "Kubernetes" in result["digest"]["skills"]


def test_detalhar_candidato_raises_for_an_unknown_id(ats_data):
    with pytest.raises(ToolExecutionError):
        CopilotTools(ats_data["db"]).detalhar_candidato(9999)


def test_mover_candidatura_rejects_an_invalid_stage(ats_data):
    application = ats.ensure_application(
        ats_data["db"], ats_data["candidate"].id, ats_data["job"].id
    )
    with pytest.raises(ToolExecutionError, match="inválida"):
        CopilotTools(ats_data["db"]).mover_candidatura(application.id, "aprovadissimo")


def test_mover_candidatura_advances_the_funnel(ats_data):
    application = ats.ensure_application(
        ats_data["db"], ats_data["candidate"].id, ats_data["job"].id
    )
    result = CopilotTools(ats_data["db"]).mover_candidatura(application.id, "offer")
    assert result["digest"]["nova_etapa"] == "Proposta"
    assert result["card"]["application"]["stage"] == "offer"


def test_resumo_pipeline_returns_the_overview(ats_data):
    result = CopilotTools(ats_data["db"]).resumo_pipeline()
    assert result["digest"]["jobs_open"] == 1
    assert result["card"]["type"] == "overview"


# ── Conversation loop ───────────────────────────────────────────────────────
def test_a_plain_answer_short_circuits_the_loop(ats_data):
    llm = MagicMock()
    llm.is_configured = True
    llm.complete.return_value = _response("Temos 1 vaga aberta.")

    result = run_copilot(ats_data["db"], "quantas vagas?", client=llm)

    assert result["reply"] == "Temos 1 vaga aberta."
    assert result["tool_calls"] == []
    assert llm.complete.call_count == 1


def test_a_tool_call_is_executed_and_fed_back(ats_data):
    llm = MagicMock()
    llm.is_configured = True
    llm.complete.side_effect = [
        _response(tool_calls=[_tool_call("listar_vagas", {})]),
        _response("Você tem a vaga de SRE Pleno."),
    ]

    result = run_copilot(ats_data["db"], "quais vagas?", client=llm)

    assert result["tool_calls"] == [{"name": "listar_vagas", "arguments": {}, "ok": True}]
    assert result["cards"][0]["type"] == "jobs"
    assert "SRE" in result["reply"]

    # The tool result must have been appended as a `tool` message.
    second_call_messages = llm.complete.call_args_list[1].args[0]
    assert second_call_messages[-1]["role"] == "tool"
    assert second_call_messages[-1]["name"] == "listar_vagas"


def test_an_unknown_tool_is_reported_back_to_the_model(ats_data):
    llm = MagicMock()
    llm.is_configured = True
    llm.complete.side_effect = [
        _response(tool_calls=[_tool_call("demitir_todo_mundo", {})]),
        _response("Não posso fazer isso."),
    ]

    result = run_copilot(ats_data["db"], "faz aí", client=llm)

    assert result["tool_calls"][0]["ok"] is False
    payload = json.loads(llm.complete.call_args_list[1].args[0][-1]["content"])
    assert "não existe" in payload["erro"]


def test_a_failing_tool_does_not_break_the_turn(ats_data):
    llm = MagicMock()
    llm.is_configured = True
    llm.complete.side_effect = [
        _response(tool_calls=[_tool_call("detalhar_candidato", {"candidate_id": 9999})]),
        _response("Não encontrei esse candidato."),
    ]

    result = run_copilot(ats_data["db"], "detalha o 9999", client=llm)

    assert result["tool_calls"][0]["ok"] is False
    assert "Não encontrei" in result["reply"]


def test_malformed_tool_arguments_degrade_to_defaults(ats_data):
    llm = MagicMock()
    llm.is_configured = True
    broken = {
        "id": "c1",
        "type": "function",
        "function": {"name": "listar_vagas", "arguments": "{isso não é json"},
    }
    llm.complete.side_effect = [_response(tool_calls=[broken]), _response("ok")]

    result = run_copilot(ats_data["db"], "lista", client=llm)
    assert result["tool_calls"][0]["ok"] is True


def test_the_loop_gives_up_after_the_round_limit(ats_data):
    llm = MagicMock()
    llm.is_configured = True
    # Always asks for another tool; the guard must force a final answer.
    llm.complete.side_effect = [
        *[_response(tool_calls=[_tool_call("listar_vagas", {})]) for _ in range(5)],
        _response("Aqui está o que apurei."),
    ]

    result = run_copilot(ats_data["db"], "loop", client=llm)

    assert result["reply"] == "Aqui está o que apurei."
    assert llm.complete.call_count == 6


def test_history_is_forwarded_to_the_model(ats_data):
    llm = MagicMock()
    llm.is_configured = True
    llm.complete.return_value = _response("ok")

    run_copilot(
        ats_data["db"],
        "e agora?",
        history=[{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}],
        client=llm,
    )

    messages = llm.complete.call_args.args[0]
    assert [m["content"] for m in messages if m["role"] == "user"] == ["oi", "e agora?"]


def test_copilot_requires_an_api_key(ats_data):
    llm = MagicMock()
    llm.is_configured = False
    with pytest.raises(LLMNotConfigured):
        run_copilot(ats_data["db"], "oi", client=llm)


def test_the_chat_endpoint_rejects_an_empty_message(client):
    response = client.post("/copilot/chat", json={"message": "   ", "history": []})
    assert response.status_code == 400


def test_the_tools_endpoint_lists_the_catalogue(client):
    body = client.get("/copilot/tools").json()
    names = [t["name"] for t in body["tools"]]
    assert "ranquear_candidatos" in names
    assert body["suggestions"]
