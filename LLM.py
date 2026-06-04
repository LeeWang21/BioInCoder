import os
from langchain_deepseek import ChatDeepSeek

#---------------------
#llm model
#----------------------
# 推荐在 shell 里设置：
os.environ["DEEPSEEK_API_KEY"] = "sk-dc3b68654c7f4994a9b2d082170f311b"
# 不建议把 key 写进脚本
llm = ChatDeepSeek(model="deepseek-v4-pro", extra_body = {"thinking": {"type": "disabled"}})
#llm = ChatDeepSeek(model="deepseek-v4-pro", extra_body = {"thinking": {"type": "enabled"}})
