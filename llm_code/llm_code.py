import sys
from pathlib import Path
from typing import Optional

import click
import openai
from pydantic import BaseSettings
from rich.console import Console
from rich.syntax import Syntax

from llm_code import __version__, db

from .templates import Message, TemplateLibrary


class Settings(BaseSettings):
    openai_api_key: str = ""
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.8
    max_tokens: int = 1000
    config_dir: Path = Path("~/.llm_code").expanduser()

    class Config:
        env_file = Path("~/.llm_code").expanduser() / "env"
        env_file_encoding = "utf-8"


def load_templates(path: Path) -> Optional[TemplateLibrary]:
    path = path / "prompts"
    if path.exists():
        return TemplateLibrary.from_file_or_directory(path)
    else:
        return None


def initdb(config_dir: Path):
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "db.sqlite"
    _ = db.Database.get(db_path)


@click.command()
@click.option("-i", "--inputs", default=None, help="Glob of input files.")
@click.option("-ln", "--line-numbers", is_flag=True, help="Show line numbers.")
@click.option("--version", is_flag=True, help="Show version.")
@click.argument("instructions", nargs=-1)
def main(inputs, line_numbers, instructions, version):
    """Coding assistant using OpenAI's chat models.

    Requires OPENAI_API_KEY as an environment variable. Alternately, you can set it in
    ~/.llm_code/env.
    """
    console = Console()

    if version:
        console.print(f"[bold green]llm_code[/] version {__version__}")
        sys.exit(0)

    settings = Settings()
    initdb(settings.config_dir)

    if not settings.openai_api_key:
        raise click.UsageError("OPENAI_API_KEY must be set.")

    instructions = " ".join(instructions)
    if not instructions:
        raise click.UsageError("Please provide some instructions.")

    library = load_templates(settings.config_dir) or load_templates(
        Path(__file__).parent.parent
    )
    if not library:
        raise click.UsageError("No templates found.")

    inputs = Path.cwd().glob(inputs) if inputs else []
    input = "\n\n".join([i.read_text() for i in inputs])

    if input:
        message = library["coding/input"].message(code=input, instructions=instructions)
    else:
        message = library["coding/simple"].message(instructions=instructions)

    messages = [library["coding/system"].message(), message]

    with console.status("[bold green]Asking OpenAI..."):
        response = openai.ChatCompletion.create(
            api_key=settings.openai_api_key,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            messages=messages,
        )

    message = Message.from_message(response.choices[0]["message"])  # type: ignore

    db.write(
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        system_message=messages[0]["content"],
        user_message=messages[1]["content"],
        assistant_message=message.content,
        input_tokens=response.usage["prompt_tokens"],  # type: ignore
        output_tokens=response.usage["completion_tokens"],  # type: ignore
    )

    code = message.code()
    if code:
        console.print(Syntax(code.code, code.lang, line_numbers=line_numbers))
    else:
        console.print(f"No code found in message: \n\n{message.content}")
        sys.exit(1)


if __name__ == "__main__":
    main()
