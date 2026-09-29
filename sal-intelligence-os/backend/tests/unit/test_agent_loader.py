from app.services.agent_loader import list_agent_names, load_agent, load_domain_routing


def test_all_26_agents_load_without_error():
    names = list_agent_names()
    assert len(names) == 26
    for name in names:
        spec = load_agent(name)
        assert spec.name == name
        assert spec.system_prompt  # nenhum agente com corpo vazio


def test_domain_routing_only_references_existing_agents():
    routing = load_domain_routing()
    known_agents = set(list_agent_names())
    for case_type, agents in routing.items():
        unknown = set(agents) - known_agents
        assert not unknown, f"{case_type} referencia agentes inexistentes: {unknown}"
