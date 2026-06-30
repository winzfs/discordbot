import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    command_prefix: str = "!"
    log_level: str = "INFO"
    message_content_intent: bool = True
    members_intent: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "DISCORD_TOKEN이 설정되지 않았습니다. "
                ".env.example을 참고해 환경변수를 설정해 주세요."
            )

        return cls(
            discord_token=token,
            command_prefix=os.getenv("COMMAND_PREFIX", "!").strip() or "!",
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            message_content_intent=_to_bool(
                os.getenv("MESSAGE_CONTENT_INTENT"), default=True
            ),
            members_intent=_to_bool(os.getenv("MEMBERS_INTENT"), default=True),
        )


def _to_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}
