import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("UM_AI_API_KEY"),
    base_url=os.environ.get("UM_AI_BASE_URL"),
)

MODEL = os.environ.get("UM_AI_MODEL", "gpt-oss-20b")