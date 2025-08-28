import sys
import json
import time
from typing import List, Dict, Any, Type, Union

from pydantic import BaseModel, ValidationError


class Context(BaseModel):
    original_text: str


class Vocabulary(BaseModel):
    lemma: str
    Chinese: str


class VocabularyTranslationTask(BaseModel):
    index: int
    vocabulary: List[Vocabulary]
    context: Context


class DialogueTranslationTask(BaseModel):
    index: int
    original_text: str
    Chinese: str


class GeminiResponse(BaseModel):
    tasks: List[Union[VocabularyTranslationTask, DialogueTranslationTask]]
    total_token_count: int
    success: bool
    message: str = ""


def validate_input_data(request_data: Dict[str, Any]) -> None:
    """Validate the input data structure"""
    if not isinstance(request_data, dict):
        raise ValueError("Input data must be a dictionary")
    if "tasks" not in request_data:
        raise ValueError("Missing 'tasks' in input data")
    if "params" not in request_data:
        raise ValueError("Missing 'params' in input data")

    params = request_data["params"]
    required_params = ["api_key", "system_instruction", "schema"]
    for param in required_params:
        if param not in params:
            raise ValueError(f"Missing required parameter: {param}")


def get_task_schema(schema_name: str) -> Type[BaseModel]:
    """Get the appropriate schema class based on the schema name"""
    schema_map = {
        'DialogueTranslationTask': DialogueTranslationTask,
        'VocabularyTranslationTask': VocabularyTranslationTask
    }
    if schema_name not in schema_map:
        raise ValueError(f"Unknown schema name: {schema_name}")
    return schema_map[schema_name]


def query_gemini(
        api_key: str,
        translation_tasks: List[Dict[str, Any]],
        task_schema: Type[Union[VocabularyTranslationTask, DialogueTranslationTask]],
        system_instruction: str,
        gemini_model: str = "gemini-2.0-flash",
        temperature: float = 0.3,
        max_retries: int = 3,
        retry_delay: int = 10
) -> GeminiResponse:
    """
    Query the Gemini API for translation tasks with retry logic.

    Args:
        api_key: Gemini API key
        translation_tasks: List of translation tasks
        task_schema: Pydantic model for the task type
        system_instruction: System instruction for the model
        gemini_model: Model name to use
        temperature: Generation temperature
        max_retries: Number of retry attempts
        retry_delay: Delay between retries in seconds

    Returns:
        GeminiResponse containing the results
    """
    from google import genai
    from google.genai import types
    from google.genai.types import SchemaUnion
    client = genai.Client(api_key=api_key)
    messages = []
    translation_res = []
    total_token_count = 0

    # Validate input tasks before sending to API
    try:
        translation_res = [task_schema(**task) for task in translation_tasks]
    except ValidationError as e:
        return GeminiResponse(
            tasks=[],
            total_token_count=0,
            success=False,
            message=f"Input validation failed: {str(e)}"
        )

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=gemini_model,
                contents=json.dumps(translation_tasks, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=list[task_schema],
                    temperature=temperature
                ),
            )

            if not response.parsed:
                raise ValueError("Empty response from Gemini API")

            translation_res = response.parsed
            total_token_count = response.usage_metadata.total_token_count
            return GeminiResponse(
                tasks=translation_res,
                total_token_count=total_token_count,
                success=True
            )

        except Exception as e:
            messages.append(f"Attempt {attempt} failed: {str(e)}")
            if attempt < max_retries:
                time.sleep(retry_delay)

    return GeminiResponse(
        tasks=[],
        total_token_count=0,
        success=False,
        message="All retry attempts failed. " + "\n".join(messages)
    )


def main():
    try:
        # Read and parse input
        '''{
        	"tasks": [{
        		"index": 0,
        		"original_text": "That was eight years ago.",
        		"Chinese": ""
        	}, {
        		"index": 1,
        		"original_text": "Much has changed.",
        		"Chinese": ""
        	}],
        	"params": {
        		"api_key": "",
        		"system_instruction": "You are an expert translator. You will be given a list of dialogue translation tasks in JSON format. For each entry, provide the most appropriate translation in Simplified Chinese based on the context. \\nOnly complete the `Chinese` field. Do not include pinyin, explanations, or any additional information.",
        		"schema": "DialogueTranslationTask"
        	}
        }'''
        input_text = sys.stdin.read()
        if not input_text:
            raise ValueError("No input provided")

        request_data = json.loads(input_text)
        validate_input_data(request_data)

        # Extract parameters
        tasks = request_data["tasks"]
        params = request_data["params"]

        # Get schema and make API call
        schema = get_task_schema(params["schema"])
        response = query_gemini(
            api_key=params["api_key"],
            translation_tasks=tasks,
            task_schema=schema,
            system_instruction=params["system_instruction"],
            gemini_model=params.get("model", "gemini-2.0-flash"),
            temperature=float(params.get("temperature", 0.3)),
            max_retries=int(params.get("max_retries", 3))
        )

        # Prepare output
        if response.success:
            result = {
                "success": True,
                "data": {
                    "tasks": [task.model_dump() for task in response.tasks],
                    "total_token_count": response.total_token_count
                }
            }
        else:
            result = {
                "success": False,
                "message": response.message
            }

        print(json.dumps(result, ensure_ascii=False))

    except json.JSONDecodeError as e:
        error = {
            "success": False,
            "message": f"Invalid JSON input: {str(e)}"
        }
        print(json.dumps(error))
    except Exception as e:
        error = {
            "success": False,
            "message": f"Unexpected error: {str(e)}"
        }
        print(json.dumps(error))


if __name__ == "__main__":
    main()