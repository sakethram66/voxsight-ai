import edge_tts


_VOICES = {
    "te-IN": "te-IN-ShrutiNeural",
    "hi-IN": "hi-IN-SwaraNeural",
}


async def synthesize_speech(text: str, language: str) -> bytes:
    voice = _VOICES.get(language)
    if voice is None:
        raise ValueError("Unsupported speech language.")

    audio = bytearray()
    async for event in edge_tts.Communicate(text, voice).stream():
        if event["type"] == "audio":
            audio.extend(event["data"])
    if not audio:
        raise RuntimeError("Speech service returned no audio.")
    return bytes(audio)