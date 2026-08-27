import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.environ.get("UM_AI_API_KEY"),
    base_url=os.environ.get("UM_AI_BASE_URL"),
)

modelos = client.models.list()
for m in modelos.data:
    print(m.id)