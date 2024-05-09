import json, os

from django_core.config import Config


class Constants:
    """Constants"""

    CHAT_HISTORY_WINDOW = 4
    ASR_DEFAULT_CONFIDENCE_SCORE = 0.7

    MESSAGE_INPUT_TYPE_TEXT = "text"
    MESSAGE_INPUT_TYPE_VOICE = "voice"

    LANGUAGE_SHORT_CODE_ENG = "en"
    LANGUAGE_BCP_CODE_NATIVE = Config.LANGUAGE_BCP_CODE_NATIVE
    LANGUAGE_SHORT_CODE_NATIVE = Config.LANGUAGE_SHORT_CODE_NATIVE

    GOOGLE_SPEECH_SYNTHESIS_MODEL = "GOOGLE_SPEECH_SYNTHESIS_MODEL"
    AZURE_SPEECH_SYNTHESIS_MODEL = "AZURE_SPEECH_SYNTHESIS_MODEL"

    UNANSWERED_PHRASES = [
        "out of my context",
        "out of context",
        "not mentioned in the given context",
        " rephrase ",
        " reframe ",
        "topic was not in my last update",
        "topic wasn't in my last update",
        "I do not have information",
        "I don't have information",
        "I don't have real-time information",
        "thought of stumping an AI",
    ]

    HERE_ARE_FOLLOW_UP_QUESTIONS_TO_ASK_TEXT = "\n\nHere are the follow-up questions you can ask:\n"

    MP3 = "mp3"
    OGG = "ogg"

    EMBEDDING_MODEL = "text-embedding-3-small"
