#!/usr/bin/env python
from typing import Generator
import runpod
from utils import validate_sampling_params, ServerlessConfig, random_uuid
from engine import VLLMEngine


serverless_config = ServerlessConfig()
vllm_engine = VLLMEngine()


def concurrency_modifier(current_concurrency) -> int:
    return max(0, serverless_config.max_concurrency - vllm_engine.get_n_current_jobs)

async def handler(job: dict) -> Generator[dict, None, None]:
    job_input = job["input"]
    llm_input, apply_chat_template = job_input.get(
        "prompt", job_input["messages"]
    ), job_input.get("apply_chat_template", False)

    if apply_chat_template or isinstance(llm_input, list):
        llm_input = vllm_engine.tokenizer.apply_chat_template(llm_input)

    stream = job_input.get("stream", False)
    batch_size = job_input.get("batch_size", serverless_config.default_batch_size)
    sampling_params = job_input.get("sampling_params", {})

    validated_params = validate_sampling_params(sampling_params)
    request_id = random_uuid()
    results_generator = vllm_engine.llm.generate(
        llm_input, validated_params, request_id
    )

    batch, last_output_text = [], ""
    async for request_output in results_generator:
        for output in request_output.outputs:
            usage = {
                "input": len(request_output.prompt_token_ids),
                "output": len(output.token_ids),
            }

            if stream:
                batch.append(
                    {"text": output.text[len(last_output_text) :], "usage": usage}
                )
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            last_output_text = output.text

    if not stream:
        yield [{"text": last_output_text, "usage": usage}]

    if batch:
        yield batch


runpod.serverless.start(
    {
        "handler": handler,
        "concurrency_modifier": concurrency_modifier,
        "return_aggregate_stream": True,
    }
)
