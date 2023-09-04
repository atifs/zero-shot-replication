"""Run the zero-shot replication."""
import argparse
import os

import openai
from evalplus.data import write_jsonl

from zero_shot_replication.core import OUTPUT_FILE_NAME, ProblemType
from zero_shot_replication.core.utils import (
    extract_code,
    get_configured_logger,
    get_root_dir,
    load_existing_jsonl,
    parse_arguments,
    prep_for_file_path,
)
from zero_shot_replication.datasets import get_dataset
from zero_shot_replication.llm_providers import ProviderManager, ProviderName
from zero_shot_replication.model import ModelName, Quantization


def get_output_path(args: argparse.Namespace, version: str) -> str:
    """Get the output path for the given arguments."""

    output_dir = os.path.join(
        get_root_dir(),
        "results",
        prep_for_file_path(args.provider),
        prep_for_file_path(args.pset),
        prep_for_file_path(args.model),
    )

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    py_interpreter_segment = "_py-interpreter" if args.py_interpreter else ""

    base_file_name = OUTPUT_FILE_NAME.format(
        PROVIDER=prep_for_file_path(args.provider),
        pset=prep_for_file_path(args.pset),
        MODEL=prep_for_file_path(args.model),
        TEMPERATURE=prep_for_file_path(str(args.temperature)),
        QUANTIZATION=prep_for_file_path(str(args.quantization)),
        VERSION=prep_for_file_path(version),
    )

    output_file_name = (
        base_file_name.rstrip(".jsonl") + py_interpreter_segment + ".jsonl"
    )

    return os.path.join(output_dir, args.output_file_name or output_file_name)


if __name__ == "__main__":
    """Run the zero-shot replication."""
    # Setup
    logger = get_configured_logger("zero_shot_replication", log_level="INFO")
    openai.api_key = os.getenv("OPENAI_API_KEY", "")
    args = parse_arguments()

    provider = ProviderName(args.provider)
    model = ModelName(args.model)
    quantization = Quantization(args.quantization)

    logger.info(
        f"Loading ModelName={model.value} from ProviderName={provider.value}."
    )

    # Build an LLM provider instance
    llm_provider = ProviderManager.get_provider(
        provider,
        model,
        quantization,
        temperature=args.temperature,
        stream=args.stream,
        py_interpreter=args.py_interpreter,
    )
    # What mode should the prompt be in?
    prompt_mode = llm_provider.model.prompt_mode

    # Get the corresponding dataset
    dataset = get_dataset(ProblemType(args.pset))

    # Get the output path
    out_path = get_output_path(args, llm_provider.model.VERSION)

    # Load existing results
    results = load_existing_jsonl(out_path)
    exising_task_ids = {
        result["task_id"] for result in results if "task_id" in result
    }

    # Run the experiment
    for task_id, problem in dataset.generator:
        if task_id in exising_task_ids:
            print(
                f"Continuing over existing task_id: {task_id} as it already exists."
            )
            continue

        prompt = llm_provider.model.get_formatted_prompt(problem, dataset)

        print(f"\n{'-'*200}\nTaskId:\n{task_id}\nPrompt:\n{prompt}\n")
        try:
            raw_completion = llm_provider.get_completion(prompt)
            if args.pset in ["human-eval", "leetcode", "leetcode-msft-sparks"]:
                # or other codegen
                completion = extract_code(raw_completion)
            else:
                completion = raw_completion

            print(f"Extracted Completion:\n{completion}\n")

            result = {
                **problem,
                "task_id": task_id,
                "completion": completion,
                "raw_completion": raw_completion,
                "actual_prompt": prompt,
            }
            results.append(result)

        except (
            openai.error.OpenAIError,
            Exception,
        ) as e:  # Catch any OpenAI specific errors and general exceptions
            print(f"Error encountered for task_id {task_id}: {e}")
            result = {
                **problem,
                "task_id": task_id,
                "completion": "Error encountered",
                "raw_completion": "Error encountered",
                "actual_prompt": prompt,
            }

        write_jsonl(out_path, results)
