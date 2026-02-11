"""Quick smoke-test for the three Groq cloud providers."""
import asyncio
import sys
from pathlib import Path

import httpx

# Ensure project root is on sys.path so 'src' is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main():
    from src.core.config import get_settings
    s = get_settings()
    print(f"Groq API key loaded: {bool(s.groq_api_key)}")
    if not s.groq_api_key:
        print("ERROR: No GROQ_API_KEY found in .env")
        sys.exit(1)

    passed = 0
    failed = 0

    # ---- LLM ----
    print("\n=== Groq LLM (llama-3.1-8b-instant) ===")
    try:
        from src.providers.llm.groq_provider import GroqLLMProvider
        from src.providers.llm.base import Message

        llm = GroqLLMProvider(model="llama-3.1-8b-instant", api_key=s.groq_api_key)
        health = await llm.health_check()
        print(f"Health check: {health}")

        r = await llm.generate([Message(role="user", content="Say hello in one sentence.")])
        print(f"Response: {r.content}")
        print(f"Tokens: {r.tokens_used}  Latency: {r.latency_ms:.0f}ms")
        await llm.close()
        print("LLM OK")
        passed += 1
    except Exception as e:
        print(f"LLM FAILED: {e}")
        failed += 1

    # ---- TTS ----
    tts_audio = None
    print("\n=== Groq TTS (orpheus-v1-english / troy) ===")
    try:
        from src.providers.tts.groq_tts_provider import GroqTTSProvider

        tts = GroqTTSProvider(api_key=s.groq_api_key)
        print(f"Provider info: {tts.get_provider_info()}")

        result = await tts.synthesize("Hello, this is a test of Groq TTS.")
        tts_audio = result.audio_data
        print(f"Audio: {len(result.audio_data)} bytes, {result.sample_rate}Hz, {result.duration_seconds:.2f}s")
        await tts.close()
        print("TTS OK")
        passed += 1
    except httpx.HTTPStatusError as e:
        # Parse the JSON error body returned by Groq
        try:
            body = e.response.json()
            error_obj = body.get("error", {})
            error_code = error_obj.get("code", "")
            error_msg = error_obj.get("message", str(e))
        except Exception:
            error_code = ""
            error_msg = e.response.text or str(e)

        if error_code == "model_terms_required" or "terms" in error_msg.lower():
            print("TTS SKIPPED: Orpheus model terms not yet accepted.")
            print("  -> Go to: https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english")
            print("  -> Accept the terms, then re-run this test.")
        else:
            print(f"TTS FAILED ({e.response.status_code}): {error_msg}")
            failed += 1
    except Exception as e:
        print(f"TTS FAILED: {e}")
        failed += 1

    # ---- STT ----
    print("\n=== Groq STT (whisper-large-v3-turbo) ===")
    try:
        from src.providers.stt.groq_whisper_provider import GroqWhisperSTTProvider

        stt = GroqWhisperSTTProvider(api_key=s.groq_api_key)
        print(f"Provider info: {stt.get_model_info()}")

        if tts_audio:
            # Use TTS output as STT input (round-trip test)
            transcript = await stt.transcribe(tts_audio)
            print(f"Transcription: {transcript.text}")
            print(f"Language: {transcript.language}  Confidence: {transcript.confidence:.2f}  Duration: {transcript.duration_seconds:.2f}s")
        else:
            # No TTS audio available — test with a minimal WAV
            # Generate a tiny silent WAV to confirm the API accepts our request format
            import wave, io, struct
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                # 0.5 second of silence
                wf.writeframes(b"\x00\x00" * 8000)
            silent_wav = buf.getvalue()
            transcript = await stt.transcribe(silent_wav)
            print(f"Transcription (silent audio): '{transcript.text}'")
            print(f"Language: {transcript.language}  Duration: {transcript.duration_seconds:.2f}s")

        await stt.close()
        print("STT OK")
        passed += 1
    except Exception as e:
        print(f"STT FAILED: {e}")
        failed += 1

    # ---- Summary ----
    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("All Groq providers working!")
    else:
        print("Some providers had issues — see above.")


if __name__ == "__main__":
    asyncio.run(main())
