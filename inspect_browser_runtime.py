import os
import shutil

from AgentConfigSetup import multi_agent_runtime


def main() -> None:
    registry = multi_agent_runtime.agent_registry
    message_container = multi_agent_runtime.message_container

    agent_browser_bin = os.environ.get("BIOINCODER_AGENT_BROWSER_BIN", "agent-browser")
    cloakbrowser_bin = os.environ.get("BIOINCODER_CLOAKBROWSER_BIN", "cloakbrowser")

    print("BioInCoder browser runtime")
    print(f"agents: {registry.list_agents()}")
    print(f"channels: {list(message_container.channels.keys())}")
    print(f"browser_registered: {'browser' in registry.agent_configs}")
    print(f"browser_channel_registered: {'Browser_Channel' in message_container.channels}")
    print(f"agent-browser bin: {agent_browser_bin}")
    print(f"agent-browser found: {shutil.which(agent_browser_bin) or 'NO'}")
    print(f"cloakbrowser bin: {cloakbrowser_bin}")
    print(f"cloakbrowser found: {shutil.which(cloakbrowser_bin) or 'NO'}")
    print(f"cloakbrowser required: {os.environ.get('BIOINCODER_CLOAKBROWSER_REQUIRED', '1')}")
    print(f"cloakbrowser auto config: {os.environ.get('BIOINCODER_CLOAKBROWSER_AUTO_CONFIG', '1')}")
    print(f"browser headless: {os.environ.get('BIOINCODER_BROWSER_HEADLESS', '1')}")
    print(
        "AGENT_BROWSER_EXECUTABLE_PATH configured: "
        f"{bool(os.environ.get('AGENT_BROWSER_EXECUTABLE_PATH'))}"
    )
    print(f"AGENT_BROWSER_ARGS configured: {bool(os.environ.get('AGENT_BROWSER_ARGS'))}")


if __name__ == "__main__":
    main()
