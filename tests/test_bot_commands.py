from unittest.mock import AsyncMock

from admin.bot_commands import BOT_COMMANDS, register_commands


def test_bot_commands_cover_all_ten_commands():
    names = {command.command for command in BOT_COMMANDS}
    assert names == {
        "addword",
        "delword",
        "listwords",
        "warns",
        "resetwarns",
        "setresetdays",
        "setinterval",
        "addmsg",
        "delmsg",
        "listmsgs",
    }


async def test_register_commands_calls_set_my_commands():
    bot = AsyncMock()

    await register_commands(bot)

    bot.set_my_commands.assert_awaited_once_with(BOT_COMMANDS)
