import time
from typing import Generic, List, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel


class Context(BaseModel):
    original_text: str


class Vocabulary(BaseModel):
    lemma: str
    Chinese: str


class TaskBase(BaseModel):
    id: str


class VocabularyTranslationTask(TaskBase):
    vocabulary: List[Vocabulary]
    context: Context
    index: int


class DialogueTranslationTask(TaskBase):
    original_text: str
    Chinese: str
    index: int


T = TypeVar("T", bound=TaskBase)


class TranslationTasks(BaseModel, Generic[T]):
    tasks: List[T]


class GeminiResponse(BaseModel, Generic[T]):
    tasks: List[T]
    total_token_count: int
    success: bool
    message: str = ""


def translate(
    api_key: str,
    translation_tasks: TranslationTasks[T],
    system_instruction: str,
    gemini_model: str = "gemini-2.0-flash",
    temperature: float = 0.3,
    max_retries: int = 3,
    retry_delay: int = 10,
) -> GeminiResponse[T]:
    """
    Query the Gemini API for translation tasks with retry logic.

    :param api_key: Gemini API key
    :param translation_tasks: Translation tasks
    :param system_instruction: System instruction
    :param gemini_model: Model name to use
    :param temperature: Generation temperature
    :param max_retries: Number of retry attempts
    :param retry_delay: Delay between retries in seconds

    returns: GeminiResponse containing the results
    """

    client = genai.Client(api_key=api_key)
    messages = []

    response_schema = type(translation_tasks)

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=gemini_model,
                contents=translation_tasks.model_dump_json(),
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=temperature,
                ),
            )

            if not response.parsed:
                raise ValueError("Empty response from Gemini API")

            translation_res = response.parsed
            total_token_count = response.usage_metadata.total_token_count
            return GeminiResponse(
                tasks=translation_res.tasks,
                total_token_count=total_token_count or 0,
                success=True,
            )

        except Exception as e:
            messages.append(f"Attempt {attempt} failed: {str(e)}")
            if attempt < max_retries:
                time.sleep(retry_delay)

    return GeminiResponse(
        tasks=[],
        total_token_count=0,
        success=False,
        message="All retry attempts failed. " + "\n".join(messages),
    )