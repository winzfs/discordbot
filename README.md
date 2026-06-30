# Discord Bot

유지보수와 기능 확장을 쉽게 하기 위한 Python 기반 Discord 봇 템플릿입니다.

## 구조

```text
.
├── main.py                 # 실행 진입점
├── bot/
│   ├── app.py              # 봇 클래스와 확장 자동 로딩
│   ├── config.py           # 환경변수 설정
│   ├── logging_config.py   # 로깅 설정
│   └── cogs/               # 기능별 모듈
│       └── general.py      # 기본 예제 기능
├── .env.example
├── .gitignore
└── requirements.txt
```

## 설치 및 실행

Python 3.11 이상을 권장합니다.

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

의존성 설치:

```bash
pip install -r requirements.txt
```

`.env.example`을 `.env`로 복사한 뒤 Discord 봇 토큰을 입력합니다.

```env
DISCORD_TOKEN=your_bot_token
COMMAND_PREFIX=!
LOG_LEVEL=INFO
```

실행:

```bash
python main.py
```

## 새 기능 추가

`bot/cogs/` 아래에 새 Python 파일을 만들면 시작 시 자동으로 로드됩니다.

```python
from discord.ext import commands


class Example(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="예제")
    async def example(self, ctx: commands.Context) -> None:
        await ctx.send("새 기능입니다.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Example(bot))
```

파일명 앞에 `_`를 붙이면 자동 로딩에서 제외됩니다.
