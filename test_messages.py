from pathlib import Path
import tempfile

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from Messages import MessageContainer, MessageContainerConfig


def test_basic_container():
    config = MessageContainerConfig(
        user_id="user_001",
        session_id="session_001",
    )

    container = MessageContainer(config=config)

    assert "Chat_Channel" in container.channels
    assert "Plan_Channel" in container.channels
    assert "Code_Channel" in container.channels

    assert container.config.user_id == "user_001"
    assert container.config.session_id == "session_001"

    print("PASS: default channels initialized")


def test_add_requestMsgs_as_primary():
    container = MessageContainer()
    request_id = "req_001"

    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="你好，我想设计一个 MessageContainer。"),
        AIMessage(content="可以。建议用 channel -> request_id -> messages 的结构。"),
    ]

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        messages=messages,
    )

    loaded = container.get_requestMsgs("Chat_Channel", request_id)

    assert len(loaded) == 3
    assert loaded[0].content == "You are a helpful assistant."
    assert loaded[1].content == "你好，我想设计一个 MessageContainer。"
    assert loaded[2].content == "可以。建议用 channel -> request_id -> messages 的结构。"

    print("PASS: add_requestMsgs creates request message list")


def test_add_requestMsg_only_appends_existing_request():
    container = MessageContainer()
    request_id = "req_002"

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        messages=[
            HumanMessage(content="第一条消息。"),
        ],
    )

    container.add_requestMsg(
        channel_name="Chat_Channel",
        request_id=request_id,
        message=AIMessage(content="这是补充回复。"),
    )

    messages = container.get_requestMsgs("Chat_Channel", request_id)

    assert len(messages) == 2
    assert messages[0].content == "第一条消息。"
    assert messages[1].content == "这是补充回复。"

    print("PASS: add_requestMsg appends to existing request")


def test_add_requestMsg_rejects_missing_request_id():
    container = MessageContainer()

    try:
        container.add_requestMsg(
            channel_name="Chat_Channel",
            request_id="missing_req",
            message=HumanMessage(content="这条不应该被自动创建。"),
        )
        raise AssertionError("Expected ValueError for missing request_id, but no error was raised.")
    except ValueError as e:
        assert "Request_id" in str(e) or "request_id" in str(e)

    assert "missing_req" not in container.channels["Chat_Channel"]

    print("PASS: add_requestMsg rejects missing request_id")


def test_dynamic_channel_creation_with_add_requestMsgs():
    container = MessageContainer()
    request_id = "req_003"

    container.add_requestMsgs(
        channel_name="Memory_Channel",
        request_id=request_id,
        messages=[
            HumanMessage(content="请记住这段上下文。"),
        ],
    )

    assert "Memory_Channel" in container.channels
    assert request_id in container.channels["Memory_Channel"]
    assert container.channels["Memory_Channel"][request_id][0].content == "请记住这段上下文。"

    print("PASS: add_requestMsgs can create dynamic channel when allowed")


def test_dynamic_channel_creation_disabled():
    config = MessageContainerConfig(
        allow_create_channel=False,
    )

    container = MessageContainer(config=config)

    try:
        container.add_requestMsgs(
            channel_name="Memory_Channel",
            request_id="req_004",
            messages=[HumanMessage(content="这条不应该被添加。")],
        )
        raise AssertionError("Expected ValueError for missing channel, but no error was raised.")
    except ValueError as e:
        assert "Channel" in str(e)

    assert "Memory_Channel" not in container.channels

    print("PASS: dynamic channel creation can be disabled")


def test_string_prefix():
    container = MessageContainer()
    request_id = "req_005"

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        messages=[
            HumanMessage(content="Hello"),
            AIMessage(content="Hi, how can I help?"),
        ],
    )

    text = container.string_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        format="prefix",
    )

    print("\n--- prefix transcript ---")
    print(text)

    assert "Human" in text
    assert "Hello" in text
    assert "AI" in text or "Assistant" in text
    assert "Hi, how can I help?" in text

    print("PASS: string_requestMsgs prefix")


def test_string_xml():
    container = MessageContainer()
    request_id = "req_006"

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        messages=[
            HumanMessage(content="请总结这段对话。"),
            AIMessage(content="好的，我会总结。"),
        ],
    )

    xml_text = container.string_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        format="xml",
    )

    print("\n--- xml transcript ---")
    print(xml_text)

    assert "human" in xml_text
    assert "Assistant" in xml_text or "ai" in xml_text
    assert "请总结这段对话。" in xml_text
    assert "好的，我会总结。" in xml_text

    print("PASS: string_requestMsgs xml")


def test_get_missing_request_raises_error():
    container = MessageContainer()

    try:
        container.get_requestMsgs(
            channel_name="Chat_Channel",
            request_id="missing_req",
        )
        raise AssertionError("Expected ValueError for missing request_id, but no error was raised.")
    except ValueError as e:
        assert "Request_id" in str(e) or "request_id" in str(e)

    print("PASS: get_requestMsgs rejects missing request_id")


def test_clear_requestMsgs():
    container = MessageContainer()
    request_id = "req_007"

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        messages=[
            HumanMessage(content="这条稍后会被删除。"),
        ],
    )

    assert request_id in container.channels["Chat_Channel"]

    container.clear_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
    )

    assert request_id not in container.channels["Chat_Channel"]

    print("PASS: clear_requestMsgs deletes request")


