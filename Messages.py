import warnings
from typing import Literal
from dataclasses import dataclass, field
from pathlib import Path
import json

from langchain_core.messages import AnyMessage, get_buffer_string, messages_to_dict, messages_from_dict



@dataclass
class MessageContainerConfig:
    default_channels: list[str] = field(default_factory=list)
    allow_create_channel: bool = True
    user_id: str | None = None
    session_id: str | None = None
    storage_dir: str | Path | None = None
    autosave: bool = True
    autoload: bool = True



@dataclass
class MessageContainer:
    config: MessageContainerConfig = field(default_factory=MessageContainerConfig)
    channels: dict[str, dict[str, list[AnyMessage]]] = field(default_factory=dict)


    def __post_init__(self) -> None:
        for channel in self.config.default_channels:
            self.add_channel(channel)
        if self.config.autoload and self.config.storage_dir is not None:
            self.load_all_requestMsgs(self.config.storage_dir, strict_metadata=True)


    def add_channel(self, channel_name: str) -> None:
        self.channels.setdefault(channel_name, {})


    def add_requestMsgs(self, channel_name: str, request_id:str, messages: list[AnyMessage]) -> None:
        if channel_name not in self.channels:
            if self.config.allow_create_channel:
                warnings.warn(f"Channel '{channel_name}' does not exist. Creating channel since allow_create_channel is True.")
                self.add_channel(channel_name)
            else:
                raise ValueError(f"Channel '{channel_name}' does not exist and channel creation is disabled.")
              
        self.channels[channel_name][request_id] = messages
        self._autosave_requestMsgs(channel_name, request_id)


    def add_requestMsg(self, channel_name: str, request_id: str, message: AnyMessage) -> None:
        if channel_name not in self.channels:
            if self.config.allow_create_channel:
                warnings.warn(f"Channel '{channel_name}' does not exist. Creating channel since allow_create_channel is True.")
                self.add_channel(channel_name)
            else:
                raise ValueError(f"Channel '{channel_name}' does not exist and channel creation is disabled.")
            
        if request_id not in self.channels[channel_name].keys():
            raise ValueError(f"Request_id '{request_id}' does not exist in the channel '{channel_name}'")
        else:
            self.channels[channel_name][request_id].append(message)


    def clear_channel(self, channel_name: str) -> None:
        if channel_name in self.channels:
            self.channels[channel_name] = {}
        else:
            raise ValueError(f"Channel '{channel_name}' does not exist.")


    def clear_requestMsgs(self, channel_name: str, request_id: str) -> None:
        if channel_name not in self.channels:
            raise ValueError(f"Channel '{channel_name}' does not exist")
        else:
            if request_id not in self.channels[channel_name].keys():
                raise ValueError(f"Request_id '{request_id}' does not exist in the channel '{channel_name}'")
            else:
                del self.channels[channel_name][request_id]


    def get_requestMsgs(
        self,
        channel_name: str,
        request_id: str,
    ) -> list[AnyMessage]:
        if channel_name not in self.channels:
            raise ValueError(f"Channel '{channel_name}' does not exist")

        if request_id not in self.channels[channel_name]:
            raise ValueError(
                f"Request_id '{request_id}' does not exist in the channel '{channel_name}'"
            )

        return self.channels[channel_name][request_id]


    def string_requestMsgs(
        self,
        channel_name: str,
        request_id: str,
        format: Literal["prefix", "xml"] = "prefix",
    ) -> str | list[dict]:

        messages = self.get_requestMsgs(channel_name = channel_name, request_id = request_id)

        if format == "prefix":
            return get_buffer_string(messages, format="prefix")

        if format == "xml":
            return get_buffer_string(messages, format="xml")

        raise ValueError(f"Unsupported format: {format}")

    def _safe_file_component(self, value: str) -> str:
        safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-")
        return safe or "unnamed"

    def requestMsgs_file_path(self, channel_name: str, request_id: str, root_dir: str | Path | None = None) -> Path:
        root = Path(root_dir or self.config.storage_dir or "artifacts/messages")
        filename = f"{self._safe_file_component(channel_name)}__{self._safe_file_component(request_id)}.json"
        return root / filename

    def _autosave_requestMsgs(self, channel_name: str, request_id: str) -> None:
        if not self.config.autosave or self.config.storage_dir is None:
            return
        self.save_requestMsgs(
            channel_name=channel_name,
            request_id=request_id,
            file_path=self.requestMsgs_file_path(channel_name, request_id),
            overwrite=True,
        )
    

    def save_requestMsgs(
        self,
        channel_name: str,
        request_id: str,
        file_path: str | Path,
        overwrite: bool = False,
        user_id: str | None = None,
        session_id: str | None = None
    ) -> Path:
        messages = self.get_requestMsgs(channel_name, request_id)

        path = Path(file_path)

        if path.exists() and not overwrite:
            raise FileExistsError(f"File already exists: {path}")

        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "user_id": user_id or self.config.user_id,
            "session_id": session_id or self.config.session_id,
            "channel_name": channel_name,
            "request_id": request_id,
            "messages": messages_to_dict(messages),
        }

        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return path

    def load_all_requestMsgs(
        self,
        root_dir: str | Path,
        overwrite: bool = True,
        strict_metadata: bool = False,
    ) -> list[Path]:
        root = Path(root_dir)
        if not root.exists():
            return []

        loaded_paths: list[Path] = []
        for path in sorted(root.glob("*.json")):
            self.load_requestMsgs(
                path,
                overwrite=overwrite,
                strict_metadata=strict_metadata,
            )
            loaded_paths.append(path)
        return loaded_paths

    def load_requestMsgs(
        self,
        file_path: str | Path,
        channel_name: str | None = None,
        request_id: str | None = None,
        overwrite: bool = False,
        user_id: str | None = None,
        session_id: str | None = None,
        strict_metadata: bool = False,
    ) -> list[AnyMessage]:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File does not exist: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))

        loaded_user_id = payload.get("user_id")
        loaded_session_id = payload.get("session_id")

        expected_user_id = user_id or self.config.user_id
        expected_session_id = session_id or self.config.session_id

        if strict_metadata:
            if loaded_user_id != expected_user_id:
                raise ValueError(
                    f"user_id mismatch: file has '{loaded_user_id}', "
                    f"but expected '{expected_user_id}'"
                )

            if loaded_session_id != expected_session_id:
                raise ValueError(
                    f"session_id mismatch: file has '{loaded_session_id}', "
                    f"but expected '{expected_session_id}'"
                )

        loaded_channel_name = channel_name or payload["channel_name"]
        loaded_request_id = request_id or payload["request_id"]

        messages = messages_from_dict(payload["messages"])

        if loaded_channel_name not in self.channels:
            if self.config.allow_create_channel:
                self.add_channel(loaded_channel_name)
            else:
                raise ValueError(
                    f"Channel '{loaded_channel_name}' does not exist and "
                    f"channel creation is disabled."
                )

        if loaded_request_id in self.channels[loaded_channel_name] and not overwrite:
            raise ValueError(
                f"Request_id '{loaded_request_id}' already exists in channel "
                f"'{loaded_channel_name}'. Set overwrite=True to replace it."
            )

        self.channels[loaded_channel_name][loaded_request_id] = messages

        return messages
    
