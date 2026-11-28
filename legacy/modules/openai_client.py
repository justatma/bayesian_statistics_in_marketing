# openai_client.py

import os
from dotenv import load_dotenv
import openai

load_dotenv()

def generate_insight_narrative(summary):
    openai_api_key = os.getenv("OPENAI_API_KEY")
    client = openai.OpenAI(api_key=openai_api_key)
    prompt = (
        "You are a marketing analyst. Given this ad performance summary, "
        "write a brief, insightful narrative for a marketing team:\n"
        f"{summary}"
    )
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=200
    )
    return response.choices[0].message.content

