# Discord Bot

유지보수와 기능 확장을 쉽게 하기 위한 Python 기반 Discord 봇입니다.

## 구조

```text
.
├── main.py                    # 실행 진입점
├── bot/
│   ├── app.py                 # 봇 클래스와 Cog 자동 로딩
│   ├── config.py              # 환경변수 설정
│   ├── logging_config.py      # 로깅 설정
│   └── cogs/                  # 기능별 모듈
│       └── general.py         # 기본 예제 기능
├── .github/workflows/
│   └── validate.yml           # 자동 문법·의존성 검사
├── Dockerfile                 # 클라우드 실행 이미지
├── railway.json               # Railway 배포 설정
├── render.yaml                # Render Worker 배포 설정
├── .env.example
├── .gitignore
└── requirements.txt
```

## 클라우드 배포

이 봇은 Discord Gateway와 계속 연결되어 있어야 하므로 일반적인 서버리스 웹 함수가 아니라 상시 실행 서비스 또는 Background Worker로 배포해야 합니다.

### Railway

1. Railway에서 `winzfs/discordbot` GitHub 저장소를 연결합니다.
2. 서비스 Variables에 다음 값을 등록합니다.

```env
DISCORD_TOKEN=Discord 봇 토큰
COMMAND_PREFIX=!
LOG_LEVEL=INFO
MESSAGE_CONTENT_INTENT=true
MEMBERS_INTENT=false
```

3. 저장소의 `Dockerfile`과 `railway.json`이 자동으로 적용됩니다.
4. Public Domain은 만들 필요가 없습니다.

### Render

1. Render에서 Blueprint 생성 후 이 저장소를 선택합니다.
2. `render.yaml`에 따라 `discordbot` Background Worker가 생성됩니다.
3. 생성 과정에서 `DISCORD_TOKEN`만 비밀 환경변수로 입력합니다.

## Discord 설정

Discord Developer Portal의 Bot 설정에서 **Message Content Intent**를 활성화해야 `!핑`과 같은 접두사 명령어가 동작합니다.

멤버 가입·퇴장이나 전체 멤버 조회 기능을 추가할 때는 **Server Members Intent**도 활성화하고 `MEMBERS_INTENT=true`로 변경합니다.

## 로컬 실행

```bash
pip install -r requirements.txt
python main.py
```

`.env.example`을 `.env`로 복사하고 토큰을 입력해야 합니다.

## 새 기능 추가

`bot/cogs/` 아래에 새 Python 파일을 만들면 봇 시작 시 자동으로 로드됩니다.

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
