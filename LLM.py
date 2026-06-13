import os
from langchain_deepseek import ChatDeepSeek

#---------------------
#llm model
#----------------------
if not os.environ.get("DEEPSEEK_API_KEY"):
    raise RuntimeError(
        "DEEPSEEK_API_KEY is not set. Export it before running BioInCoder."
    )

llm = ChatDeepSeek(model="deepseek-v4-pro", extra_body={"thinking": {"type": "disabled"}})
llm_flash = ChatDeepSeek(model="deepseek-v4-flash", extra_body={"thinking": {"type": "disabled"}})
#llm = ChatDeepSeek(model="deepseek-v4-pro", extra_body={"thinking": {"type": "enabled"}})
