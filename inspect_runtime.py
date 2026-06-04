from AgentConfigSetup import multi_agent_runtime


def main() -> None:
    message_container = multi_agent_runtime.message_container

    print("BioInCoder runtime")
    print(f"user_id: {message_container.config.user_id}")
    print(f"session_id: {message_container.config.session_id}")
    print(f"agents: {multi_agent_runtime.agent_registry.list_agents()}")
    print(f"channels: {list(message_container.channels.keys())}")
    print(f"jupyter_sessions: {multi_agent_runtime.jupyter_registry.list_sessions()}")


if __name__ == "__main__":
    main()