def test_clear_channel():
    container = MessageContainer()

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id="req_008",
        messages=[
            HumanMessage(content="这条消息在 channel 里。"),
        ],
    )

    assert len(container.channels["Chat_Channel"]) == 1

    container.clear_channel("Chat_Channel")

    assert container.channels["Chat_Channel"] == {}

    print("PASS: clear_channel clears all requests in channel")


def test_save_and_load_messages():
    config = MessageContainerConfig(
        user_id="user_001",
        session_id="session_001",
    )

    container = MessageContainer(config=config)
    request_id = "req_009"

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        messages=[
            HumanMessage(content="保存这条消息。"),
            AIMessage(content="好的，已经准备保存。"),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "req_009.json"

        saved_path = container.save_requestMsgs(
            channel_name="Chat_Channel",
            request_id=request_id,
            file_path=file_path,
            overwrite=True,
        )

        assert saved_path.exists()

        new_container = MessageContainer(config=config)

        loaded_messages = new_container.load_requestMsgs(
            file_path=saved_path,
            overwrite=True,
            strict_metadata=True,
        )

        assert len(loaded_messages) == 2
        assert loaded_messages[0].content == "保存这条消息。"
        assert loaded_messages[1].content == "好的，已经准备保存。"

        loaded_text = new_container.string_requestMsgs(
            channel_name="Chat_Channel",
            request_id=request_id,
            format="prefix",
        )

        print("\n--- loaded transcript ---")
        print(loaded_text)

        assert "保存这条消息。" in loaded_text
        assert "好的，已经准备保存。" in loaded_text

    print("PASS: save_requestMsgs and load_requestMsgs")


def test_load_with_override_channel_and_request_id():
    config = MessageContainerConfig(
        user_id="user_001",
        session_id="session_001",
    )

    container = MessageContainer(config=config)

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id="original_req",
        messages=[
            HumanMessage(content="原始 request。"),
            AIMessage(content="原始回复。"),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "original_req.json"

        container.save_requestMsgs(
            channel_name="Chat_Channel",
            request_id="original_req",
            file_path=file_path,
            overwrite=True,
        )

        new_container = MessageContainer(config=config)

        loaded_messages = new_container.load_requestMsgs(
            file_path=file_path,
            channel_name="Plan_Channel",
            request_id="loaded_as_new_req",
            overwrite=True,
            strict_metadata=True,
        )

        assert len(loaded_messages) == 2
        assert "loaded_as_new_req" in new_container.channels["Plan_Channel"]
        assert "original_req" not in new_container.channels["Plan_Channel"]

    print("PASS: load_requestMsgs supports channel/request_id override")


def test_load_existing_request_without_overwrite_raises_error():
    config = MessageContainerConfig(
        user_id="user_001",
        session_id="session_001",
    )

    container = MessageContainer(config=config)
    request_id = "req_010"

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        messages=[
            HumanMessage(content="原始消息。"),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "req_010.json"

        container.save_requestMsgs(
            channel_name="Chat_Channel",
            request_id=request_id,
            file_path=file_path,
            overwrite=True,
        )

        try:
            container.load_requestMsgs(
                file_path=file_path,
                overwrite=False,
            )
            raise AssertionError("Expected ValueError for existing request_id, but no error was raised.")
        except ValueError as e:
            assert "already exists" in str(e)

    print("PASS: load_requestMsgs prevents accidental overwrite")


def test_strict_metadata_error():
    config = MessageContainerConfig(
        user_id="user_001",
        session_id="session_001",
    )

    container = MessageContainer(config=config)
    request_id = "req_011"

    container.add_requestMsgs(
        channel_name="Chat_Channel",
        request_id=request_id,
        messages=[
            HumanMessage(content="测试 metadata。"),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "req_011.json"

        container.save_requestMsgs(
            channel_name="Chat_Channel",
            request_id=request_id,
            file_path=file_path,
            overwrite=True,
        )

        wrong_config_container = MessageContainer(
            config=MessageContainerConfig(
                user_id="wrong_user",
                session_id="session_001",
            )
        )

        try:
            wrong_config_container.load_requestMsgs(
                file_path=file_path,
                strict_metadata=True,
            )
            raise AssertionError("Expected metadata mismatch error, but no error was raised.")
        except ValueError as e:
            assert "user_id mismatch" in str(e)

    print("PASS: strict_metadata catches user_id mismatch")


if __name__ == "__main__":
    test_basic_container()
    test_add_requestMsgs_as_primary()
    test_add_requestMsg_only_appends_existing_request()
    test_add_requestMsg_rejects_missing_request_id()
    test_dynamic_channel_creation_with_add_requestMsgs()
    test_dynamic_channel_creation_disabled()
    test_string_prefix()
    test_string_xml()
    test_get_missing_request_raises_error()
    test_clear_requestMsgs()
    test_clear_channel()
    test_save_and_load_messages()
    test_load_with_override_channel_and_request_id()
    test_load_existing_request_without_overwrite_raises_error()
    test_strict_metadata_error()

    print("\nAll tests passed.")
