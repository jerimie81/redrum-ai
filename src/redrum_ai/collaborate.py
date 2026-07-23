def apply_tone(prompt: str, user_mood: str) -> str:
    """Adapts the system prompt based on user mood (Item 240)."""
    tones = {
        "frustrated": "The user is frustrated. Be extremely patient, reliable, and empathetic. Focus on guaranteed fixes (Item 244, 249).",
        "burnout": "The user might be experiencing burnout. Suggest breaks and keep tasks lightweight (Item 241).",
        "celebratory": "Celebrate the user's success! Use emojis and positive reinforcement (Item 248)."
    }
    return prompt + "\n" + tones.get(user_mood, "")

def rubber_duck_mode(config, query: str) -> str:
    """Rubber Duck mode: Listens and prompts the user to explain logic (Item 243)."""
    from redrum_ai.model import send_to_ollama
    prompt = f"The user is explaining their logic: {query}\nRespond by validating their thought process and asking one guiding question to help them realize the answer themselves. Do NOT just give the answer (Item 242)."
    return send_to_ollama(config, prompt)
